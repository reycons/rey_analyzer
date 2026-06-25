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

from rey_lib.artifacts import artifact_config_from_ctx
from rey_lib.config.ctx import find_in_ctx
from rey_lib.files.file_utils import (
    discover_inbox_files,
    move_to_failed,
    move_to_processing,
    move_to_success,
    read_text_file,
)
from rey_lib.llm.analysis import Analyzer, AnalysisResult
from rey_lib.logs import get_logger
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
from rey_analyzer.requests import AnalysisRequest, build_request
from rey_analyzer.results import build_artifact_store, write_result

__all__ = ["run_all", "run_source", "run_analysis", "build_payload"]

_logger = get_logger(__name__)

# Maps input_type config values to DataSource construction strategies.
# Text-like formats are all passed as raw text — the LLM reads them as-is.
_TEXT_INPUT_TYPES = frozenset({
    "text_file",
    "jsonl_file",
    "json_file",
    "markdown_file",
})


def run_all(ctx: Any) -> tuple[int, int, int]:
    """
    Process all enabled data sources defined in ctx.

    Iterates ctx.data_sources in declaration order. Disabled sources are
    skipped with a debug log. Failures on one source do not stop others
    unless ctx.runtime.stop_on_error is true.

    Parameters
    ----------
    ctx : Any
        Application context built by build_ctx().

    Returns
    -------
    tuple[int, int, int]
        Total counts of (success, failed, pending_approval) files.
    """
    sources = getattr(ctx, "data_sources", []) or []
    if not sources:
        _logger.warning("No data_sources configured — nothing to process.")
        return 0, 0, 0

    stop_on_error = bool(getattr(getattr(ctx, "runtime", None), "stop_on_error", False))
    total_success = total_failed = total_pending = 0

    for source_cfg in sources:
        if not getattr(source_cfg, "enabled", True):
            _logger.debug("source '%s' disabled — skipping.", source_cfg.name)
            continue

        try:
            analysis_cfg = _resolve_analysis_cfg(ctx, source_cfg.analysis_config)
            success, failed, pending = run_source(ctx, source_cfg, analysis_cfg)
            _logger.info(
                "source '%s' complete: success=%d failed=%d pending=%d",
                source_cfg.name, success, failed, pending,
            )
            total_success += success
            total_failed += failed
            total_pending += pending
        except Exception as exc:  # noqa: BLE001
            _logger.error("source '%s' error: %s", source_cfg.name, exc)
            total_failed += 1
            if stop_on_error:
                raise

    return total_success, total_failed, total_pending


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
        if bool(getattr(source_cfg, "require_input", False)):
            inbox = getattr(getattr(source_cfg, "paths", None), "inbox_path", "")
            pattern = getattr(source_cfg, "file_pattern", "*")
            raise SourceError(
                f"source '{source_cfg.name}': no input files matched "
                f"'{pattern}' in {inbox}. This step requires input produced by "
                "an upstream step. Confirm the upstream step (e.g. file_redactor) "
                "ran successfully and that the inbox path and redact.yaml are correct."
            )
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

    move_files = getattr(source_cfg, "move_files", True)

    processing = file_path
    try:
        request    = build_request(source_cfg, analysis_cfg, file_path, ctx=ctx)
        _move_kwargs = {
            "state_ctx": ctx,
            "app": "rey_analyzer",
            "pipeline": getattr(ctx, "pipeline_name", None),
        }
        processing = move_to_processing(file_path, source_cfg, **_move_kwargs) if move_files else file_path

        llm_profile = _resolve_llm_profile(ctx, request.llm_profile_name)
        analyzer    = _build_analyzer(ctx, analysis_cfg, request, llm_profile)
        source      = _build_data_source(source_cfg.input_type, processing, analysis_cfg)
        result      = analyzer.analyze(source, analysis_id=request.request_id)

        write_result(request, result, source_cfg, analysis_cfg, ctx=ctx)

        if result.status == "pending_approval":
            _logger.info(
                "file '%s' pending approval — remaining in processing.",
                file_path.name,
            )
            return "pending_approval"

        if result.status == "success":
            if move_files:
                move_to_success(processing, source_cfg, **_move_kwargs)
            return "success"

        if move_files:
            move_to_failed(processing, source_cfg, **_move_kwargs)
        return "failed"

    except Exception as exc:  # noqa: BLE001
        _logger.error("analysis failed for '%s': %s", file_path.name, exc)
        if move_files:
            try:
                move_to_failed(processing, source_cfg, state_ctx=ctx, app="rey_analyzer", pipeline=getattr(ctx, "pipeline_name", None))
            except Exception:  # noqa: BLE001
                _logger.error("could not move '%s' to failed.", file_path.name)
        return "failed"


def build_payload(
    ctx:          Any,
    analysis_cfg: Any,
    file_path:    Path,
) -> dict[str, Any]:
    """Build the exact LLM payload for one analysis config and file.

    Applies the same extract → prepare pipeline as run_analysis but stops
    before calling the LLM provider. Returns a dict with the formatted
    payload string and preparation metadata.

    Parameters
    ----------
    ctx : Any
        Application context — used to resolve ``contracts_root``.
    analysis_cfg : Any
        Analysis config Namespace (from ctx.analysis_configs).
    file_path : Path
        Absolute path to the file to include in the payload.

    Returns
    -------
    dict[str, Any]
        Keys: analysis_name, data_file, rows_sampled, content.
    """
    from rey_lib.llm.analysis import load_analysis_contract  # noqa: PLC0415
    from rey_lib.llm.preparation import prepare  # noqa: PLC0415

    # Resolve contract path the same way build_request does.
    contracts_root_val = getattr(ctx, "contracts_root", None)
    contracts_root = (
        Path(str(contracts_root_val)).expanduser().resolve()
        if contracts_root_val
        else Path(__file__).parent.parent
    )
    contract_rel = getattr(analysis_cfg, "contract", "")
    if not contract_rel:
        raise ConfigurationError(
            f"analysis_config '{analysis_cfg.name}' has no contract path."
        )
    p = Path(contract_rel)
    contract_path = p.resolve() if p.is_absolute() else (contracts_root / contract_rel).resolve()

    contract = load_analysis_contract(contract_path)

    # Infer input type from file extension — mirrors _build_data_source logic.
    suffix = file_path.suffix.lower()
    input_type_map = {
        ".jsonl": "jsonl_file",
        ".json":  "json_file",
        ".csv":   "csv_file",
        ".xlsx":  "excel_file",
        ".xls":   "excel_file",
    }
    input_type = input_type_map.get(suffix, "text_file")
    source = _build_data_source(input_type, file_path, analysis_cfg)

    spec = contract.spec
    raw = source.extract(max_extract=10_000)
    prepared = prepare(
        raw,
        allowed_columns  = spec.allowed_columns,
        required_filters = spec.required_filters,
        max_rows         = spec.max_rows,
        sampling_method  = spec.sampling_method,
        sampling_seed    = spec.sampling_seed,
        redaction_rules  = spec.redaction,
    )

    _logger.info(
        "build-payload: contract='%s' rows_sampled=%d file='%s'",
        contract.name,
        prepared.profile.rows_sampled,
        file_path.name,
    )

    content = "\n".join([
        f"# {contract.name}",
        "",
        "## System Prompt (Contract)",
        "",
        contract.base.body.strip(),
        "",
        "---",
        "",
        f"## Input Data — {file_path.name} ({prepared.profile.rows_sampled} rows)",
        "",
        prepared.rendered_text,
    ])

    return {
        "analysis_name": analysis_cfg.name,
        "data_file":     file_path.name,
        "rows_sampled":  prepared.profile.rows_sampled,
        "content":       content,
    }


# ---------------------------------------------------------------------------
# Private factories
# ---------------------------------------------------------------------------

# Profile keys forwarded to the provider as options (endpoint, timeout, and
# capability flags). Only keys present on the profile are forwarded.
_PROVIDER_OPTION_KEYS = (
    "endpoint",
    "timeout_seconds",
    "supports_tools",
    "supports_images",
    "supports_json_mode",
    "supports_streaming",
    "supports_system_messages",
    "max_context_tokens",
)


def _profile_provider_options(llm_profile: Any) -> dict[str, Any]:
    """Collect provider option keys present on the LLM profile."""
    options: dict[str, Any] = {}
    for key in _PROVIDER_OPTION_KEYS:
        value = getattr(llm_profile, key, None)
        if value is not None:
            options[key] = value
    return options


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
        temperature       = float(getattr(llm_profile, "temperature", 0.0) or 0.0),
        provider_options  = _profile_provider_options(llm_profile),
        artifact_store    = artifact_store,
        requires_approval = request.requires_approval,
        artifact_processing = artifact_config_from_ctx(ctx),
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
            text = read_text_file(file_path, encoding="utf-8")
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
