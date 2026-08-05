from __future__ import annotations

from dataclasses import dataclass

from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class ProjectError(Exception):
    status_code: int
    code: str
    message: str

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={"error": {"code": self.code, "message": self.message}},
        )


PROJECT_NOT_FOUND = ProjectError(404, "project_not_found", "Project was not found.")
VERSION_CONFLICT = ProjectError(409, "version_conflict", "Version parent is no longer current.")
