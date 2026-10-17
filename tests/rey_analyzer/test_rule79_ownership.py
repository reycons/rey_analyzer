"""rey_analyzer: one canonical AppError per failure (backlog 709, rule 79).

A source or file failure the runner consumes and continues past is reported
there as the canonical AppError; a failure that propagates is not reported
locally.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from tests.conftest import make_run_log

from rey_analyzer.error_utils import AnalysisError, FileMovementError, SourceError


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_consumed_source_failure_is_one_source_error(
    run_log: Any, sample_ctx: SimpleNamespace, sample_source_cfg: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from rey_analyzer.runner import run_all

    failure = RuntimeError("boom password=hunter2")
    sample_ctx.data_sources = [sample_source_cfg]

    with patch("rey_analyzer.runner._resolve_analysis_cfg", side_effect=failure), \
            caplog.at_level(logging.ERROR):
        assert run_all(sample_ctx, run_log) == (0, 1, 0)

    (record,) = _errors(caplog)
    assert type(record.exc_info[1]) is SourceError
    assert record.exc_info[1].__cause__ is failure
    assert "hunter2" not in record.getMessage()


def test_with_stop_on_error_the_source_failure_propagates_unreported(
    run_log: Any, sample_ctx: SimpleNamespace, sample_source_cfg: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from rey_analyzer.runner import run_all

    failure = RuntimeError("boom")
    sample_ctx.data_sources = [sample_source_cfg]
    sample_ctx.runtime.stop_on_error = True

    with patch("rey_analyzer.runner._resolve_analysis_cfg", side_effect=failure), \
            caplog.at_level(logging.ERROR), pytest.raises(RuntimeError) as raised:
        run_all(sample_ctx, run_log)

    assert raised.value is failure
    assert _errors(caplog) == []


def test_a_failed_file_and_a_failed_move_are_each_their_own_error(
    sample_ctx: SimpleNamespace, sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace, sample_jsonl_file: Path, tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from rey_analyzer.runner import run_analysis

    inbox = Path(sample_source_cfg.paths.inbox_path)
    inbox.mkdir(parents=True, exist_ok=True)
    file_in_inbox = inbox / sample_jsonl_file.name
    file_in_inbox.write_text(sample_jsonl_file.read_text())
    object.__setattr__(sample_ctx, "run_log_path", str(tmp_path / "run.jsonl"))
    object.__setattr__(sample_ctx, "run_id", "r1")
    object.__setattr__(sample_ctx, "run_timestamp", "20260709_000000")
    run_log = make_run_log(tmp_path, app="rey_analyzer", path=str(tmp_path / "run.jsonl"))
    analysis_failure, move_failure = RuntimeError("bad request"), OSError("disk full")

    with patch("rey_analyzer.runner.build_request", side_effect=analysis_failure), \
            patch("rey_analyzer.runner.move_to_failed", side_effect=move_failure), \
            caplog.at_level(logging.ERROR):
        status = run_analysis(
            sample_ctx, run_log, sample_source_cfg, sample_analysis_cfg, file_in_inbox,
        )

    assert status == "failed"
    analysis, movement = _errors(caplog)
    assert type(analysis.exc_info[1]) is AnalysisError
    assert analysis.exc_info[1].__cause__ is analysis_failure
    assert type(movement.exc_info[1]) is FileMovementError
    assert movement.exc_info[1].__cause__ is move_failure

