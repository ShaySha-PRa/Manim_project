from __future__ import annotations

from uuid import UUID

from manim_workbench_contracts import (
    ContentPlanVersion,
    ContentPlanVersionCreateRequest,
    ContentPlanVersionPage,
    Project,
    ProjectCreateRequest,
    ProjectPage,
    ProjectUpdateRequest,
    PromptVersion,
    PromptVersionCreateRequest,
    PromptVersionPage,
)

from .repository import ProjectRepository


class ProjectService:
    """Owner-scoped project operations backed by append-only version records."""

    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    def create_project(self, owner_id: UUID, request: ProjectCreateRequest) -> Project:
        return self._repository.create_project(owner_id, request.title)

    def list_projects(self, owner_id: UUID, cursor: UUID | None, limit: int) -> ProjectPage:
        return self._repository.list_projects(owner_id, cursor, limit)

    def get_project(self, project_id: UUID, owner_id: UUID) -> Project:
        return self._repository.get_project(project_id, owner_id)

    def update_project(
        self, project_id: UUID, owner_id: UUID, request: ProjectUpdateRequest
    ) -> Project:
        return self._repository.update_project(
            project_id,
            owner_id,
            title=request.title,
            archived=request.archived,
        )

    def list_prompt_versions(
        self, project_id: UUID, owner_id: UUID, cursor: int | None, limit: int
    ) -> PromptVersionPage:
        items, next_cursor = self._repository.list_prompt_versions(
            project_id, owner_id, cursor, limit
        )
        return PromptVersionPage(items=items, next_cursor=next_cursor)

    def create_prompt_version(
        self, project_id: UUID, owner_id: UUID, request: PromptVersionCreateRequest
    ) -> PromptVersion:
        return self._repository.append_prompt_version(project_id, owner_id, request.prompt)

    def list_content_plan_versions(
        self, project_id: UUID, owner_id: UUID, cursor: int | None, limit: int
    ) -> ContentPlanVersionPage:
        items, next_cursor = self._repository.list_content_plan_versions(
            project_id, owner_id, cursor, limit
        )
        return ContentPlanVersionPage(items=items, next_cursor=next_cursor)

    def create_content_plan_version(
        self, project_id: UUID, owner_id: UUID, request: ContentPlanVersionCreateRequest
    ) -> ContentPlanVersion:
        return self._repository.append_content_plan_version(
            project_id,
            owner_id,
            request.parent_version_id,
            request.content_plan,
        )
