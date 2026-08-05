from __future__ import annotations

from dataclasses import dataclass

from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class JobError(Exception):
    status_code: int
    code: str
    message: str

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={"error": {"code": self.code, "message": self.message}},
        )


INTERNAL_TOKEN_INVALID = JobError(401, "INTERNAL_TOKEN_INVALID", "internal token is invalid")
JOB_NOT_FOUND = JobError(404, "JOB_NOT_FOUND", "render job was not found")
JOB_NOT_CLAIMABLE = JobError(409, "JOB_NOT_CLAIMABLE", "render job cannot be claimed")
IDENTITY_CONFLICT = JobError(
    409, "IDENTITY_CONFLICT", "idempotency key belongs to a different render job"
)
WORK_ITEM_INVALID = JobError(409, "WORK_ITEM_INVALID", "render work item is not executable")
LEASE_INVALID = JobError(409, "LEASE_INVALID", "lease is invalid or expired")
STATE_CONFLICT = JobError(409, "STATE_CONFLICT", "render job state does not allow this operation")
CANCELLATION_REQUESTED = JobError(
    409, "CANCELLATION_REQUESTED", "render job cancellation was requested"
)
ARTIFACT_SET_INVALID = JobError(
    422, "ARTIFACT_SET_INVALID", "artifacts must contain each required kind"
)
VALIDATION_ERROR = JobError(422, "VALIDATION_ERROR", "request payload is invalid")
