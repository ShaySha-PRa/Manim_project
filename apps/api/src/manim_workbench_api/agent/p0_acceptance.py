"""P0 gold-set rates from docs/research/animation-agent-v2.md.

First render ≥85%, final success ≥97%, science ≥90%. Science uses ToolRun
assertions, not a VLM. The paper+CSV row counts as confirmation success.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from manim_workbench_contracts import RenderProfile, ToolRun
from manim_workbench_contracts.intent import AgentRunOutcome

from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.compiler.manim import compile_animation_ir

FIRST_RENDER_MIN = 0.85
FINAL_SUCCESS_MIN = 0.97
SCIENCE_MIN = 0.90
Expect = Literal["ready", "needs_confirmation"]


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "eval" / "agent_p0_gold.jsonl"
        if candidate.is_file():
            return parent
    raise FileNotFoundError("eval/agent_p0_gold.jsonl")


def default_gold_path() -> Path:
    return repo_root() / "eval" / "agent_p0_gold.jsonl"


def default_csv_text() -> str:
    rows = ["time,temperature,pressure"]
    for second in range(0, 401, 5):
        bump = 8.0 if 330 <= second <= 370 else 0.0
        rows.append(f"{second},{22.0 + bump},{1.0 + bump / 20.0}")
    return "\n".join(rows)


@dataclass(frozen=True, slots=True)
class GoldCase:
    id: str
    prompt: str
    expect: Expect
    science_keys: tuple[str, ...] = ()
    asset: str | None = None
    source: str = ""


@dataclass(frozen=True, slots=True)
class CaseResult:
    id: str
    expect: Expect
    outcome: str
    compile_ok: bool
    science_ok: bool
    ir_deterministic: bool
    security_ok: bool
    confirmation_ok: bool
    rendered: bool | None
    message: str = ""


@dataclass(frozen=True, slots=True)
class P0AcceptanceReport:
    n: int
    renderable: int
    compile_ready: int
    science_pass: int
    ir_deterministic: int
    confirmation_pass: int
    rendered: int | None
    first_render_rate: float | None
    science_rate: float
    ir_deterministic_rate: float
    final_success_rate: float
    first_render_min: float = FIRST_RENDER_MIN
    final_success_min: float = FINAL_SUCCESS_MIN
    science_min: float = SCIENCE_MIN
    cases: tuple[CaseResult, ...] = field(default_factory=tuple)
    render_attempted: bool = False

    @property
    def meets_compile_gates(self) -> bool:
        return (
            self.science_rate >= self.science_min
            and self.ir_deterministic_rate >= self.science_min
            and self.compile_ready == self.renderable
            and self.confirmation_pass == self.n - self.renderable
        )

    @property
    def meets_p0_gates(self) -> bool:
        if not self.meets_compile_gates:
            return False
        if self.first_render_rate is None:
            return False
        return (
            self.first_render_rate >= self.first_render_min
            and self.final_success_rate >= self.final_success_min
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["meets_compile_gates"] = self.meets_compile_gates
        payload["meets_p0_gates"] = self.meets_p0_gates
        return payload


def load_gold(path: Path | None = None) -> tuple[GoldCase, ...]:
    gold_path = path or default_gold_path()
    cases: list[GoldCase] = []
    for line_no, raw in enumerate(gold_path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        data = json.loads(text)
        case_id = data.get("id")
        prompt = data.get("prompt")
        expect = data.get("expect")
        if not isinstance(case_id, str) or not isinstance(prompt, str):
            raise ValueError(f"{gold_path}:{line_no} needs id and prompt")
        if expect not in {"ready", "needs_confirmation"}:
            raise ValueError(f"{gold_path}:{line_no} expect must be ready or needs_confirmation")
        keys = data.get("science_keys") or []
        if expect == "ready" and not keys:
            raise ValueError(f"{gold_path}:{line_no} ready cases need science_keys")
        if expect == "needs_confirmation" and keys:
            raise ValueError(f"{gold_path}:{line_no} confirmation cases cannot score science")
        asset = data.get("asset")
        cases.append(
            GoldCase(
                id=case_id,
                prompt=prompt,
                expect=expect,
                science_keys=tuple(str(item) for item in keys),
                asset=str(asset) if asset else None,
                source=str(data.get("source") or ""),
            )
        )
    if not cases:
        raise ValueError(f"{gold_path} is empty")
    return tuple(cases)


def docker_image_ready() -> bool:
    from manim_workbench_runner.rendering.models import MANIM_IMAGE

    probe = subprocess.run(
        ["docker", "image", "inspect", MANIM_IMAGE],
        check=False,
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def evaluate_gold(
    *,
    gold_path: Path | None = None,
    work_root: Path,
    render: bool = False,
    csv_text: str | None = None,
) -> P0AcceptanceReport:
    cases = load_gold(gold_path)
    fixture = default_csv_text() if csv_text is None else csv_text
    results: list[CaseResult] = []
    for case in cases:
        results.append(
            _evaluate_case(case, work_root=work_root / case.id, csv_text=fixture, render=render)
        )
    return summarize(tuple(results), render_attempted=render)


def summarize(results: tuple[CaseResult, ...], *, render_attempted: bool) -> P0AcceptanceReport:
    renderable = tuple(item for item in results if item.expect == "ready")
    confirmation = tuple(item for item in results if item.expect == "needs_confirmation")
    compile_ready = sum(1 for item in renderable if item.compile_ok)
    science_pass = sum(1 for item in renderable if item.science_ok)
    ir_ok = sum(1 for item in renderable if item.ir_deterministic)
    confirmation_pass = sum(1 for item in confirmation if item.confirmation_ok)
    n_renderable = len(renderable)
    science_rate = science_pass / n_renderable if n_renderable else 0.0
    ir_rate = ir_ok / n_renderable if n_renderable else 0.0
    if render_attempted:
        rendered = sum(1 for item in renderable if item.rendered is True)
        first_render_rate = rendered / n_renderable if n_renderable else 0.0
        final_pass = rendered + confirmation_pass
    else:
        rendered = None
        first_render_rate = None
        final_pass = compile_ready + confirmation_pass
    return P0AcceptanceReport(
        n=len(results),
        renderable=n_renderable,
        compile_ready=compile_ready,
        science_pass=science_pass,
        ir_deterministic=ir_ok,
        confirmation_pass=confirmation_pass,
        rendered=rendered,
        first_render_rate=first_render_rate,
        science_rate=science_rate,
        ir_deterministic_rate=ir_rate,
        final_success_rate=final_pass / len(results) if results else 0.0,
        cases=results,
        render_attempted=render_attempted,
    )


def _evaluate_case(
    case: GoldCase,
    *,
    work_root: Path,
    csv_text: str,
    render: bool,
) -> CaseResult:
    work_root.mkdir(parents=True, exist_ok=True)
    asset = csv_text if case.asset == "csv" else None
    result = run_agent(case.prompt, csv_text=asset, output_root=work_root / "compute")
    if case.expect == "needs_confirmation":
        ok = result.outcome is AgentRunOutcome.NEEDS_CONFIRMATION
        return CaseResult(
            id=case.id,
            expect=case.expect,
            outcome=result.outcome.value,
            compile_ok=False,
            science_ok=False,
            ir_deterministic=False,
            security_ok=False,
            confirmation_ok=ok,
            rendered=None,
            message=result.message if not ok else "confirmed",
        )
    compile_ok = result.outcome is AgentRunOutcome.READY and result.animation_ir is not None
    science_ok = False
    ir_deterministic = False
    security_ok = False
    rendered: bool | None = None
    message = result.message or result.outcome.value
    if compile_ok:
        assertions = result.tool_runs[0].assertions if result.tool_runs else {}
        science_ok = all(assertions.get(key) is True for key in case.science_keys)
        first = compile_animation_ir(result.animation_ir, result.tool_runs).segments[0].source
        second = compile_animation_ir(result.animation_ir, result.tool_runs).segments[0].source
        ir_deterministic = first == second and "lambda" not in first and "np.exp" not in first
        security_ok = validate_source_security(first).allowed
        compile_ok = compile_ok and ir_deterministic and security_ok
        if render:
            rendered = _render_preview(first, result.tool_runs[0], work_root)
            message = "rendered" if rendered else "render_failed"
        else:
            message = "compile_ready"
    return CaseResult(
        id=case.id,
        expect=case.expect,
        outcome=result.outcome.value,
        compile_ok=compile_ok,
        science_ok=science_ok,
        ir_deterministic=ir_deterministic,
        security_ok=security_ok,
        confirmation_ok=False,
        rendered=rendered,
        message=message,
    )


def _render_preview(source: str, tool_run: ToolRun, work_root: Path) -> bool:
    from manim_workbench_runner.sandbox.executor import SandboxExecutionSuccess, SandboxExecutor
    from manim_workbench_runner.sandbox.policy import (
        SandboxInvocation,
        SandboxLimits,
        memory_tier_for_source,
    )

    source_path = work_root / "scene.py"
    output_dir = work_root / "output"
    assets_dir = work_root / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    source_path.write_text(source, encoding="utf-8")
    shutil.copyfile(
        Path(tool_run.artifact_path),
        assets_dir / f"{tool_run.output_sha256}.npz",
    )
    executor = SandboxExecutor(
        limits=SandboxLimits(allowed_source_root=work_root, allowed_output_root=work_root)
    )
    rendered = executor.execute(
        SandboxInvocation(
            job_id=uuid4(),
            source_path=source_path,
            output_path=output_dir,
            scene_class="GeneratedScene",
            profile=RenderProfile.PREVIEW,
            memory_tier=memory_tier_for_source(source),
            assets_path=assets_dir,
        )
    )
    return isinstance(rendered, SandboxExecutionSuccess) and (output_dir / "video.mp4").exists()
