from pathlib import Path

import numpy as np
import pytest
from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.agent.scientific_planner import plan_tools
from manim_workbench_api.agent.service import AgentService
from manim_workbench_api.assets.scientific import (
    AssetIngestError,
    ingest_csv_text,
    inspect_numpy_file,
)
from manim_workbench_api.tools.registry import invoke
from manim_workbench_contracts import (
    AssetDType,
    AssetMime,
    AssetSource,
    IntentSpec,
    ToolNeed,
    ToolOp,
)
from manim_workbench_contracts.intent import AgentRunOutcome, IntentDomain


def _csv() -> str:
    return "time,temperature,pressure\n0,22.0,1.0\n5,22.0,1.0\n10,30.0,1.4\n"


def test_ingest_csv_records_numeric_schema_and_hash() -> None:
    text = _csv()
    asset = ingest_csv_text(text)
    assert asset.source == AssetSource.UPLOAD
    assert asset.mime == AssetMime.CSV
    assert asset.derived_from is None
    assert asset.columns == ("time", "temperature", "pressure")
    dtypes = {field.name: field.dtype for field in asset.fields}
    assert dtypes["time"] in {AssetDType.INT64, AssetDType.FLOAT64}
    assert dtypes["temperature"] == AssetDType.FLOAT64
    assert asset.fields[0].shape == (3,)
    assert asset.size_bytes == len(text.encode("utf-8"))


def test_ingest_csv_rejects_string_columns_and_limits() -> None:
    with pytest.raises(AssetIngestError, match="not numeric"):
        ingest_csv_text("time,notes\n1,hot\n")
    with pytest.raises(AssetIngestError, match="column limit"):
        header = ",".join(f"c{index}" for index in range(25))
        ingest_csv_text(header + "\n" + ",".join("1" for _ in range(25)))
    with pytest.raises(AssetIngestError, match="row limit"):
        rows = ["time,temperature,pressure"]
        rows.extend(f"{index},1.0,1.0" for index in range(5_001))
        ingest_csv_text("\n".join(rows))
    with pytest.raises(AssetIngestError, match="invalid column name"):
        ingest_csv_text("time (s),temperature,pressure\n1,2,3\n")


def test_inspect_npz_skips_assertion_json_and_forbids_pickle(tmp_path: Path) -> None:
    run = invoke("wave2d_superposition", {"nx": 8, "ny": 8, "nt": 4}, output_root=tmp_path)
    assert run.asset_version is not None
    assert run.input_asset_version is None
    assert run.asset_version.source == AssetSource.TOOL_OUTPUT
    assert run.asset_version.mime == AssetMime.NPZ
    assert run.asset_version.sha256 == run.output_sha256
    assert run.asset_version.derived_from is None
    assert "assertion_json" not in run.asset_version.columns
    assert "rgb" in run.asset_version.columns
    rgb = next(field for field in run.asset_version.fields if field.name == "rgb")
    assert rgb.dtype == AssetDType.UINT8

    evil = tmp_path / "evil.npz"
    np.savez(evil, payload=np.array([{"a": 1}], dtype=object))
    with pytest.raises(AssetIngestError, match="pickle|object"):
        inspect_numpy_file(evil, source=AssetSource.TOOL_OUTPUT)


def test_inspect_npy_allow_pickle_false(tmp_path: Path) -> None:
    path = tmp_path / "values.npy"
    np.save(path, np.arange(4, dtype=np.float32))
    asset = inspect_numpy_file(path, source=AssetSource.UPLOAD)
    assert asset.mime == AssetMime.NPY
    assert asset.columns == ("array",)
    assert asset.fields[0].dtype == AssetDType.FLOAT32
    assert asset.fields[0].shape == (4,)


def test_csv_tool_run_links_output_to_upload_hash(tmp_path: Path) -> None:
    text = _csv()
    run = invoke("csv_anomaly", {}, input_text=text, output_root=tmp_path)
    assert run.input_asset_version is not None
    assert run.asset_version is not None
    assert run.input_asset_version.source == AssetSource.UPLOAD
    assert run.input_asset_version.mime == AssetMime.CSV
    assert run.asset_version.derived_from == run.input_asset_version.sha256
    assert run.asset_version.derived_from == run.input_sha256
    assert run.asset_version.sha256 == run.output_sha256


def test_csv_tool_accepts_timestamp_without_rewriting_asset_provenance(tmp_path: Path) -> None:
    text = "timestamp,temperature,pressure\n0,21.0,101.2\n1,21.1,101.1\n2,28.9,98.4\n"
    run = invoke("csv_anomaly", {}, input_text=text, output_root=tmp_path)
    assert run.input_asset_version is not None
    assert run.input_asset_version.columns == ("timestamp", "temperature", "pressure")
    assert run.assertions["data_fidelity"] is True
    assert run.assertions["anomaly_center"] == 2.0
    assert run.assertions["anomaly_count"] == 1
    with np.load(run.artifact_path, allow_pickle=False) as payload:
        assert payload["t"].tolist() == [0.0, 1.0, 2.0]
        assert payload["temperature"].tolist() == pytest.approx([21.0, 21.1, 28.9])


def test_agent_rejects_csv_without_numeric_schema(tmp_path: Path) -> None:
    result = run_agent(
        "把这段 CSV 的温度异常高亮出来",
        csv_text="time,temperature,pressure,notes\n1,2,3,hot\n",
        output_root=tmp_path,
    )
    assert result.outcome == AgentRunOutcome.FAILED
    assert result.error_code == "asset_invalid"
    assert result.tool_runs == ()


def test_agent_service_uses_configured_compute_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MANIM_WORKBENCH_COMPUTE_ROOT", str(tmp_path))
    service = AgentService(None, None, None)  # type: ignore[arg-type]
    assert service._compute_root == tmp_path


def test_csv_planner_does_not_inject_benchmark_specific_center() -> None:
    intent = IntentSpec(
        schema_version="1.0",
        domain=IntentDomain.DATA_ANALYSIS,
        goal="Highlight anomalies in the uploaded data",
        assumptions=(),
        dimension="2d",
        tools_needed=(ToolNeed(op=ToolOp.CSV_ANOMALY, params={}),),
        asset_required=False,
        needs_confirmation=False,
    )

    planned = plan_tools(intent)

    assert planned[0].params == {}


def test_csv_explicit_center_uses_dataset_scale_without_inventing_interval(tmp_path: Path) -> None:
    run = invoke("csv_anomaly", {"center": 2.0}, input_text=_csv(), output_root=tmp_path)

    assert run.assertions["anomaly_center"] == 2.0
    assert run.assertions["anomaly_count"] == 1
