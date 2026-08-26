"""Add immutable composable-scene workflow versions and append-only run events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_video_workflows"
down_revision: str | None = "0009_render_job_typed_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _protect_append_only(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_prevent_update BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
    )
    op.execute(
        f"CREATE TRIGGER {table}_prevent_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
    )


def _enforce_monotonic_event(table: str, run_column: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER {table}_enforce_state_version
        BEFORE INSERT ON {table}
        BEGIN
          SELECT CASE
            WHEN NEW.state_version != COALESCE(
              (SELECT MAX(state_version) + 1 FROM {table}
               WHERE {run_column} = NEW.{run_column}),
              0
            )
            THEN RAISE(ABORT, '{table} state_version must be monotonic')
          END;
        END
        """
    )


def upgrade() -> None:
    op.create_table(
        "video_workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_video_workflows_owner_project",
        "video_workflows",
        ["owner_id", "project_id", "created_at"],
    )

    op.create_table(
        "asset_version_payloads",
        sa.Column("asset_version_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("mime", sa.String(40), nullable=False),
        sa.Column("payload_text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["asset_version_id"], ["asset_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("mime IN ('text/csv','text/plain')"),
        sa.CheckConstraint("length(payload_text) BETWEEN 1 AND 200000"),
        sa.CheckConstraint("length(sha256) = 64"),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 200000"),
    )
    op.create_index(
        "ix_asset_version_payloads_owner_project",
        "asset_version_payloads",
        ["owner_id", "project_id", "created_at"],
    )

    op.create_table(
        "scene_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["video_workflows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_scene_blocks_owner_project_workflow",
        "scene_blocks",
        ["owner_id", "project_id", "workflow_id", "created_at"],
    )

    op.create_table(
        "scene_block_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scene_block_id", sa.String(36), nullable=False),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("pipeline_mode", sa.String(20), nullable=False),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("asset_version_ids_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["scene_block_id"], ["scene_blocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_id"], ["video_workflows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["scene_block_versions.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("version >= 1", name="ck_scene_block_versions_version"),
        sa.CheckConstraint(
            "pipeline_mode IN ('auto', 'teaching', 'scientific')",
            name="ck_scene_block_versions_pipeline",
        ),
        sa.CheckConstraint(
            "target_duration_seconds BETWEEN 15 AND 120",
            name="ck_scene_block_versions_duration",
        ),
        sa.CheckConstraint(
            "json_valid(asset_version_ids_json)",
            name="ck_scene_block_versions_assets_json",
        ),
        sa.UniqueConstraint(
            "scene_block_id", "version", name="uq_scene_block_versions_number"
        ),
    )
    op.create_index(
        "ix_scene_block_versions_owner_project",
        "scene_block_versions",
        ["owner_id", "project_id", "scene_block_id", "version"],
    )

    op.create_table(
        "video_workflow_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(36), nullable=True),
        sa.Column("global_brief_json", sa.Text(), nullable=False),
        sa.Column("nodes_json", sa.Text(), nullable=False),
        sa.Column("edges_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["video_workflows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["video_workflow_versions.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("version >= 1", name="ck_video_workflow_versions_version"),
        sa.CheckConstraint("json_valid(global_brief_json)", name="ck_workflow_brief_json"),
        sa.CheckConstraint("json_valid(nodes_json)", name="ck_workflow_nodes_json"),
        sa.CheckConstraint("json_valid(edges_json)", name="ck_workflow_edges_json"),
        sa.UniqueConstraint("workflow_id", "version", name="uq_video_workflow_versions_number"),
    )
    op.create_index(
        "ix_video_workflow_versions_owner_project",
        "video_workflow_versions",
        ["owner_id", "project_id", "workflow_id", "version"],
    )

    op.create_table(
        "scene_block_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scene_block_version_id", sa.String(36), nullable=False),
        sa.Column("workflow_version_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(
            ["scene_block_version_id"], ["scene_block_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"], ["video_workflow_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("length(cache_key) = 64", name="ck_scene_block_runs_cache_key"),
        sa.CheckConstraint("profile IN ('preview','final')", name="ck_scene_block_runs_profile"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_scene_block_runs_idempotency"),
    )
    op.create_index(
        "ix_scene_block_runs_owner_version",
        "scene_block_runs",
        ["owner_id", "scene_block_version_id", "created_at"],
    )

    op.create_table(
        "workflow_composition_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_version_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"], ["video_workflow_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("profile IN ('preview','final')", name="ck_composition_runs_profile"),
        sa.CheckConstraint("length(cache_key) = 64", name="ck_composition_runs_cache_key"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_composition_runs_idempotency"
        ),
    )

    op.create_table(
        "scene_run_provenance",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scene_block_run_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("intent_ref", sa.String(36), nullable=True),
        sa.Column("animation_ir_ref", sa.String(36), nullable=True),
        sa.Column("intent_json", sa.Text(), nullable=True),
        sa.Column("animation_ir_json", sa.Text(), nullable=True),
        sa.Column("tool_runs_json", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(
            ["scene_block_run_id"], ["scene_block_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("intent_json IS NULL OR json_valid(intent_json)"),
        sa.CheckConstraint("animation_ir_json IS NULL OR json_valid(animation_ir_json)"),
        sa.CheckConstraint("json_valid(tool_runs_json)"),
        sa.CheckConstraint("json_valid(provenance_json)"),
        sa.UniqueConstraint("scene_block_run_id"),
        sa.UniqueConstraint("intent_ref"),
        sa.UniqueConstraint("animation_ir_ref"),
    )
    op.create_index(
        "ix_composition_runs_owner_workflow",
        "workflow_composition_runs",
        ["owner_id", "workflow_version_id", "created_at"],
    )

    op.create_table(
        "program_render_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scene_block_run_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("program_sha256", sa.String(64), nullable=False),
        sa.Column("quality_policy", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["scene_block_run_id"], ["scene_block_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.CheckConstraint("profile IN ('preview','final')"),
        sa.CheckConstraint("length(program_sha256) = 64"),
        sa.CheckConstraint("quality_policy IN ('teaching','scientific')"),
        sa.CheckConstraint("status IN ('compiling','rendering','composing','succeeded','failed')"),
        sa.CheckConstraint("segment_count BETWEEN 1 AND 32"),
        sa.UniqueConstraint("scene_block_run_id", "profile"),
    )
    op.create_table(
        "program_render_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("program_render_run_id", sa.String(36), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("scene_class", sa.String(100), nullable=False),
        sa.Column("target_duration_seconds", sa.Float(), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=True),
        sa.Column("input_artifact_id", sa.String(36), nullable=True),
        sa.Column("input_artifact_sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(["program_render_run_id"], ["program_render_runs.id"]),
        sa.ForeignKeyConstraint(["input_artifact_id"], ["artifacts.id"]),
        sa.CheckConstraint("segment_index BETWEEN 0 AND 31"),
        sa.CheckConstraint("length(source_code) BETWEEN 1 AND 200000"),
        sa.CheckConstraint("length(source_sha256) = 64"),
        sa.CheckConstraint("length(scene_class) BETWEEN 2 AND 100"),
        sa.CheckConstraint("target_duration_seconds > 0 AND target_duration_seconds <= 600"),
        sa.CheckConstraint("input_artifact_sha256 IS NULL OR length(input_artifact_sha256) = 64"),
        sa.CheckConstraint("status IN ('pending','queued','rendering','succeeded','failed')"),
        sa.UniqueConstraint("program_render_run_id", "segment_index"),
        sa.UniqueConstraint("render_job_id"),
    )

    op.create_table(
        "workflow_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("scene_block_run_id", sa.String(36), nullable=True),
        sa.Column("composition_run_id", sa.String(36), nullable=True),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("media_type", sa.String(50), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["scene_block_run_id"], ["scene_block_runs.id"]),
        sa.ForeignKeyConstraint(["composition_run_id"], ["workflow_composition_runs.id"]),
        sa.CheckConstraint("(scene_block_run_id IS NULL) != (composition_run_id IS NULL)"),
        sa.CheckConstraint("profile IN ('preview','final')"),
        sa.CheckConstraint("length(sha256) = 64"),
        sa.CheckConstraint("byte_size > 0"),
        sa.CheckConstraint("duration_seconds > 0 AND duration_seconds <= 600"),
        sa.CheckConstraint("media_type = 'video/mp4'"),
        sa.UniqueConstraint("scene_block_run_id", "profile"),
        sa.UniqueConstraint("composition_run_id", "profile"),
    )
    op.create_index(
        "ix_workflow_artifacts_owner_project",
        "workflow_artifacts",
        ["owner_id", "project_id", "created_at"],
    )

    op.create_table(
        "scene_block_run_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("pipeline_used", sa.String(20), nullable=True),
        sa.Column("intent_ref", sa.String(36), nullable=True),
        sa.Column("animation_ir_ref", sa.String(36), nullable=True),
        sa.Column("compiled_program_ref", sa.String(36), nullable=True),
        sa.Column("preview_artifact_id", sa.String(36), nullable=True),
        sa.Column("final_artifact_id", sa.String(36), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scene_block_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["preview_artifact_id"], ["workflow_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["final_artifact_id"], ["workflow_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("state_version >= 0", name="ck_scene_block_events_state"),
        sa.CheckConstraint(
            "status IN ('queued','planning','needs_confirmation','asset_required',"
            "'compiling','rendering','succeeded','failed')",
            name="ck_scene_block_events_status",
        ),
        sa.CheckConstraint(
            "pipeline_used IS NULL OR pipeline_used IN ('teaching','scientific')",
            name="ck_scene_block_events_pipeline",
        ),
        sa.UniqueConstraint("run_id", "state_version", name="uq_scene_block_events_state"),
    )
    op.create_index(
        "ix_scene_block_run_events_latest",
        "scene_block_run_events",
        ["run_id", "state_version"],
    )

    op.create_table(
        "workflow_composition_run_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=True),
        sa.Column("artifact_id", sa.String(36), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["workflow_composition_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["workflow_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("state_version >= 0", name="ck_composition_events_state"),
        sa.CheckConstraint(
            "status IN ('queued','composing','not_ready_to_compose','succeeded','failed')",
            name="ck_composition_events_status",
        ),
        sa.CheckConstraint(
            "manifest_json IS NULL OR json_valid(manifest_json)",
            name="ck_composition_events_manifest_json",
        ),
        sa.UniqueConstraint("run_id", "state_version", name="uq_composition_events_state"),
    )
    op.create_index(
        "ix_composition_run_events_latest",
        "workflow_composition_run_events",
        ["run_id", "state_version"],
    )

    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.String(35), nullable=False),
        sa.Column("lease_owner", sa.String(100), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.String(35), nullable=True),
        sa.Column("completed_at", sa.String(35), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.Column("updated_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "kind IN ('scene_program','composition')", name="ck_workflow_tasks_kind"
        ),
        sa.CheckConstraint(
            "status IN ('queued','leased','complete')", name="ck_workflow_tasks_status"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_workflow_tasks_attempts"),
        sa.CheckConstraint("json_valid(payload_json)", name="ck_workflow_tasks_payload"),
        sa.UniqueConstraint("kind", "run_id", name="uq_workflow_tasks_run"),
        sa.UniqueConstraint(
            "owner_id", "kind", "idempotency_key", name="uq_workflow_tasks_idempotency"
        ),
    )
    op.create_index(
        "ix_workflow_tasks_claim",
        "workflow_tasks",
        ["kind", "status", "available_at", "lease_expires_at", "created_at"],
    )

    for table in (
        "asset_version_payloads",
        "scene_block_versions",
        "video_workflow_versions",
        "scene_block_runs",
        "scene_block_run_events",
        "workflow_composition_runs",
        "workflow_composition_run_events",
        "scene_run_provenance",
    ):
        _protect_append_only(table)
    _enforce_monotonic_event("scene_block_run_events", "run_id")
    _enforce_monotonic_event("workflow_composition_run_events", "run_id")


def downgrade() -> None:
    scientific_jobs = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM render_jobs "
            "WHERE program_render_segment_id IS NOT NULL"
        )
    ).scalar_one()
    if scientific_jobs:
        raise RuntimeError(
            "cannot downgrade workflow tables while RenderJobs reference ProgramRenderSegments"
        )
    op.drop_index("ix_workflow_tasks_claim", table_name="workflow_tasks")
    op.drop_table("workflow_tasks")
    op.drop_index(
        "ix_composition_run_events_latest", table_name="workflow_composition_run_events"
    )
    op.drop_table("workflow_composition_run_events")
    op.drop_table("scene_run_provenance")
    op.drop_table("program_render_segments")
    op.drop_table("program_render_runs")
    op.drop_index("ix_scene_block_run_events_latest", table_name="scene_block_run_events")
    op.drop_table("scene_block_run_events")
    op.drop_index("ix_workflow_artifacts_owner_project", table_name="workflow_artifacts")
    op.drop_table("workflow_artifacts")
    op.drop_index("ix_composition_runs_owner_workflow", table_name="workflow_composition_runs")
    op.drop_table("workflow_composition_runs")
    op.drop_index("ix_scene_block_runs_owner_version", table_name="scene_block_runs")
    op.drop_table("scene_block_runs")
    op.drop_index(
        "ix_video_workflow_versions_owner_project", table_name="video_workflow_versions"
    )
    op.drop_table("video_workflow_versions")
    op.drop_index("ix_scene_block_versions_owner_project", table_name="scene_block_versions")
    op.drop_table("scene_block_versions")
    op.drop_index("ix_scene_blocks_owner_project_workflow", table_name="scene_blocks")
    op.drop_table("scene_blocks")
    op.drop_index("ix_video_workflows_owner_project", table_name="video_workflows")
    op.drop_table("video_workflows")
    op.drop_index(
        "ix_asset_version_payloads_owner_project", table_name="asset_version_payloads"
    )
    op.drop_table("asset_version_payloads")
