"""
Assembly-line orchestrator for rey_analyzer.

runner.py is the single module that connects all other modules. It owns
the per-file lifecycle: discover → claim → analyze → write → move. It
delegates every specialised concern to the appropriate module or rey_lib.

No LLM logic lives here. No file-format parsing lives here. No path
construction beyond what is required to wire config to rey_lib.

Public API
----------
run_all        Process all enabled data sources.
run_source     Process all inbox files for one named data source.
run_analysis   Process a single file through a single analysis config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rey_lib.config.ctx import find_in_ctx
from rey_lib.llm.analysis import Analyzer, AnalysisResult
from rey_lib.logs.log_utils import get_logger
from rey_lib.llm.artifacts import LocalArtifactStore
from rey_lib.llm.datasource import (
    CSVDataSource,
    DataSource,
    ExcelDataSource,
    TextDataSource,
)

from rey_analyzer.error_utils import (
    AnalysisError,
    ConfigurationError,
    SourceError,
)
from rey_analyzer.preprocessor import build_incident_packet
from rey_analyzer.file_handler import (
    discover_inbox_files,
    move_to_failed,
    move_to_processing,
    move_to_success,
)
from rey_analyzer.requests import AnalysisRequest, build_request
from rey_analyzer.results import build_artifact_store, write_result

__all__ = ["run_all", "run_source", "run_analysis"]

_logger = get_logger(__name__)

# Maps input_type config values to DataSource construction strategies.
# Text-like formats are all passed as raw text — the LLM reads them as-is.
_TEXT_INPUT_TYPES = frozenset({
    "text_file",
    "jsonl_file",
    "json_file",
    "markdown_file",
})


def run_all(ctx: Any) -> None:
    """
    Process all enabled data sources defined in ctx.

    Iterates ctx.data_sources in declaration order. Disabled sources are
    skipped with a debug log. Failures on one source do not stop others
    unless ctx.runtime.stop_on_error is true.

    Parameters
    ----------
    ctx : Any
        Application context built by build_ctx().
    """
    sources = getattr(ctx, "data_sources", []) or []
    if not sources:
        _logger.warning("No data_sources configured — nothing to process.")
        return

    stop_on_error = bool(getattr(getattr(ctx, "runtime", None), "stop_on_error", False))

    for source_cfg in sources:
        if not getattr(source_cfg, "enabled", True):
            _logger.debug("source '%s' disabled — skipping.", source_cfg.name)
            continue

        analysis_cfg = _resolve_analysis_cfg(ctx, source_cfg.analysis_config)
        try:
            success, failed, pending = run_source(ctx, source_cfg, analysis_cfg)
            _logger.info(
                "source '%s' complete: success=%d failed=%d pending=%d",
                source_cfg.name, success, failed, pending,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error("source '%s' error: %s", source_cfg.name, exc)
            if stop_on_error:
                raise


def run_source(
    ctx:          Any,
    source_cfg:   Any,
    analysis_cfg: Any,
) -> tuple[int, int, int]:
    """
    Process all inbox files for one data source.

    Applies per-source max_files_per_run cap (lowest of source config and
    ctx.runtime.max_files_per_run). Files are processed in sorted order.

    Parameters
    ----------
    ctx : Any
        Application context.
    source_cfg : Any
        Data source config Namespace.
    analysis_cfg : Any
        Analysis config Namespace.

    Returns
    -------
    tuple[int, int, int]
        Counts of (success, failed, pending_approval) files.
    """
    max_files = _max_files(ctx, source_cfg)
    files     = discover_inbox_files(source_cfg)[:max_files]

    if not files:
        _logger.info("source '%s': inbox is empty.", source_cfg.name)
        return 0, 0, 0

    _logger.info("source '%s': %d file(s) to process.", source_cfg.name, len(files))

    success = failed = pending = 0

    for file_path in files:
        status = run_analysis(ctx, source_cfg, analysis_cfg, file_path)
        if status == "success":
            success += 1
        elif status == "pending_approval":
            pending += 1
        else:
            failed += 1

    return success, failed, pending


def run_analysis(
    ctx:          Any,
    source_cfg:   Any,
    analysis_cfg: Any,
    file_path:    Path,
) -> str:
    """
    Run the full analysis lifecycle for one file.

    Stages
    ------
    1. Build AnalysisRequest (hashes, identity).
    2. Move file from inbox to processing (claim ownership).
    3. Resolve LLM profile.
    4. Build Analyzer and DataSource.
    5. Call Analyzer.analyze().
    6. Write result artifacts.
    7. Move file to success, failed, or leave in processing (pending approval).

    Parameters
    ----------
    ctx : Any
        Application context.
    source_cfg : Any
        Data source config Namespace.
    analysis_cfg : Any
        Analysis config Namespace.
    file_path : Path
        Absolute path of the file in inbox_path.

    Returns
    -------
    str
        Final status: 'success', 'pending_approval', or 'failed'.
    """
    object.__setattr__(ctx, "source_name", source_cfg.name)
    object.__setattr__(ctx, "analysis_name", analysis_cfg.name)
    object.__setattr__(ctx, "current_file", file_path.name)

    request     = build_request(source_cfg, analysis_cfg, file_path)
    processing  = move_to_processing(file_path, source_cfg)

    try:
        llm_profile  = _resolve_llm_profile(ctx, request.llm_profile_name)
        analyzer     = _build_analyzer(ctx, analysis_cfg, request, llm_profile)
        source       = _build_data_source(source_cfg.input_type, processing, analysis_cfg)
        result       = analyzer.analyze(source, analysis_id=request.request_id)

        write_result(request, result, source_cfg)

        if result.status == "pending_approval":
            _logger.info(
                "file '%s' pending approval — remaining in processing.",
                file_path.name,
            )
            return "pending_approval"

        if result.status == "success":
            move_to_success(processing, source_cfg)
            return "success"

        move_to_failed(processing, source_cfg)
        return "failed"

    except Exception as exc:  # noqa: BLE001
        _logger.error("analysis failed for '%s': %s", file_path.name, exc)
        try:
            move_to_failed(processing, source_cfg)
        except Exception:  # noqa: BLE001
            _logger.error("could not move '%s' to failed.", file_path.name)
        return "failed"


# ---------------------------------------------------------------------------
# Private factories
# ---------------------------------------------------------------------------

def _build_analyzer(
    ctx:          Any,
    analysis_cfg: Any,
    request:      AnalysisRequest,
    llm_profile:  Any,
) -> Analyzer:
    """Construct an Analyzer for the given request."""
    artifact_store = build_artifact_store(ctx)
    return Analyzer(
        contract_path     = request.contract_path,
        provider          = llm_profile.provider,
        model             = llm_profile.model,
        api_key           = getattr(llm_profile, "api_key", ""),
        artifact_store    = artifact_store,
        requires_approval = request.requires_approval,
    )


def _build_data_source(
    input_type:   str,
    file_path:    Path,
    analysis_cfg: Any = None,
) -> DataSource:
    """
    Construct the appropriate DataSource for the given input_type.

    Parameters
    ----------
    input_type : str
        One of: text_file, jsonl_file, json_file, markdown_file,
        csv_file, excel_file.
    file_path : Path
        Absolute path to the file to read.
    analysis_cfg : Any, optional
        Analysis config Namespace. When present and input_type is
        'jsonl_file', applies analysis_cfg.input.include_levels filtering.

    Returns
    -------
    DataSource
        Configured data source instance.

    Raises
    ------
    SourceError
        If input_type is not recognised.
    """
    if input_type == "jsonl_file" and analysis_cfg is not None:
        input_cfg = getattr(analysis_cfg, "input", None)
        if input_cfg is not None:
            text = build_incident_packet(file_path, input_cfg)
            return TextDataSource(text=text, ref=file_path.name)

    if input_type in _TEXT_INPUT_TYPES:
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SourceError(f"Cannot read {file_path}: {exc}") from exc
        return TextDataSource(text=text, ref=file_path.name)

    if input_type == "csv_file":
        return CSVDataSource(path=file_path)

    if input_type == "excel_file":
        return ExcelDataSource(path=file_path)

    raise SourceError(
        f"Unsupported input_type '{input_type}'. "
        f"Supported: text_file, jsonl_file, json_file, markdown_file, "
        f"csv_file, excel_file."
    )


def _resolve_analysis_cfg(ctx: Any, name: str) -> Any:
    """Look up a named analysis config in ctx.analysis_configs."""
    cfg = find_in_ctx(ctx, "analysis_configs", name)
    if cfg is None:
        raise ConfigurationError(
            f"analysis_config '{name}' not found. "
            f"Check config/app/analysis_configs.yaml."
        )
    return cfg


def _resolve_llm_profile(ctx: Any, name: str) -> Any:
    """Look up a named LLM profile in ctx.llm_profiles."""
    profile = find_in_ctx(ctx, "llm_profiles", name)
    if profile is None:
        raise ConfigurationError(
            f"llm_profile '{name}' not found. "
            f"Check config/app/llm_configs.yaml."
        )
    return profile


def _max_files(ctx: Any, source_cfg: Any) -> int:
    """Return the effective per-run file cap for a data source."""
    runtime_max = getattr(getattr(ctx, "runtime", None), "max_files_per_run", 100)
    source_max  = getattr(source_cfg, "max_files_per_run", runtime_max)
    return min(runtime_max, source_max)
