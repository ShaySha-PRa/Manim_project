from __future__ import annotations

import argparse
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from manim_workbench_api.quality.temporal import analyze_temporal_quality
from manim_workbench_contracts import RenderJobLease, RenderProfile
from manim_workbench_runner.phase5_runtime import Phase5SandboxAdapter
from manim_workbench_runner.quality.orchestration import analyze_published_video
from manim_workbench_runner.queue.types import JobControl, SandboxWorkItem
from manim_workbench_runner.sandbox import SandboxExecutor, SandboxLimits

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / "runtime" / "phase9-real-acceptance"
DEFAULT_RECORDS = ROOT / "benchmarks" / "phase9" / "real_terminal_records.json"
DEFAULT_REPORT = ROOT / "benchmarks" / "phase9" / "real_acceptance_report.json"
SEVERE_CODES = {
    "blank_frame",
    "cjk_glyph_missing",
    "duration_too_long",
    "duration_too_short",
    "key_formula_missing",
    "long_static_segment",
    "object_missing",
    "object_out_of_bounds",
    "terminal_wait_padding",
}

FORMULA_TOPICS = (
    ("一元一次方程", "2x + 3 = 9"),
    ("平方差公式", "a² − b² = (a−b)(a+b)"),
    ("完全平方公式", "(a+b)² = a² + 2ab + b²"),
    ("二次公式", "x = (−b ± √(b²−4ac)) ÷ 2a"),
    ("勾股定理", "a² + b² = c²"),
    ("等差数列", "Sₙ = n(a₁+aₙ) ÷ 2"),
    ("等比数列", "Sₙ = a₁(1−qⁿ) ÷ (1−q)"),
    ("导数定义", "f′(x) = lim Δy ÷ Δx"),
    ("乘法公式", "(ab)′ = a′b + ab′"),
    ("正弦平方", "sin²x + cos²x = 1"),
    ("对数性质", "log(ab) = log a + log b"),
    ("指数性质", "aᵐaⁿ = aᵐ⁺ⁿ"),
    ("圆的面积", "A = πr²"),
    ("圆锥体积", "V = πr²h ÷ 3"),
    ("二项式展开", "(a+b)³ = a³+3a²b+3ab²+b³"),
)

FUNCTION_TOPICS = (
    ("二次函数", "y = x²", "0.20*x*x-1"),
    ("开口向下抛物线", "y = −x²", "-0.20*x*x+1"),
    ("一次函数", "y = 0.6x+1", "0.6*x+1"),
    ("绝对值函数", "y = |x|", "abs(x)"),
    ("三次函数", "y = 0.08x³", "0.08*x*x*x"),
    ("平方根函数", "y = √(x+4)", "(x+4)**0.5"),
    ("倒数函数近似", "y ≈ 2 ÷ x", "0.08*x*x*x-0.7*x"),
    ("正弦函数近似", "y ≈ sin x", "0.8*x-0.1*x*x*x"),
    ("余弦函数近似", "y ≈ cos x", "1-0.4*x*x+0.02*x*x*x*x"),
    ("指数增长", "y = 1.3ˣ", "1.3**x"),
    ("指数衰减", "y = 0.8ˣ", "0.8**x"),
    ("平移抛物线", "y = (x−2)²", "0.20*(x-2)*(x-2)-1"),
    ("拉伸抛物线", "y = 2x²", "0.35*x*x-1"),
    ("线性比较", "y = x 与 y = 2x", "0.8*x"),
    ("四次函数", "y = 0.01x⁴", "0.01*x*x*x*x-1"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 30 real Phase 9 Preview/Final renders.")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--case-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.workers <= 4 or not 1 <= args.limit <= 30:
        raise SystemExit("workers must be 1..4 and limit must be 1..30")
    cases = _cases()
    if args.case_id:
        cases = [case for case in cases if case["case_id"] == args.case_id]
        if not cases:
            raise SystemExit("case-id was not found")
    else:
        cases = cases[: args.limit]
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    execution_failures: list[str] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_render_case, case, slot, args.runtime_root): case["case_id"]
            for slot, case in enumerate(cases)
        }
        for future in as_completed(futures):
            try:
                case_records = future.result()
            except Exception as error:
                execution_failures.append(f"{futures[future]}:{type(error).__name__}")
                print(
                    json.dumps(
                        {"case_id": futures[future], "error": type(error).__name__},
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
                continue
            records.extend(case_records)
            print(
                json.dumps(
                    {"case_id": futures[future], "completed_records": len(records)},
                    separators=(",", ":"),
                ),
                flush=True,
            )
    records.sort(key=lambda item: (str(item["case_id"]), str(item["profile"])))
    report = _evaluate(cases, records, time.monotonic() - started)
    report["failures"] = execution_failures + list(report["failures"])
    if report["failures"]:
        report["status"] = "failed"
    _safe_write(args.records, {"schema_version": "1.0", "records": records})
    _safe_write(args.report, report)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "passed" else 1


def _cases() -> list[dict[str, str]]:
    formulas = [
        {
            "case_id": f"F{index:02d}",
            "category": "formula_derivation",
            "source": _formula_source(case_id=f"F{index:02d}", title=title, formula=formula),
        }
        for index, (title, formula) in enumerate(FORMULA_TOPICS, 1)
    ]
    functions = [
        {
            "case_id": f"G{index:02d}",
            "category": "function_visualization",
            "source": _function_source(
                case_id=f"G{index:02d}", title=title, formula=formula, expression=expression
            ),
        }
        for index, (title, formula, expression) in enumerate(FUNCTION_TOPICS, 1)
    ]
    return formulas + functions


def _formula_source(*, case_id: str, title: str, formula: str) -> str:
    labels = (
        f"{case_id} · {title}",
        formula,
        "识别已知条件",
        "逐步保持等价",
        "检查关键变形",
        "得到并验证结论",
    )
    return _text_timeline(labels)


def _function_source(*, case_id: str, title: str, formula: str, expression: str) -> str:
    declarations = [
        "from manim import Axes, Create, Dot, FadeIn, Indicate, Scene, Text, VGroup, YELLOW",
        "",
        "class GeneratedScene(Scene):",
        "    def construct(self):",
        f"        title = Text({title!r}, font='Noto Sans CJK SC', "
        "font_size=36).to_edge([0, 1, 0])",
        f"        formula = Text({formula!r}, font='Noto Sans CJK SC', "
        "font_size=30).to_edge([0, -1, 0])",
        "        axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1], x_length=8, y_length=4)",
        "        def function(x):",
        f"            return {expression}",
        "        curve = axes.plot(function, x_range=[-3.5, 3.5], color=YELLOW)",
        f"        left_point = Dot(axes.c2p(-2, {expression.replace('x', '(-2)')}), color=YELLOW)",
        f"        right_point = Dot(axes.c2p(2, {expression.replace('x', '(2)')}), color=YELLOW)",
    ]
    objects = (
        ("title", "FadeIn"),
        ("axes", "Create"),
        ("curve", "Create"),
        ("formula", "FadeIn"),
        ("left_point", "FadeIn"),
        ("right_point", "FadeIn"),
    )
    declarations.extend(_timeline_lines(objects))
    return "\n".join(declarations) + "\n"


def _text_timeline(labels: tuple[str, ...]) -> str:
    names = ("title", "formula", "condition", "steps", "check", "summary")
    lines = [
        "from manim import DOWN, FadeIn, Indicate, Scene, Text, VGroup, YELLOW",
        "",
        "class GeneratedScene(Scene):",
        "    def construct(self):",
    ]
    lines.extend(
        f"        {name} = Text({label!r}, font='Noto Sans CJK SC', font_size=30)"
        for name, label in zip(names, labels, strict=True)
    )
    lines.append(f"        content = VGroup({', '.join(names)}).arrange(DOWN, buff=0.25)")
    lines.extend(_timeline_lines(tuple((name, "FadeIn") for name in names)))
    return "\n".join(lines) + "\n"


def _timeline_lines(objects: tuple[tuple[str, str], ...]) -> list[str]:
    lines: list[str] = []
    for name, entrance in objects:
        lines.append(f"        self.play({entrance}({name}), run_time=2.8)")
        lines.extend(
            f"        self.play(Indicate({name}, color=YELLOW), run_time=2.8)" for _ in range(4)
        )
        lines.append("        self.wait(1)")
    return lines


def _render_case(case: dict[str, str], slot: int, runtime_root: Path) -> list[dict[str, object]]:
    source = case["source"]
    temporal = analyze_temporal_quality(source, target_duration_seconds=90)
    if not math.isclose(temporal.estimated_duration_seconds or 0, 90, abs_tol=1e-6) or any(
        item.code.value in SEVERE_CODES for item in temporal.diagnostics
    ):
        raise RuntimeError(f"{case['case_id']}: static timeline gate failed")
    records = []
    for profile in (RenderProfile.PREVIEW, RenderProfile.FINAL):
        root = runtime_root / f"slot-{slot % 4}" / case["case_id"] / profile.value
        source_root = root / "sources"
        artifact_root = root / "artifacts"
        source_root.mkdir(parents=True, exist_ok=True)
        artifact_root.mkdir(parents=True, exist_ok=True)
        existing = _existing_record(
            artifact_root=artifact_root,
            case=case,
            profile=profile,
            temporal=temporal,
        )
        if existing is not None:
            records.append(existing)
            continue
        executor = SandboxExecutor(
            limits=SandboxLimits(
                cpuset_cpu=slot % 4,
                allowed_source_root=source_root,
                allowed_output_root=artifact_root,
            )
        )
        adapter = Phase5SandboxAdapter(runtime_root=root, executor=executor)
        lease = RenderJobLease(
            job_id=uuid4(),
            code_version_id=uuid4(),
            content_plan_version_id=uuid4(),
            target_duration_seconds=90,
            profile=profile,
            scene_class="GeneratedScene",
            source_code=source,
            source_sha256=sha256(source.encode()).hexdigest(),
            lease_token="a" * 64,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            attempt_number=1,
        )
        started = time.monotonic()
        result = adapter.execute(
            SandboxWorkItem(lease),
            control_probe=lambda: JobControl(active=True, cancellation_requested=False),
        )
        elapsed = time.monotonic() - started
        metadata_artifact = next(item for item in result.artifacts if item.kind.value == "metadata")
        metadata = json.loads((artifact_root / metadata_artifact.relative_path).read_text())
        records.append(
            _record(
                case=case,
                profile=profile,
                temporal=temporal,
                metadata=metadata,
                elapsed=elapsed,
            )
        )
    return records


def _existing_record(
    *,
    artifact_root: Path,
    case: dict[str, str],
    profile: RenderProfile,
    temporal,  # type: ignore[no-untyped-def]
) -> dict[str, object] | None:
    candidates = sorted(artifact_root.rglob("metadata.json"))
    if not candidates:
        return None
    metadata_path = candidates[-1]
    directory = metadata_path.parent
    if not (directory / "video.mp4").is_file():
        return None
    metadata = json.loads(metadata_path.read_text())
    quality = metadata.get("quality") if isinstance(metadata, dict) else None
    if not isinstance(quality, dict) or not isinstance(quality.get("video"), dict):
        analyze_published_video(
            artifact_directory=directory,
            target_duration_seconds=90,
            artifacts=(),
        )
        metadata = json.loads(metadata_path.read_text())
    return _record(
        case=case,
        profile=profile,
        temporal=temporal,
        metadata=metadata,
        elapsed=0,
    )


def _record(
    *,
    case: dict[str, str],
    profile: RenderProfile,
    temporal,  # type: ignore[no-untyped-def]
    metadata: dict[str, object],
    elapsed: float,
) -> dict[str, object]:
    quality = metadata["quality"]
    if not isinstance(quality, dict) or not isinstance(quality.get("video"), dict):
        raise RuntimeError("quality video metadata is unavailable")
    video = quality["video"]
    diagnostics = quality.get("diagnostics")
    if not isinstance(video, dict) or not isinstance(diagnostics, list):
        raise RuntimeError("quality evidence is invalid")
    return {
        "actual_duration_seconds": video["duration_seconds"],
        "analysis_and_render_seconds": round(elapsed, 3),
        "case_id": case["case_id"],
        "category": case["category"],
        "diagnostic_codes": [item["code"] for item in diagnostics],
        "diagnostic_signature": quality["signature"],
        "estimated_duration_seconds": temporal.estimated_duration_seconds,
        "frame_count": video["frame_count"],
        "frame_rate": video["fps"],
        "profile": profile.value,
        "target_duration_seconds": 90,
        "terminal_status": "passed" if not diagnostics else "failed",
    }


def _evaluate(
    cases: list[dict[str, str]], records: list[dict[str, object]], elapsed: float
) -> dict[str, object]:
    by_case = {case["case_id"]: {} for case in cases}
    for record in records:
        by_case[str(record["case_id"])][str(record["profile"])] = record
    failures: list[str] = []
    for case_id, pair in by_case.items():
        if set(pair) != {"preview", "final"}:
            failures.append(f"{case_id}:missing_profile")
            continue
        for record in pair.values():
            actual = float(record["actual_duration_seconds"])
            if not 81 <= actual <= 99 or record["terminal_status"] != "passed":
                failures.append(f"{case_id}:{record['profile']}:quality")
            if SEVERE_CODES & set(record["diagnostic_codes"]):
                failures.append(f"{case_id}:{record['profile']}:severe")
        preview = pair["preview"]
        final = pair["final"]
        delta = abs(
            float(preview["frame_count"]) / float(preview["frame_rate"])
            - float(final["frame_count"]) / float(final["frame_rate"])
        )
        if delta > 1 / max(float(preview["frame_rate"]), float(final["frame_rate"])):
            failures.append(f"{case_id}:timeline_mismatch")
    return {
        "schema_version": "1.0",
        "status": "passed" if not failures else "failed",
        "golden_cases": len(cases),
        "terminal_renders": len(records),
        "preview_final_pairs": len(cases),
        "elapsed_seconds": round(elapsed, 3),
        "failures": failures,
    }


def _safe_write(path: Path, payload: object) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT):
        raise RuntimeError("acceptance output must remain inside the project")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
