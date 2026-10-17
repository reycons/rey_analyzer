"""
rey_analyzer workflow operation -- the approved implementation catalog and its handler.

The canonical Workflow (rey_lib.workflow) binds each WorkflowStep to an
implementation this application approves (``build_process_registry``, published
on the registration as ``approved_implementations``) and runs it through the
step's Run. The one handler wraps the existing ``run_source`` analyzer function.
This module runs no workflow itself.

Public API
----------
build_process_registry  operation name -> approved implementation.
"""

from __future__ import annotations

from typing import Any

from rey_lib.config.ctx import find_in_ctx
from rey_lib.logs import AppLogger
from rey_lib.workflow import RunContext, StepResult

from rey_analyzer.error_utils import AnalyzerError, ConfigurationError
from rey_analyzer.runner import run_source

__all__ = ["build_process_registry"]

_logger = AppLogger(__name__)

# ---------------------------------------------------------------------------
# Process registry (process name -> handler)
# ---------------------------------------------------------------------------

def build_process_registry() -> dict[str, Any]:
    """Return the analyzer's approved implementation catalog (key -> handler).

    Not workflow membership. It answers what this application will let the
    engine call; which processes exist, and how many name one of these, is the
    workflow's declaration. Every key here is published in this application's
    registration, and the engine refuses a workflow naming anything else.

    Each implementation takes the canonical WorkflowStep as its last argument
    (Run.execute passes it).
    """
    def analysis(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext,
                 step: Any = None) -> StepResult:
        return _process_analysis(ctx, run_log, config, run)

    return {"analysis": analysis}


# ---------------------------------------------------------------------------
# Process handler (coordinator signature: ctx, config, run) -> StepResult
# ---------------------------------------------------------------------------

def _process_analysis(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext) -> StepResult:
    """Run one named analyzer source. Calls the existing run_source unchanged.

    ``source`` is the step-config data-source name; the source's own config names
    its analysis config, resolved exactly as the ``run-source`` command does. A
    non-zero failed count fails the step (fail-closed), matching ``run-source``.
    """
    source_name = str(_get(config, "source", "") or "")
    if not source_name:
        raise AnalyzerError("workflow 'analysis' step is missing required config 'source'.")

    source_cfg = _resolve_source(ctx, source_name)
    analysis_cfg = _resolve_analysis(ctx, source_cfg.analysis_config)
    success, failed, pending = run_source(ctx, run_log,
        source_cfg,
        analysis_cfg,
        workflow_name=str(run.metadata.get("workflow") or ""),
    )

    run.metadata[f"analysis:{source_name}"] = {
        "success": success, "failed": failed, "pending": pending,
    }
    detail = f"success={success} failed={failed} pending={pending}"
    if failed:
        return StepResult(source_name, "failed", detail)
    return StepResult(source_name, "ok", detail)


# ---------------------------------------------------------------------------
# Config resolution (same lookups the run-source command uses)
# ---------------------------------------------------------------------------

def _resolve_source(ctx: Any, name: str) -> Any:
    """Look up a data source config by name or raise ConfigurationError."""
    cfg = find_in_ctx(ctx, "data_sources", name)
    if cfg is None:
        raise ConfigurationError(
            f"data_source '{name}' not found. Check config/data_sources/."
        )
    return cfg


def _resolve_analysis(ctx: Any, name: str) -> Any:
    """Look up an analysis config by name or raise ConfigurationError."""
    cfg = find_in_ctx(ctx, "analysis_configs", name)
    if cfg is None:
        raise ConfigurationError(
            f"analysis_config '{name}' not found. "
            f"Check config/app/analysis_configs.yaml."
        )
    return cfg


# ---------------------------------------------------------------------------
# Access helper
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Return obj[key] / obj.key, or default."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
