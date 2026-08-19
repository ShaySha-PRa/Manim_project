"""P2 benchmark gates: science ≥95%, unexpected FAILED <1%, both backends compile."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from manim_workbench_contracts.intent import AgentRunOutcome

from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.agent.p0_acceptance import default_csv_text, repo_root
from manim_workbench_api.agent.paper_catalog import lotka_csv_text, lotka_paper_text
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.compiler.manim import compile_animation_ir

SCIENCE_MIN = 0.95
FAIL_MAX = 0.01
BENCH_MIN = 100
BENCH_MAX = 300
Expect = Literal["ready", "needs_confirmation", "asset_required"]


def default_p2_benchmark_path() -> Path:
    return repo_root() / "eval" / "agent_p2_benchmark.jsonl"


@dataclass(frozen=True, slots=True)
class P2BenchCase:
    id: str
    prompt: str
    expect: Expect
    science_keys: tuple[str, ...] = ()
    asset: str | None = None
    family: str = ""


@dataclass(frozen=True, slots=True)
class P2CaseResult:
    id: str
    expect: Expect
    outcome: str
    manim_ok: bool
    web_ok: bool
    science_ok: bool
    expected_ok: bool
    failed: bool


@dataclass(frozen=True, slots=True)
class P2AcceptanceReport:
    n: int
    ready: int
    science_rate: float
    fail_rate: float
    expected_rate: float
    cross_backend_rate: float
    science_min: float = SCIENCE_MIN
    fail_max: float = FAIL_MAX
    cases: tuple[P2CaseResult, ...] = field(default_factory=tuple)

    @property
    def meets_p2_gates(self) -> bool:
        return (
            BENCH_MIN <= self.n <= BENCH_MAX
            and self.science_rate >= self.science_min
            and self.fail_rate < self.fail_max
            and self.expected_rate >= 1.0 - self.fail_max
            and self.cross_backend_rate >= 1.0
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["meets_p2_gates"] = self.meets_p2_gates
        payload["lab_trial"] = True
        payload["external_user_study"] = False
        return payload


def load_p2_benchmark(path: Path | None = None) -> tuple[P2BenchCase, ...]:
    bench_path = path or default_p2_benchmark_path()
    cases: list[P2BenchCase] = []
    for line_no, raw in enumerate(bench_path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        data = json.loads(text)
        expect = data.get("expect")
        if expect not in {"ready", "needs_confirmation", "asset_required"}:
            raise ValueError(f"{bench_path}:{line_no} bad expect")
        keys = tuple(str(item) for item in (data.get("science_keys") or []))
        if expect == "ready" and not keys:
            raise ValueError(f"{bench_path}:{line_no} ready cases need science_keys")
        cases.append(
            P2BenchCase(
                id=str(data["id"]),
                prompt=str(data["prompt"]),
                expect=expect,
                science_keys=keys,
                asset=str(data["asset"]) if data.get("asset") else None,
                family=str(data.get("family") or ""),
            )
        )
    if not (BENCH_MIN <= len(cases) <= BENCH_MAX):
        raise ValueError(f"{bench_path} must contain {BENCH_MIN}-{BENCH_MAX} cases")
    return tuple(cases)


def evaluate_p2_benchmark(
    *,
    work_root: Path,
    gold_path: Path | None = None,
) -> P2AcceptanceReport:
    cases = load_p2_benchmark(gold_path)
    compute_root = work_root / "compute"
    compile_root = work_root / "compile-cache"
    results = [_evaluate_p2_case(case, compute_root, compile_root) for case in cases]
    ready = [item for item in results if item.expect == "ready"]
    return P2AcceptanceReport(
        n=len(results),
        ready=len(ready),
        science_rate=sum(1 for item in ready if item.science_ok) / max(len(ready), 1),
        fail_rate=sum(1 for item in results if item.failed) / len(results),
        expected_rate=sum(1 for item in results if item.expected_ok) / len(results),
        cross_backend_rate=(
            sum(1 for item in ready if item.manim_ok and item.web_ok) / max(len(ready), 1)
        ),
        cases=tuple(results),
    )


def _evaluate_p2_case(
    case: P2BenchCase,
    compute_root: Path,
    compile_root: Path,
) -> P2CaseResult:
    csv_text = None
    paper_text = None
    if case.asset == "csv":
        csv_text = default_csv_text()
    elif case.asset == "paper_csv":
        csv_text = lotka_csv_text()
        paper_text = lotka_paper_text()
    elif case.asset == "paper_unknown":
        paper_text = "An unspecified novel PDE appears in the appendix."
        csv_text = lotka_csv_text()
    result = run_agent(
        case.prompt,
        csv_text=csv_text,
        paper_text=paper_text,
        output_root=compute_root,
    )
    manim_ok = False
    web_ok = False
    science_ok = False
    if result.outcome is AgentRunOutcome.READY and result.animation_ir is not None:
        manim = compile_animation_ir(
            result.animation_ir,
            result.tool_runs,
            backend="manim",
            cache_root=compile_root,
        )
        web = compile_animation_ir(
            result.animation_ir,
            result.tool_runs,
            backend="web",
            cache_root=compile_root,
        )
        manim_source = manim.segments[0].source
        web_source = web.segments[0].source
        manim_ok = (
            validate_source_security(manim_source).allowed
            and "lambda" not in manim_source
            and "class GeneratedScene" in manim_source
        )
        web_ok = _web_source_ok(web_source)
        science_ok = all(
            any(bool(run.assertions.get(key)) for run in result.tool_runs)
            for key in case.science_keys
        )
    expected_ok = result.outcome.value == case.expect
    if case.expect == "ready":
        expected_ok = expected_ok and manim_ok and web_ok and science_ok
    return P2CaseResult(
        id=case.id,
        expect=case.expect,
        outcome=result.outcome.value,
        manim_ok=manim_ok,
        web_ok=web_ok,
        science_ok=science_ok,
        expected_ok=expected_ok,
        failed=result.outcome is AgentRunOutcome.FAILED,
    )


def _web_source_ok(source: str) -> bool:
    if "lambda" in source or "from manim" in source.lower():
        return False
    try:
        payload = json.loads(source)
    except json.JSONDecodeError:
        return False
    return payload.get("backend") == "web" and "scene_base" in payload
