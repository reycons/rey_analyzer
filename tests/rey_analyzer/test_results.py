"""Tests for result artifact writing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rey_analyzer.results import _raw_output_stem, write_result


def _request(run_id: str, file_path: Path) -> SimpleNamespace:
    """Minimal AnalysisRequest-shaped object for write_result."""
    return SimpleNamespace(
        run_id=run_id, request_id="req-1", source_name="src",
        analysis_name="an", file_path=file_path, input_hash="ih",
        contract_path=Path("contract.md"), contract_hash="ch",
        schema_hash="sh", idempotency_mode="strict",
    )


def test_write_result_logs_result_json_as_run_artifact(tmp_path: Path) -> None:
    """The analysis result.json is recorded as a files/artifacts run-log record."""
    source_cfg = SimpleNamespace(paths=SimpleNamespace(results_path=str(tmp_path / "results")))
    request = _request("run-analysis-1", tmp_path / "input.csv")
    result = SimpleNamespace(status="success", data={"ok": True}, raw_text=None, errors=[])
    ctx = SimpleNamespace(
        log_file=str(tmp_path / "rey_analyzer.jsonl"),
        owner_app_name="rey_analyzer",
        pipeline_name="daily",
        run_id="run-pipe-1",
        run_timestamp="20260706_120000",
    )

    run_dir = write_result(request, result, source_cfg, analysis_cfg=None, ctx=ctx)

    assert (run_dir / "result.json").exists()
    records = [
        json.loads(line)
        for line in Path(ctx.run_log_path).read_text(encoding="utf-8").splitlines()
    ]
    artifact = next(r for r in records if r["record_type"] == "ARTIFACT_REFERENCE")
    assert artifact["record_subgroup"] == "artifacts"
    assert artifact["artifact_role"] == "analysis_result"
    assert artifact["path"] == str(run_dir / "result.json")
    assert artifact["run_id"] == "run-pipe-1"


def test_raw_output_stem_preserves_dots_in_yaml_filename() -> None:
    """Only the real suffix is removed for normal loader YAML files."""
    path = Path("ExtracoBanks_N.A.2026-03-31_Position.yaml")

    assert _raw_output_stem(path) == "ExtracoBanks_N.A.2026-03-31_Position"


def test_raw_output_stem_removes_profile_json_suffix() -> None:
    """Profile inputs remove the compound suffix but keep dots in the stem."""
    path = Path("ExtracoBanks_N.A.2026-03-31_Position.profile.json")

    assert _raw_output_stem(path) == "ExtracoBanks_N.A.2026-03-31_Position"
