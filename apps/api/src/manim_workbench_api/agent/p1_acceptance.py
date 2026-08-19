"""P1 gold-set gates: expression ≥4.2/5, mean IR repairs ≤1, full asset provenance."""

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

EXPRESSION_MIN = 4.2
REPAIR_MEAN_MAX = 1.0
GOLD_MIN = 50
GOLD_MAX = 100
Expect = Literal["ready", "needs_confirmation", "asset_required"]


def default_p1_gold_path() -> Path:
    return repo_root() / "eval" / "agent_p1_gold.jsonl"


@dataclass(frozen=True, slots=True)
class P1GoldCase:
    id: str
    prompt: str
    expect: Expect
    science_keys: tuple[str, ...] = ()
    asset: str | None = None
    family: str = ""


@dataclass(frozen=True, slots=True)
class P1CaseResult:
    id: str
    expect: Expect
    outcome: str
    compile_ok: bool
    science_ok: bool
    expression: float | None
    repair_count: int
    provenance_ok: bool
    expected_ok: bool


@dataclass(frozen=True, slots=True)
class P1AcceptanceReport:
    n: int
    ready: int
    expression_mean: float
    repair_mean: float
    provenance_rate: float
    expected_rate: float
    science_rate: float
    expression_min: float = EXPRESSION_MIN
    repair_mean_max: float = REPAIR_MEAN_MAX
    cases: tuple[P1CaseResult, ...] = field(default_factory=tuple)

    @property
    def meets_p1_gates(self) -> bool:
        return (
            GOLD_MIN <= self.n <= GOLD_MAX
            and self.expression_mean >= self.expression_min
            and self.repair_mean <= self.repair_mean_max
            and self.provenance_rate >= 1.0
            and self.expected_rate >= 0.97
            and self.science_rate >= 0.90
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["meets_p1_gates"] = self.meets_p1_gates
        return payload


def load_p1_gold(path: Path | None = None) -> tuple[P1GoldCase, ...]:
    gold_path = path or default_p1_gold_path()
    cases: list[P1GoldCase] = []
    for line_no, raw in enumerate(gold_path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        data = json.loads(text)
        expect = data.get("expect")
        if expect not in {"ready", "needs_confirmation", "asset_required"}:
            raise ValueError(f"{gold_path}:{line_no} bad expect")
        keys = tuple(str(item) for item in (data.get("science_keys") or []))
        if expect == "ready" and not keys:
            raise ValueError(f"{gold_path}:{line_no} ready cases need science_keys")
        cases.append(
            P1GoldCase(
                id=str(data["id"]),
                prompt=str(data["prompt"]),
                expect=expect,
                science_keys=keys,
                asset=str(data["asset"]) if data.get("asset") else None,
                family=str(data.get("family") or ""),
            )
        )
    if not (GOLD_MIN <= len(cases) <= GOLD_MAX):
        raise ValueError(f"{gold_path} must contain {GOLD_MIN}-{GOLD_MAX} cases")
    return tuple(cases)


def evaluate_p1_gold(*, work_root: Path, gold_path: Path | None = None) -> P1AcceptanceReport:
    cases = load_p1_gold(gold_path)
    results = [_evaluate_p1_case(case, work_root / case.id) for case in cases]
    ready = [item for item in results if item.expect == "ready"]
    expression_values = [item.expression or 0.0 for item in ready]
    return P1AcceptanceReport(
        n=len(results),
        ready=len(ready),
        expression_mean=sum(expression_values) / max(len(expression_values), 1),
        repair_mean=sum(item.repair_count for item in ready) / max(len(ready), 1),
        provenance_rate=(
            sum(1 for item in ready if item.provenance_ok) / max(len(ready), 1)
        ),
        expected_rate=sum(1 for item in results if item.expected_ok) / len(results),
        science_rate=sum(1 for item in ready if item.science_ok) / max(len(ready), 1),
        cases=tuple(results),
    )


def _evaluate_p1_case(case: P1GoldCase, work_root: Path) -> P1CaseResult:
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
        output_root=work_root,
    )
    compile_ok = False
    science_ok = False
    provenance_ok = False
    expression = None
    if result.outcome is AgentRunOutcome.READY and result.animation_ir is not None:
        compiled = compile_animation_ir(result.animation_ir, result.tool_runs)
        source = compiled.segments[0].source
        compile_ok = validate_source_security(source).allowed and "lambda" not in source
        science_ok = all(
            any(bool(run.assertions.get(key)) for run in result.tool_runs)
            for key in case.science_keys
        )
        provenance_ok = all(
            run.asset_version is not None and run.asset_version.sha256 == run.output_sha256
            for run in result.tool_runs
        ) and bool(result.tool_runs)
        if result.critic_report is not None:
            expression = result.critic_report.expression_score
    expected_ok = result.outcome.value == case.expect
    if case.expect == "ready":
        expected_ok = expected_ok and compile_ok and science_ok and provenance_ok
    return P1CaseResult(
        id=case.id,
        expect=case.expect,
        outcome=result.outcome.value,
        compile_ok=compile_ok,
        science_ok=science_ok,
        expression=expression,
        repair_count=result.repair_count,
        provenance_ok=provenance_ok,
        expected_ok=expected_ok,
    )
