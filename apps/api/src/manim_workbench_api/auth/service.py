from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from argon2.low_level import Type
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from .errors import (
    AUTHENTICATION_FAILED,
    AUTHORIZATION_FAILED,
    INVALID_USER_INPUT,
    LOGIN_RATE_LIMITED,
    USER_ALREADY_EXISTS,
    AuthError,
)
from .models import AuthenticatedSession, AuthSettings, SessionPrincipal

LOGIN_WINDOW = timedelta(minutes=15)
MAX_FAILED_LOGIN_ATTEMPTS = 5
_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$61ighTfqZ2OWQFc9/AQzUQ$"
    "ePNxsLtrnD063WEzZFsj9tyzMVcgnEzqc1GJ5reAJDk"
)


class AuthService:
    """Authentication operations backed exclusively by parameterized SQL."""

    def __init__(self, engine: Engine, password_hasher: PasswordHasher | None = None) -> None:
        self._engine = engine
        self._password_hasher = password_hasher or PasswordHasher(type=Type.ID)

    def create_user(self, email: str, password: str) -> SessionPrincipal:
        normalized_email = self._normalize_email(email)
        if not self._email_is_valid(normalized_email):
            raise INVALID_USER_INPUT
        now = self._now()
        user_id = uuid4()
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email, created_at, password_hash, must_change_password, "
                        "password_changed_at) VALUES (:id, :email, :created_at, :password_hash, "
                        ":must_change_password, "
                        ":password_changed_at)"
                    ),
                    {
                        "id": str(user_id),
                        "email": normalized_email,
                        "created_at": self._serialize(now),
                        "password_hash": self._password_hasher.hash(password),
                        "must_change_password": True,
                        "password_changed_at": self._serialize(now),
                    },
                )
        except IntegrityError as error:
            raise USER_ALREADY_EXISTS from error
        return SessionPrincipal(
            user_id=user_id,
            email=normalized_email,
            created_at=now,
            must_change_password=True,
            session_id=UUID(int=0),
            expires_at=now,
        )

    def login(
        self,
        *,
        email: str,
        password: str,
        remote_addr: str | None,
        settings: AuthSettings,
    ) -> AuthenticatedSession:
        normalized_email = self._normalize_email(email)
        identifier_hash = self._digest(normalized_email)
        remote_addr_hash = self._digest(remote_addr or "unknown")
        now = self._now()
        authenticated: AuthenticatedSession | None = None
        failure: AuthError | None = None
        with self._engine.begin() as connection:
            failures = connection.execute(
                text(
                    "SELECT COUNT(*) FROM login_attempts "
                    "WHERE identifier_hash = :identifier_hash "
                    "AND remote_addr_hash = :remote_addr_hash "
                    "AND attempted_at >= :window_start AND succeeded = :succeeded"
                ),
                {
                    "identifier_hash": identifier_hash,
                    "remote_addr_hash": remote_addr_hash,
                    "window_start": self._serialize(now - LOGIN_WINDOW),
                    "succeeded": False,
                },
            ).scalar_one()
            if failures >= MAX_FAILED_LOGIN_ATTEMPTS:
                failure = LOGIN_RATE_LIMITED
            else:
                row = (
                    connection.execute(
                        text(
                            "SELECT id, email, created_at, password_hash, must_change_password, "
                            "disabled_at FROM users WHERE email = :email"
                        ),
                        {"email": normalized_email},
                    )
                    .mappings()
                    .one_or_none()
                )
                password_hash = (
                    row["password_hash"] if row and row["password_hash"] else _DUMMY_PASSWORD_HASH
                )
                password_valid = self._password_is_valid(password_hash, password)
                usable = bool(row and password_valid and row["disabled_at"] is None)
                self._record_login_attempt(
                    connection,
                    identifier_hash=identifier_hash,
                    remote_addr_hash=remote_addr_hash,
                    attempted_at=now,
                    succeeded=usable,
                )
                if not usable:
                    failure = AUTHENTICATION_FAILED
                else:
                    authenticated = self._create_session(connection, row, now, settings)
        if failure:
            raise failure
        if not authenticated:
            raise AUTHENTICATION_FAILED
        return authenticated

    def get_session(self, token: str, settings: AuthSettings) -> AuthenticatedSession:
        with self._engine.begin() as connection:
            principal = self._load_principal(connection, token, revoke_invalid=True)
            csrf_token = self._new_token()
            connection.execute(
                text(
                    "UPDATE sessions SET csrf_token_hash = :csrf_token_hash, "
                    "last_seen_at = :last_seen_at WHERE id = :id"
                ),
                {
                    "csrf_token_hash": self._digest(csrf_token),
                    "last_seen_at": self._serialize(self._now()),
                    "id": str(principal.session_id),
                },
            )
        return AuthenticatedSession(principal=principal, token=token, csrf_token=csrf_token)

    def get_principal(self, token: str) -> SessionPrincipal:
        with self._engine.begin() as connection:
            return self._load_principal(connection, token, revoke_invalid=True)

    def authorize_mutation(
        self,
        *,
        token: str,
        csrf_token: str,
        origin: str | None,
        settings: AuthSettings,
    ) -> SessionPrincipal:
        self._require_origin(origin, settings)
        with self._engine.begin() as connection:
            principal = self._load_principal(connection, token, revoke_invalid=True)
            self._validate_csrf(connection, principal.session_id, csrf_token)
        if not principal.is_ready:
            raise AUTHORIZATION_FAILED
        return principal

    def logout(
        self, token: str, csrf_token: str, origin: str | None, settings: AuthSettings
    ) -> None:
        self._require_origin(origin, settings)
        with self._engine.begin() as connection:
            principal = self._load_principal(connection, token, revoke_invalid=True)
            self._validate_csrf(connection, principal.session_id, csrf_token)
            connection.execute(
                text("UPDATE sessions SET revoked_at = :revoked_at WHERE id = :id"),
                {"revoked_at": self._serialize(self._now()), "id": str(principal.session_id)},
            )

    def change_password(
        self,
        *,
        token: str,
        csrf_token: str,
        origin: str | None,
        current_password: str,
        new_password: str,
        settings: AuthSettings,
    ) -> AuthenticatedSession:
        self._require_origin(origin, settings)
        now = self._now()
        with self._engine.begin() as connection:
            principal = self._load_principal(connection, token, revoke_invalid=True)
            self._validate_csrf(connection, principal.session_id, csrf_token)
            row = (
                connection.execute(
                    text("SELECT password_hash FROM users WHERE id = :id AND disabled_at IS NULL"),
                    {"id": str(principal.user_id)},
                )
                .mappings()
                .one_or_none()
            )
            if (
                not row
                or not row["password_hash"]
                or not self._password_is_valid(row["password_hash"], current_password)
            ):
                raise AUTHENTICATION_FAILED
            connection.execute(
                text(
                    "UPDATE users SET password_hash = :password_hash, "
                    "must_change_password = :required, password_changed_at = :password_changed_at "
                    "WHERE id = :id"
                ),
                {
                    "password_hash": self._password_hasher.hash(new_password),
                    "required": False,
                    "password_changed_at": self._serialize(now),
                    "id": str(principal.user_id),
                },
            )
            connection.execute(
                text("UPDATE sessions SET revoked_at = :revoked_at WHERE user_id = :user_id"),
                {"revoked_at": self._serialize(now), "user_id": str(principal.user_id)},
            )
            refreshed = {
                "id": str(principal.user_id),
                "email": principal.email,
                "created_at": self._serialize(principal.created_at),
                "must_change_password": False,
            }
            return self._create_session(connection, refreshed, now, settings)

    def _create_session(
        self, connection, user, now: datetime, settings: AuthSettings
    ) -> AuthenticatedSession:  # type: ignore[no-untyped-def]
        token = self._new_token()
        csrf_token = self._new_token()
        session_id = uuid4()
        expires_at = now + timedelta(seconds=settings.session_max_age_seconds)
        connection.execute(
            text(
                "INSERT INTO sessions "
                "(id, user_id, token_hash, csrf_token_hash, created_at, last_seen_at, expires_at, "
                "revoked_at, user_agent_hash, remote_addr_hash) "
                "VALUES (:id, :user_id, :token_hash, :csrf_token_hash, :created_at, :last_seen_at, "
                ":expires_at, NULL, NULL, NULL)"
            ),
            {
                "id": str(session_id),
                "user_id": user["id"],
                "token_hash": self._digest(token),
                "csrf_token_hash": self._digest(csrf_token),
                "created_at": self._serialize(now),
                "last_seen_at": self._serialize(now),
                "expires_at": self._serialize(expires_at),
            },
        )
        principal = SessionPrincipal(
            user_id=UUID(str(user["id"])),
            email=str(user["email"]),
            created_at=self._parse_datetime(str(user["created_at"])),
            must_change_password=bool(user["must_change_password"]),
            session_id=session_id,
            expires_at=expires_at,
        )
        return AuthenticatedSession(principal=principal, token=token, csrf_token=csrf_token)

    def _load_principal(self, connection, token: str, *, revoke_invalid: bool) -> SessionPrincipal:  # type: ignore[no-untyped-def]
        row = (
            connection.execute(
                text(
                    "SELECT sessions.id AS session_id, sessions.user_id, sessions.expires_at, "
                    "sessions.revoked_at, users.email, users.created_at, "
                    "users.must_change_password, users.disabled_at FROM sessions "
                    "JOIN users ON users.id = sessions.user_id "
                    "WHERE sessions.token_hash = :token_hash"
                ),
                {"token_hash": self._digest(token)},
            )
            .mappings()
            .one_or_none()
        )
        now = self._now()
        if not row:
            raise AUTHENTICATION_FAILED
        expires_at = self._parse_datetime(str(row["expires_at"]))
        invalid = (
            row["revoked_at"] is not None or row["disabled_at"] is not None or expires_at <= now
        )
        if invalid:
            if revoke_invalid and row["revoked_at"] is None:
                connection.execute(
                    text("UPDATE sessions SET revoked_at = :revoked_at WHERE id = :id"),
                    {"revoked_at": self._serialize(now), "id": row["session_id"]},
                )
            raise AUTHENTICATION_FAILED
        return SessionPrincipal(
            user_id=UUID(str(row["user_id"])),
            email=str(row["email"]),
            created_at=self._parse_datetime(str(row["created_at"])),
            must_change_password=bool(row["must_change_password"]),
            session_id=UUID(str(row["session_id"])),
            expires_at=expires_at,
        )

    def _validate_csrf(self, connection, session_id: UUID, csrf_token: str) -> None:  # type: ignore[no-untyped-def]
        stored = connection.execute(
            text("SELECT csrf_token_hash FROM sessions WHERE id = :id"), {"id": str(session_id)}
        ).scalar_one_or_none()
        if not stored or not secrets.compare_digest(str(stored), self._digest(csrf_token)):
            raise AUTHORIZATION_FAILED

    @staticmethod
    def _require_origin(origin: str | None, settings: AuthSettings) -> None:
        if not origin or origin.rstrip("/") not in settings.allowed_origins:
            raise AUTHORIZATION_FAILED

    def _password_is_valid(self, password_hash: str, password: str) -> bool:
        try:
            return self._password_hasher.verify(password_hash, password)
        except (VerificationError, VerifyMismatchError):
            return False

    @staticmethod
    def _record_login_attempt(
        connection,
        *,
        identifier_hash: str,
        remote_addr_hash: str,
        attempted_at: datetime,
        succeeded: bool,
    ) -> None:  # type: ignore[no-untyped-def]
        connection.execute(
            text(
                "INSERT INTO login_attempts "
                "(identifier_hash, remote_addr_hash, attempted_at, succeeded) "
                "VALUES (:identifier_hash, :remote_addr_hash, :attempted_at, :succeeded)"
            ),
            {
                "identifier_hash": identifier_hash,
                "remote_addr_hash": remote_addr_hash,
                "attempted_at": AuthService._serialize(attempted_at),
                "succeeded": succeeded,
            },
        )

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _email_is_valid(email: str) -> bool:
        local, separator, domain = email.partition("@")
        return bool(
            separator
            and local
            and domain
            and len(email) <= 320
            and not any(character.isspace() for character in email)
        )

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _serialize(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
