from fastapi import FastAPI
from manim_workbench_api.workspace.router import router


def test_workspace_mutation_contracts_never_accept_owner_id() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    schema = app.openapi()

    for path in (
        "/api/v1/workspace/projects/{project_id}/content-plans/generate",
        "/api/v1/workspace/projects/{project_id}/code-generations",
        "/api/v1/workspace/projects/{project_id}/render-jobs",
    ):
        request_schema = schema["paths"][path]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        reference = request_schema["$ref"].rsplit("/", 1)[-1]
        assert "owner_id" not in schema["components"]["schemas"][reference]["properties"]
