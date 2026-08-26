from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import manim_workbench_api.agent.orchestrator as orchestrator
import manim_workbench_api.agent.service as agent_service_module
from manim_workbench_api.agent.orchestrator import AgentExecution, run_agent_with_program
from manim_workbench_api.agent.service import AgentService
from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment
from manim_workbench_contracts import AgentRunRequest, CriticReport
from manim_workbench_contracts.intent import AgentRunOutcome


def test_orchestrator_returns_full_program_and_critic_receives_every_segment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_sources: list[str] = []

    def compile_two_segments(ir, tool_runs):  # type: ignore[no-untyped-def]
        del ir, tool_runs
        return CompiledProgram(
            segments=(
                CompiledSegment(
                    source="from manim import Scene\n# segment-one",
                    scene_base="Scene",
                    visual_kinds=(),
                    duration_seconds=10,
                ),
                CompiledSegment(
                    source="from manim import ThreeDScene\n# segment-two",
                    scene_base="ThreeDScene",
                    visual_kinds=(),
                    duration_seconds=20,
                ),
            )
        )

    def evaluate_all(ir, tool_runs, source, *, provider=None):  # type: ignore[no-untyped-def]
        del ir, tool_runs, provider
        captured_sources.append(source)
        return CriticReport(expression_score=5.0)

    monkeypatch.setattr(orchestrator, "compile_animation_ir", compile_two_segments)
    monkeypatch.setattr(orchestrator, "evaluate_expression", evaluate_all)

    execution = run_agent_with_program(
        "展示傅里叶级数逐渐逼近方波",
        output_root=tmp_path,
    )

    assert execution.response.outcome is AgentRunOutcome.READY
    assert execution.compiled_program is not None
    assert len(execution.compiled_program.segments) == 2
    assert captured_sources == [
        "from manim import Scene\n# segment-one\n\n"
        "from manim import ThreeDScene\n# segment-two"
    ]


class _Projects:
    _engine = None

    def get_project(self, project_id, owner_id):  # type: ignore[no-untyped-def]
        return SimpleNamespace(id=project_id, owner_id=owner_id)

    def append_prompt_version(self, project_id, owner_id, prompt):  # type: ignore[no-untyped-def]
        del project_id, owner_id, prompt
        return SimpleNamespace(id=uuid4())


class _ContentPlans:
    def save_ready(self, request, draft, **kwargs):  # type: ignore[no-untyped-def]
        del request, draft, kwargs
        return SimpleNamespace(id=uuid4())


class _CodeVersions:
    def __init__(self) -> None:
        self.saved = 0

    def save_success(self, request, **kwargs):  # type: ignore[no-untyped-def]
        del request, kwargs
        self.saved += 1
        raise AssertionError("multi-segment program must not persist one canonical segment")


def test_agent_service_does_not_persist_only_the_first_segment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    original = run_agent_with_program(
        "展示傅里叶级数逐渐逼近方波",
        output_root=tmp_path,
    )
    assert original.compiled_program is not None
    first = original.compiled_program.segments[0]
    multi = replace(original, compiled_program=CompiledProgram(segments=(first, first)))
    monkeypatch.setattr(
        agent_service_module,
        "run_agent_with_program",
        lambda *args, **kwargs: multi,
    )
    code_versions = _CodeVersions()
    request = AgentRunRequest(
        project_id=uuid4(),
        owner_id=uuid4(),
        prompt="展示傅里叶级数逐渐逼近方波",
        target_duration_seconds=60,
    )

    result = AgentService(_Projects(), _ContentPlans(), code_versions).run(request)

    assert result.outcome is AgentRunOutcome.FAILED
    assert result.error_code == "program_render_required"
    assert code_versions.saved == 0


def test_agent_service_checks_security_for_later_segments(
    monkeypatch,
    tmp_path: Path,
) -> None:
    original = run_agent_with_program(
        "展示傅里叶级数逐渐逼近方波",
        output_root=tmp_path,
    )
    assert original.compiled_program is not None
    first = original.compiled_program.segments[0]
    unsafe = replace(first, source="import os\nos.system('id')")
    execution = AgentExecution(
        response=original.response,
        compiled_program=CompiledProgram(segments=(first, unsafe)),
    )
    monkeypatch.setattr(
        agent_service_module,
        "run_agent_with_program",
        lambda *args, **kwargs: execution,
    )
    code_versions = _CodeVersions()
    request = AgentRunRequest(
        project_id=uuid4(),
        owner_id=uuid4(),
        prompt="展示傅里叶级数逐渐逼近方波",
        target_duration_seconds=60,
    )

    result = AgentService(_Projects(), _ContentPlans(), code_versions).run(request)

    assert result.outcome is AgentRunOutcome.FAILED
    assert result.error_code == "security_policy_violation"
    assert code_versions.saved == 0
