from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    ContentPlanDraft,
    ContentPlanVersion,
    Project,
    ProjectPage,
    PromptVersion,
)
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from .errors import PROJECT_NOT_FOUND, VERSION_CONFLICT


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


class ProjectRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_project(self, owner_id: UUID, title: str) -> Project:
        project = Project(
            id=uuid4(),
            owner_id=owner_id,
            title=title,
            created_at=utc_now(),
            archived_at=None,
        )
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, owner_id, title, created_at, archived_at, updated_at) "
                    "VALUES (:id, :owner_id, :title, :created_at, NULL, :updated_at)"
                ),
                {
                    "id": str(project.id),
                    "owner_id": str(owner_id),
                    "title": title,
                    "created_at": project.created_at.isoformat(),
                    "updated_at": project.created_at.isoformat(),
                },
            )
        return project

    def list_projects(self, owner_id: UUID, cursor: UUID | None, limit: int) -> ProjectPage:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT id, owner_id, title, created_at, archived_at FROM projects "
                        "WHERE owner_id = :owner_id AND (:cursor IS NULL OR id > :cursor) "
                        "ORDER BY id ASC LIMIT :fetch_limit"
                    ),
                    {
                        "owner_id": str(owner_id),
                        "cursor": str(cursor) if cursor else None,
                        "fetch_limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
        has_next = len(rows) > limit
        visible = rows[:limit]
        return ProjectPage(
            items=tuple(self._project_from_row(row) for row in visible),
            next_cursor=UUID(str(visible[-1]["id"])) if has_next and visible else None,
        )

    def get_project(self, project_id: UUID, owner_id: UUID) -> Project:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT id, owner_id, title, created_at, archived_at FROM projects "
                        "WHERE id = :project_id AND owner_id = :owner_id"
                    ),
                    {"project_id": str(project_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PROJECT_NOT_FOUND
        return self._project_from_row(row)

    def update_project(
        self,
        project_id: UUID,
        owner_id: UUID,
        *,
        title: str | None,
        archived: bool | None,
    ) -> Project:
        archived_at = utc_now().isoformat() if archived is True else None
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "UPDATE projects SET "
                        "title = CASE WHEN :title IS NULL THEN title ELSE :title END, "
                        "archived_at = CASE "
                        "WHEN :archived IS NULL THEN archived_at "
                        "WHEN :archived = 1 THEN :archived_at ELSE NULL END, "
                        "updated_at = :updated_at "
                        "WHERE id = :project_id AND owner_id = :owner_id "
                        "RETURNING id, owner_id, title, created_at, archived_at"
                    ),
                    {
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "title": title,
                        "archived": archived,
                        "archived_at": archived_at,
                        "updated_at": utc_now().isoformat(),
                    },
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PROJECT_NOT_FOUND
        return self._project_from_row(row)

    def list_prompt_versions(
        self,
        project_id: UUID,
        owner_id: UUID,
        cursor: int | None,
        limit: int,
    ) -> tuple[tuple[PromptVersion, ...], int | None]:
        self._require_project(project_id, owner_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT id, project_id, owner_id, version, parent_version_id, created_at, "
                        "prompt "
                        "FROM prompt_versions WHERE project_id = :project_id "
                        "AND owner_id = :owner_id "
                        "AND (:cursor IS NULL OR version < :cursor) "
                        "ORDER BY version DESC LIMIT :fetch_limit"
                    ),
                    {
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "cursor": cursor,
                        "fetch_limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
        page_rows = rows[:limit]
        next_cursor = int(page_rows[-1]["version"]) if len(rows) > limit else None
        return tuple(self._prompt_from_row(row) for row in page_rows), next_cursor

    def append_prompt_version(self, project_id: UUID, owner_id: UUID, prompt: str) -> PromptVersion:
        try:
            with self._engine.begin() as connection:
                self._require_project_with_connection(connection, project_id, owner_id)
                current = (
                    connection.execute(
                        text(
                            "SELECT id, version FROM prompt_versions "
                            "WHERE project_id = :project_id AND owner_id = :owner_id "
                            "ORDER BY version DESC LIMIT 1"
                        ),
                        {"project_id": str(project_id), "owner_id": str(owner_id)},
                    )
                    .mappings()
                    .one_or_none()
                )
                version = 1 if current is None else int(current["version"]) + 1
                parent_id = None if current is None else UUID(str(current["id"]))
                record = PromptVersion(
                    id=uuid4(),
                    project_id=project_id,
                    owner_id=owner_id,
                    version=version,
                    parent_version_id=parent_id,
                    created_at=utc_now(),
                    prompt=prompt,
                )
                connection.execute(
                    text(
                        "INSERT INTO prompt_versions "
                        "(id, project_id, owner_id, version, parent_version_id, created_at, "
                        "prompt) "
                        "VALUES (:id, :project_id, :owner_id, :version, :parent_version_id, "
                        ":created_at, :prompt)"
                    ),
                    self._prompt_insert_values(record),
                )
        except (IntegrityError, OperationalError) as error:
            self._raise_version_conflict_if_concurrent(error)
        return record

    def list_content_plan_versions(
        self,
        project_id: UUID,
        owner_id: UUID,
        cursor: int | None,
        limit: int,
    ) -> tuple[tuple[ContentPlanVersion, ...], int | None]:
        self._require_project(project_id, owner_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT id, project_id, owner_id, version, parent_version_id, created_at, "
                        "schema_version, content_json FROM content_plan_versions "
                        "WHERE project_id = :project_id AND owner_id = :owner_id "
                        "AND (:cursor IS NULL OR version < :cursor) "
                        "ORDER BY version DESC LIMIT :fetch_limit"
                    ),
                    {
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "cursor": cursor,
                        "fetch_limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
        page_rows = rows[:limit]
        next_cursor = int(page_rows[-1]["version"]) if len(rows) > limit else None
        return tuple(self._content_plan_from_row(row) for row in page_rows), next_cursor

    def append_content_plan_version(
        self,
        project_id: UUID,
        owner_id: UUID,
        parent_version_id: UUID,
        draft: ContentPlanDraft,
    ) -> ContentPlanVersion:
        try:
            with self._engine.begin() as connection:
                self._require_project_with_connection(connection, project_id, owner_id)
                current = (
                    connection.execute(
                        text(
                            "SELECT id, version FROM content_plan_versions "
                            "WHERE project_id = :project_id AND owner_id = :owner_id "
                            "ORDER BY version DESC LIMIT 1"
                        ),
                        {"project_id": str(project_id), "owner_id": str(owner_id)},
                    )
                    .mappings()
                    .one_or_none()
                )
                if current is None or str(current["id"]) != str(parent_version_id):
                    raise VERSION_CONFLICT
                record = ContentPlanVersion(
                    id=uuid4(),
                    project_id=project_id,
                    owner_id=owner_id,
                    version=int(current["version"]) + 1,
                    parent_version_id=parent_version_id,
                    created_at=utc_now(),
                    **draft.model_dump(),
                )
                connection.execute(
                    text(
                        "INSERT INTO content_plan_versions "
                        "(id, project_id, owner_id, version, parent_version_id, created_at, "
                        "schema_version, content_json) VALUES (:id, :project_id, :owner_id, "
                        ":version, :parent_version_id, :created_at, :schema_version, :content_json)"
                    ),
                    {
                        "id": str(record.id),
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "version": record.version,
                        "parent_version_id": str(parent_version_id),
                        "created_at": record.created_at.isoformat(),
                        "schema_version": record.schema_version,
                        "content_json": draft.model_dump_json(),
                    },
                )
        except (IntegrityError, OperationalError) as error:
            self._raise_version_conflict_if_concurrent(error)
        return record

    @staticmethod
    def _raise_version_conflict_if_concurrent(error: IntegrityError | OperationalError) -> None:
        if isinstance(error, IntegrityError) or "locked" in str(error).lower():
            raise VERSION_CONFLICT from error
        raise error

    def _require_project(self, project_id: UUID, owner_id: UUID) -> None:
        with self._engine.connect() as connection:
            self._require_project_with_connection(connection, project_id, owner_id)

    @staticmethod
    def _require_project_with_connection(connection, project_id: UUID, owner_id: UUID) -> None:  # type: ignore[no-untyped-def]
        row = connection.execute(
            text("SELECT id FROM projects WHERE id = :project_id AND owner_id = :owner_id"),
            {"project_id": str(project_id), "owner_id": str(owner_id)},
        ).one_or_none()
        if row is None:
            raise PROJECT_NOT_FOUND

    @staticmethod
    def _project_from_row(row) -> Project:  # type: ignore[no-untyped-def]
        return Project(
            id=UUID(str(row["id"])),
            owner_id=UUID(str(row["owner_id"])),
            title=str(row["title"]),
            created_at=_as_datetime(row["created_at"]),
            archived_at=_as_datetime(row["archived_at"]) if row["archived_at"] else None,
        )

    @staticmethod
    def _prompt_from_row(row) -> PromptVersion:  # type: ignore[no-untyped-def]
        return PromptVersion(
            id=UUID(str(row["id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            version=int(row["version"]),
            parent_version_id=(
                UUID(str(row["parent_version_id"])) if row["parent_version_id"] else None
            ),
            created_at=_as_datetime(row["created_at"]),
            prompt=str(row["prompt"]),
        )

    @staticmethod
    def _prompt_insert_values(record: PromptVersion) -> dict[str, object]:
        return {
            "id": str(record.id),
            "project_id": str(record.project_id),
            "owner_id": str(record.owner_id),
            "version": record.version,
            "parent_version_id": (
                str(record.parent_version_id) if record.parent_version_id else None
            ),
            "created_at": record.created_at.isoformat(),
            "prompt": record.prompt,
        }

    @staticmethod
    def _content_plan_from_row(row) -> ContentPlanVersion:  # type: ignore[no-untyped-def]
        draft = ContentPlanDraft.model_validate_json(str(row["content_json"]))
        return ContentPlanVersion(
            id=UUID(str(row["id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            version=int(row["version"]),
            parent_version_id=(
                UUID(str(row["parent_version_id"])) if row["parent_version_id"] else None
            ),
            created_at=_as_datetime(row["created_at"]),
            **draft.model_dump(),
        )
