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

from rey_lib.logs import AppLogger
from rey_lib.workflow import RunContext, StepResult

from rey_analyzer.error_utils import AnalyzerError
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
                 step: Any) -> StepResult:
        return _process_analysis(ctx, run_log, config, run, step)

    return {"analysis": analysis}


# ---------------------------------------------------------------------------
# Process handler (ctx, run_log, config, run, step) -> StepResult
# ---------------------------------------------------------------------------

def _process_analysis(ctx: Any, run_log: Any, config: dict[str, Any], run: RunContext,
                      step: Any) -> StepResult:
    """Run one named analyzer source. Calls the existing run_source unchanged.

    ``source`` is the step-config data-source name. The data source is part of
    the step's process's governed configuration (backlogs 1032, 1043): the
    step's own WorkflowProcess holds it, hydrated with the workflow's paths. Its
    config names its analysis config, which the same process holds, as it holds
    the app and runtime sections the run reads (backlog 1005). A non-zero failed
    count fails the step (fail-closed).
    """
    source_name = str(_get(config, "source", "") or "")
    if not source_name:
        raise AnalyzerError("workflow 'analysis' step is missing required config 'source'.")

    source_cfg = step.process.data_source(source_name)
    analysis_cfg = step.process.analysis_config(source_cfg.analysis_config)
    success, failed, pending = run_source(ctx, run_log,
        source_cfg,
        analysis_cfg,
        app_cfg=step.process.config_section("app"),
        runtime_cfg=step.process.config_section("runtime"),
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
# Access helper
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Return obj[key] / obj.key, or default."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
