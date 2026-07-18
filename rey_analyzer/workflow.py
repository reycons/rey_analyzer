"""
rey_analyzer workflows — process registry, handler, and runner.

Ownership: the shared coordinator (``rey_lib.workflow.run_workflow``) owns all
workflow execution mechanics (sequencing, step/range selection, fail-closed
behaviour, dry-run/apply propagation, run context, outcomes). This module owns
only the analyzer domain: the process *registry* and the single *handler* that
wraps the existing, unchanged ``run_source`` analyzer function.

This is an orchestration refactor only — the handler calls the existing analyzer
function as-is. No analysis behaviour, output, config semantics, or
success/failure rules change here.

Public API
----------
build_process_registry  process name -> handler for the shared coordinator.
run_process_workflow    Run one ordered workflow pass through the coordinator.
"""

from __future__ import annotations

from typing import Any

from rey_lib.config.ctx import find_in_ctx
from rey_lib.logs import get_logger
from rey_lib.workflow import (
    RunContext,
    StepResult,
    run_workflow as coordinate_workflow,
)

from rey_analyzer.error_utils import AnalyzerError, ConfigurationError
from rey_analyzer.runner import run_source

__all__ = [
    "build_process_registry",
    "run_process_workflow",
]

_logger = get_logger(__name__)

# This app's identity. Workflow ownership is ``app + name``; rey_analyzer consumes
# only workflows assigned to itself from the resolved ctx (never another app's).
APP_NAME = "rey_analyzer"


# ---------------------------------------------------------------------------
# Process registry (process name -> handler)
# ---------------------------------------------------------------------------

def build_process_registry() -> dict[str, Any]:
    """Return the analyzer's workflow process registry (name -> handler).

    One process, ``analysis``, wraps the existing ``run_source`` unchanged. Steps
    may only call this registered process name, never arbitrary Python from YAML.
    """
    def analysis(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
        return _process_analysis(ctx, config, run)

    return {"analysis": analysis}


# ---------------------------------------------------------------------------
# Process handler (coordinator signature: ctx, config, run) -> StepResult
# ---------------------------------------------------------------------------

def _process_analysis(ctx: Any, config: dict[str, Any], run: RunContext) -> StepResult:
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
    success, failed, pending = run_source(ctx, source_cfg, analysis_cfg)

    run.metadata[f"analysis:{source_name}"] = {
        "success": success, "failed": failed, "pending": pending,
    }
    detail = f"success={success} failed={failed} pending={pending}"
    if failed:
        return StepResult(source_name, "failed", detail)
    return StepResult(source_name, "ok", detail)


# ---------------------------------------------------------------------------
# Runner (delegates sequencing to the shared workflow coordinator)
# ---------------------------------------------------------------------------

def run_process_workflow(
    ctx: Any,
    workflow_name: str,
    *,
    apply: bool = True,
    step: str | None = None,
    from_step: str | None = None,
    to_step: str | None = None,
) -> int:
    """Execute one ordered analyzer workflow pass through the shared coordinator.

    Resolves and ownership-checks the workflow from ctx, seeds run metadata, then
    dispatches its steps through the shared coordinator against this app's process
    registry. ``step`` / ``from_step`` / ``to_step`` are thin pass-throughs for
    single-step and range execution; selection semantics are owned by
    rey_lib.workflow, not this app. Returns 0 / 1.
    """
    wf = _get_workflow(ctx, workflow_name)
    metadata = {
        "workflow": workflow_name,
        "mode": "apply" if apply else "dry-run",
    }
    run = coordinate_workflow(
        ctx,
        wf,
        build_process_registry(),
        apply=apply,
        step=step,
        from_step=from_step,
        to_step=to_step,
        metadata=metadata,
    )
    if run.status != "success":
        failed = next((o for o in run.outcomes if o.status == "failed"), None)
        _logger.error("workflow '%s' failed at step: %s",
                      workflow_name, failed.id if failed else "?")
        return 1
    _logger.info("workflow '%s' complete (%s).",
                 workflow_name, "apply" if apply else "dry-run")
    return 0


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
# Ownership + access helpers
# ---------------------------------------------------------------------------

def _get_workflow(ctx: Any, name: str) -> Any:
    """Return the named workflow config from the resolved ctx, or raise.

    Consumes ``ctx.workflows`` only — no filesystem discovery — and enforces
    ownership before returning: a workflow assigned to another app is refused,
    so rey_analyzer can never run a workflow it does not own.
    """
    workflows = getattr(ctx, "workflows", None)
    wf = None
    if isinstance(workflows, list):
        for item in workflows:
            if str(_get(item, "name", "")) == name:
                wf = item
                break
    elif workflows is not None:
        wf = _get(workflows, name)
    if wf is None:
        raise AnalyzerError(
            f"workflow '{name}' not found in rey_analyzer config (ctx.workflows)."
        )
    _enforce_ownership(wf, name)
    return wf


def _enforce_ownership(wf: Any, name: str) -> None:
    """Refuse a workflow owned by another app (fail-closed on mismatch).

    Ownership is the resolved workflow's ``app`` property, stamped during ctx
    construction. An empty owner is treated as this app's; a foreign owner raises.
    """
    owner = str(_get(wf, "app", "") or "")
    if owner and owner != APP_NAME:
        raise AnalyzerError(
            f"Workflow {name} is assigned to {owner} and cannot be executed "
            f"by {APP_NAME}."
        )


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Return obj[key] / obj.key, or default."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
