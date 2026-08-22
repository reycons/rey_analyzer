"""Tests for rey_analyzer.runner."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_run_log

from rey_analyzer.error_utils import SourceError
from rey_analyzer.runner import _build_data_source, _max_files


def test_build_data_source_jsonl_returns_text_source(tmp_path: Path) -> None:
    """jsonl_file input_type returns a TextDataSource."""
    from rey_lib.llm.datasource import TextDataSource

    f = tmp_path / "test.jsonl"
    f.write_text('{"level":"ERROR"}\n', encoding="utf-8")
    src = _build_data_source("jsonl_file", f)
    assert isinstance(src, TextDataSource)


def test_build_data_source_csv_returns_csv_source(tmp_path: Path) -> None:
    """csv_file input_type returns a CSVDataSource."""
    from rey_lib.llm.datasource import CSVDataSource

    f = tmp_path / "test.csv"
    f.write_text("col1,col2\na,b\n", encoding="utf-8")
    src = _build_data_source("csv_file", f)
    assert isinstance(src, CSVDataSource)


def test_build_data_source_unknown_type_raises_source_error(tmp_path: Path) -> None:
    """Unknown input_type raises SourceError."""
    f = tmp_path / "test.xyz"
    f.write_text("data")
    with pytest.raises(SourceError, match="Unsupported input_type"):
        _build_data_source("xyz_file", f)


def test_build_data_source_text_types(tmp_path: Path) -> None:
    """All text-like input types return TextDataSource."""
    from rey_lib.llm.datasource import TextDataSource

    f = tmp_path / "test.txt"
    f.write_text("hello", encoding="utf-8")
    for input_type in ("text_file", "jsonl_file", "json_file", "markdown_file"):
        src = _build_data_source(input_type, f)
        assert isinstance(src, TextDataSource), input_type


def test_max_files_uses_minimum(sample_ctx: SimpleNamespace) -> None:
    """_max_files returns the lower of runtime and source caps."""
    sample_ctx.runtime.max_files_per_run = 50
    source_cfg = SimpleNamespace(max_files_per_run=10)
    assert _max_files(sample_ctx, source_cfg) == 10


def test_max_files_defaults_to_runtime(sample_ctx: SimpleNamespace) -> None:
    """_max_files falls back to runtime cap when source has no override."""
    sample_ctx.runtime.max_files_per_run = 25
    source_cfg = SimpleNamespace()
    assert _max_files(sample_ctx, source_cfg) == 25


def test_run_source_empty_inbox(run_log, 
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
) -> None:
    """run_source returns (0, 0, 0) when the inbox is empty."""
    from rey_analyzer.runner import run_source

    success, failed, pending = run_source(
        sample_ctx, run_log, sample_source_cfg, sample_analysis_cfg
    )
    assert (success, failed, pending) == (0, 0, 0)


def test_run_source_logs_input_discovery_count(run_log, 
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
    tmp_path: Path,
) -> None:
    """run_source records discovered analyzer input files through shared helpers."""
    from rey_analyzer.runner import run_source

    object.__setattr__(sample_ctx, "run_log_path", str(tmp_path / "run.jsonl"))
    run_log = make_run_log(tmp_path, app="rey_analyzer",
                           path=str(tmp_path / "run.jsonl"))
    object.__setattr__(sample_ctx, "run_id", "r1")
    object.__setattr__(sample_ctx, "run_timestamp", "20260709_000000")
    inbox = Path(sample_source_cfg.paths.inbox_path)
    inbox.mkdir(parents=True, exist_ok=True)
    file_in_inbox = inbox / sample_jsonl_file.name
    file_in_inbox.write_text(sample_jsonl_file.read_text(encoding="utf-8"), encoding="utf-8")

    with patch("rey_analyzer.runner.run_analysis", return_value="success"):
        success, failed, pending = run_source(
            sample_ctx, run_log, sample_source_cfg, sample_analysis_cfg
        )

    assert (success, failed, pending) == (1, 0, 0)
    records = [
        json.loads(line)
        for line in Path(sample_ctx.run_log_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    count = next(r for r in records if r["record_type"] == "ROW_COUNT")
    discovered = next(r for r in records if r["record_type"] == "INPUT_DISCOVERED")
    assert count["count_name"] == "analysis_input_files_discovered"
    assert count["count"] == 1
    assert discovered["path"] == str(file_in_inbox)
    assert discovered["source_config"] == sample_source_cfg.name


def test_two_file_analyses_create_sibling_input_branches(run_log, 
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
    tmp_path: Path,
) -> None:
    """Each input is a sibling anchor and owns its file-processing records."""
    from rey_analyzer.runner import run_source

    object.__setattr__(sample_ctx, "run_log_path", str(tmp_path / "run.jsonl"))
    run_log = make_run_log(tmp_path, app="rey_analyzer",
                           path=str(tmp_path / "run.jsonl"))
    object.__setattr__(sample_ctx, "run_id", "r1")
    object.__setattr__(sample_ctx, "run_timestamp", "20260709_000000")

    inbox = Path(sample_source_cfg.paths.inbox_path)
    inbox.mkdir(parents=True, exist_ok=True)
    for name in ("file_a.jsonl", "file_b.jsonl"):
        (inbox / name).write_text(
            sample_jsonl_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # The app boundary (run_app_operation) establishes app level before run_source.
    run_log.set_nest_level("app")
    sample_source_cfg.move_files = False

    with patch("rey_analyzer.runner.build_request", side_effect=RuntimeError("stop")):
        assert run_source(sample_ctx, run_log, sample_source_cfg, sample_analysis_cfg) == (0, 2, 0)

    records = [
        json.loads(line)
        for line in Path(sample_ctx.run_log_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    refs = [r for r in records if r["record_type"] == "INPUT_FILE_REFERENCE"]
    assert len(refs) == 2
    # Siblings: same parent and same analysis level.
    assert refs[0]["parent_record_id"] == refs[1]["parent_record_id"]
    assert refs[0]["nest_level"] == refs[1]["nest_level"]
    # The second file is not parented under the first file's record.
    assert refs[1]["parent_record_id"] != refs[0]["record_id"]
    validations = [r for r in records if r["record_type"] == "VALIDATION_RESULT"]
    by_input = {Path(r["input_file"]).name: r for r in validations}
    for ref in refs:
        validation = by_input[ref["display_name"]]
        assert validation["parent_record_id"] == ref["record_id"]
        assert validation["nest_level"] == ref["nest_level"] + 1
    assert [r["record_id"] for r in records] == list(range(1, len(records) + 1))


def test_run_all_returns_failed_count_on_source_exception(run_log, 
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
) -> None:
    """run_all includes source-level failures in the returned counts."""
    from rey_analyzer.runner import run_all

    sample_source_cfg.analysis_config = "missing_config"
    sample_ctx.data_sources = [sample_source_cfg]

    success, failed, pending = run_all(sample_ctx, run_log)

    assert (success, failed, pending) == (0, 1, 0)


def test_run_analysis_moves_to_failed_on_exception(run_log, 
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
    tmp_path: Path,
) -> None:
    """run_analysis returns 'failed' and moves file to failed_path on error."""
    from rey_analyzer.runner import run_analysis

    inbox = Path(sample_source_cfg.paths.inbox_path)
    inbox.mkdir(parents=True, exist_ok=True)
    file_in_inbox = inbox / sample_jsonl_file.name
    file_in_inbox.write_text(sample_jsonl_file.read_text())
    object.__setattr__(sample_ctx, "run_log_path", str(tmp_path / "run.jsonl"))
    run_log = make_run_log(tmp_path, app="rey_analyzer",
                           path=str(tmp_path / "run.jsonl"))
    object.__setattr__(sample_ctx, "run_id", "r1")
    object.__setattr__(sample_ctx, "run_timestamp", "20260709_000000")

    with patch("rey_analyzer.runner.build_request", side_effect=Exception("boom")):
        status = run_analysis(
            sample_ctx, run_log, sample_source_cfg, sample_analysis_cfg, file_in_inbox
        )

    assert status == "failed"
    records = [
        json.loads(line)
        for line in Path(sample_ctx.run_log_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    input_ref = next(r for r in records if r["record_type"] == "INPUT_FILE_REFERENCE")
    validation = next(r for r in records if r["record_type"] == "VALIDATION_RESULT")
    assert input_ref["file_role"] == "analysis_input"
    assert input_ref["path"] == str(file_in_inbox)
    assert validation["validation_name"] == "analysis_result"
    assert validation["status"] == "failed"


def test_run_analysis_supplies_resolved_file_set_as_second_input(run_log, 
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A contract requiring file_set values receives them beside the profile."""
    import rey_analyzer.runner as runner

    profile = tmp_path / "profile.json"
    profile.write_text('{"source":"example","columns":[]}', encoding="utf-8")
    request = SimpleNamespace(
        request_id="req-1",
        input_hash="profile-hash",
        contract_hash="contract-hash",
        schema_hash="schema-hash",
        contract_path=tmp_path / "contract.yaml",
        file_path=profile,
        analysis_name="loader_config",
        source_name="profile_source",
        llm_profile_name="profile",
        requires_approval=False,
    )
    request.contract_path.write_text("name: c\nversion: 1\n", encoding="utf-8")

    captured: dict[str, object] = {}
    validations: list[dict[str, object]] = []

    class FakeAnalyzer:
        contract = SimpleNamespace(base=SimpleNamespace(raw_frontmatter={
            "file_set": {
                "required_values": ["target_connection", "loader_inbox_path"],
            },
        }))

        def analyze(self, source, analysis_id):  # noqa: ANN001, ANN201
            captured["provider_input"] = source.extract().raw_text
            return SimpleNamespace(status="success", prepared=None, record=None)

    ctx = SimpleNamespace(
        pipeline_name="pipeline",
        pipelines=[SimpleNamespace(
            name="pipeline",
            tokens=SimpleNamespace(
                target_connection="rey_apps",
                loader_inbox_path="/resolved/inbox",
            ),
        )],
    )
    source_cfg = SimpleNamespace(name="source", input_type="json_file", move_files=False)
    analysis_cfg = SimpleNamespace(name="loader_config")

    monkeypatch.setattr(runner, "build_request", lambda *_a, **_k: request)
    monkeypatch.setattr(
        runner,
        "_resolve_llm_profile",
        lambda *_a: SimpleNamespace(provider="provider", model="model"),
    )
    monkeypatch.setattr(runner, "_build_analyzer", lambda *_a: FakeAnalyzer())
    monkeypatch.setattr(runner, "write_result", lambda *_a, **_k: None)
    monkeypatch.setattr(runner, "log_input_file_reference", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runner,
        "log_validation_result",
        lambda *_a, **kwargs: validations.append(kwargs),
    )
    monkeypatch.setattr(
        runner,
        "emit_llm_evidence",
        lambda *_a, **kwargs: captured.update(evidence_inputs=kwargs["inputs"]),
    )

    assert runner.run_analysis(ctx, run_log, source_cfg, analysis_cfg, profile) == "success"

    provider_package = json.loads(str(captured["provider_input"]))
    assert [item["name"] for item in provider_package["inputs"]] == [
        "analysis_input", "file_set",
    ]
    assert provider_package["inputs"][1]["content"] == {
        "target_connection": "rey_apps",
        "loader_inbox_path": "/resolved/inbox",
    }
    evidence_inputs = captured["evidence_inputs"]
    assert [item.name for item in evidence_inputs] == ["analysis_input", "file_set"]
    execution = next(
        item
        for item in validations
        if item["validation_name"] == "analyzer_execution_contract"
    )
    assert execution == {
        "validation_name": "analyzer_execution_contract",
        "status": "passed",
        "message": "Resolved governed Analyzer execution for 'loader_config'.",
        "source_name": "profile_source",
        "analysis_name": "loader_config",
        "input_file": str(profile),
        "input_hash": "profile-hash",
        "contract_path": str(request.contract_path),
        "contract_hash": "contract-hash",
        "schema_hash": "schema-hash",
        "model_profile": "profile",
        "provider": "provider",
        "model": "model",
    }
