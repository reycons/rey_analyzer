"""Tests for result artifact writing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rey_analyzer.results import _artifact_step_name, _raw_output_stem, write_result


def _request(run_id: str, file_path: Path) -> SimpleNamespace:
    """Minimal AnalysisRequest-shaped object for write_result."""
    return SimpleNamespace(
        run_id=run_id, request_id="req-1", source_name="src",
        analysis_name="an", file_path=file_path, input_hash="ih",
        contract_path=Path("contract.md"), contract_hash="ch",
        schema_hash="sh", idempotency_mode="strict",
    )


def test_write_result_writes_flat_named_result_and_context_artifacts(tmp_path: Path) -> None:
    """Result/context artifacts are flat and named with step + run timestamp."""
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

    results_root = write_result(request, result, source_cfg, analysis_cfg=None, ctx=ctx)

    result_file = Path(results_root) / "an.20260706_120000.result.json"
    context_file = Path(results_root) / "an.20260706_120000.context.json"

    assert result_file.exists()
    assert context_file.exists()
    assert not (Path(results_root) / request.run_id).exists()

    context_record = json.loads(context_file.read_text(encoding="utf-8"))
    assert context_record["analysis_name"] == "an"
    assert context_record["run_id"] == "run-analysis-1"

    records = [
        json.loads(line)
        for line in Path(ctx.run_log_path).read_text(encoding="utf-8").splitlines()
    ]
    result_artifact = next(
        r for r in records
        if r["record_type"] == "ARTIFACT_REFERENCE"
        and r.get("artifact_role") == "analysis_result"
    )
    context_artifact = next(
        r for r in records
        if r["record_type"] == "ARTIFACT_REFERENCE"
        and r.get("artifact_role") == "analysis_context"
    )
    assert result_artifact["record_subgroup"] == "artifacts"
    assert result_artifact["path"] == str(result_file)
    assert result_artifact["run_id"] == "run-pipe-1"
    assert result_artifact["producer"] == "analyzer"
    assert result_artifact["artifact_type"] == "analysis_result"
    assert result_artifact["source_path"] == str(tmp_path / "input.csv")
    assert result_artifact["safe_to_preview"] is True

    assert context_artifact["record_subgroup"] == "artifacts"
    assert context_artifact["path"] == str(context_file)
    assert context_artifact["producer"] == "analyzer"
    assert context_artifact["artifact_type"] == "analysis_context"
    assert context_artifact["source_path"] == str(tmp_path / "input.csv")
    assert context_artifact["safe_to_preview"] is True


def test_raw_output_logged_as_llm_artifact(tmp_path: Path) -> None:
    """Raw LLM output is recorded as an llm_result artifact under the llm producer."""
    from rey_lib.logs import group_artifacts_by_producer, normalize_artifacts

    source_cfg = SimpleNamespace(paths=SimpleNamespace(
        results_path=str(tmp_path / "results"),
        raw_output_path=str(tmp_path / "raw")))
    request = _request("run-analysis-2", tmp_path / "input.profile.json")
    result = SimpleNamespace(status="success", data={"ok": True},
                             raw_text="GENERATED DDL", errors=[])
    analysis_cfg = SimpleNamespace(output=SimpleNamespace(write_raw=True))
    ctx = SimpleNamespace(
        log_file=str(tmp_path / "rey_analyzer.jsonl"), owner_app_name="rey_analyzer",
        run_id="run-pipe-2", run_timestamp="20260708_000000",
    )

    write_result(request, result, source_cfg, analysis_cfg=analysis_cfg, ctx=ctx)

    raw_files = list((tmp_path / "raw").rglob("*.yaml"))
    assert len(raw_files) == 1
    assert raw_files[0].read_text(encoding="utf-8") == result.raw_text

    records = [json.loads(line)
               for line in Path(ctx.run_log_path).read_text(encoding="utf-8").splitlines()]
    raw = next(r for r in records
               if r["record_type"] == "ARTIFACT_REFERENCE" and r.get("artifact_role") == "raw_output")
    assert raw["producer"] == "llm"
    assert raw["artifact_type"] == "llm_result"
    assert raw["safe_to_preview"] is True

    # Normalized: analyzer artifacts under analyzer, raw LLM output under llm.
    groups = group_artifacts_by_producer(normalize_artifacts(records))
    assert "analyzer" in groups and "llm" in groups


def test_artifact_step_name_sanitizes_unsafe_input() -> None:
    """Unsafe step names are converted to safe filename components."""
    req = SimpleNamespace(analysis_name=" apply/trade:staging*tables? ", source_name="src")
    assert _artifact_step_name(req) == "apply_trade_staging_tables"


def test_artifact_step_name_uses_safe_fallback_when_empty() -> None:
    """An empty/missing step name falls back to unknown_step."""
    req = SimpleNamespace(analysis_name="  ", source_name="")
    assert _artifact_step_name(req) == "unknown_step"


def test_raw_output_stem_preserves_dots_in_yaml_filename() -> None:
    """Only the real suffix is removed for normal loader YAML files."""
    path = Path("ExtracoBanks_N.A.2026-03-31_Position.yaml")

    assert _raw_output_stem(path) == "ExtracoBanks_N.A.2026-03-31_Position"


def test_raw_output_stem_removes_profile_json_suffix() -> None:
    """Profile inputs remove the compound suffix but keep dots in the stem."""
    path = Path("ExtracoBanks_N.A.2026-03-31_Position.profile.json")

    assert _raw_output_stem(path) == "ExtracoBanks_N.A.2026-03-31_Position"
