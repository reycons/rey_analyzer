"""Tests for rey_analyzer CLI exit behavior."""

from types import SimpleNamespace
from unittest.mock import patch

import main as analyzer_main


def _args(command: str, **values: object) -> SimpleNamespace:
    """Build minimal parsed args for main() tests."""
    defaults = {
        "command": command,
        "config_path": "/tmp/configs/v01",
        "config_dir": None,
        "env_overrides": [],
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _ctx() -> SimpleNamespace:
    """Build a minimal ctx accepted by setup_logging."""
    return SimpleNamespace(
        app=SimpleNamespace(log_path=None),
        logs=SimpleNamespace(log_path=None),
    )


def test_run_source_returns_nonzero_when_any_file_failed() -> None:
    """A partial file failure must fail the process for pipeline_coordinator."""
    source = SimpleNamespace(analysis_config="analysis")

    with (
        patch.object(analyzer_main, "_parse_args", return_value=_args("run-source", source="src")),
        patch.object(analyzer_main, "apply_env_overrides"),
        patch.object(analyzer_main, "build_ctx_from_args", return_value=_ctx()),
        patch.object(analyzer_main, "_resolve_source", return_value=source),
        patch.object(analyzer_main, "_resolve_analysis", return_value=SimpleNamespace()),
        patch.object(analyzer_main, "run_source", return_value=(4, 1, 0)),
        patch.object(analyzer_main, "setup_logging"),
    ):
        assert analyzer_main.main() == 1


def test_submit_file_returns_nonzero_when_analysis_failed() -> None:
    """A failed single-file analysis must fail the process."""
    source = SimpleNamespace(analysis_config="analysis")

    with (
        patch.object(
            analyzer_main,
            "_parse_args",
            return_value=_args("submit-file", source="src", file="/tmp/input.json"),
        ),
        patch.object(analyzer_main, "apply_env_overrides"),
        patch.object(analyzer_main, "build_ctx_from_args", return_value=_ctx()),
        patch.object(analyzer_main, "_resolve_source", return_value=source),
        patch.object(analyzer_main, "_resolve_analysis", return_value=SimpleNamespace()),
        patch.object(analyzer_main, "run_analysis", return_value="failed"),
        patch.object(analyzer_main, "setup_logging"),
    ):
        assert analyzer_main.main() == 1
