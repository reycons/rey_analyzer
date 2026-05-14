"""
Analysis request identity and construction.

An AnalysisRequest represents one unit of work: one file processed through
one analysis config. It carries the stable identities used for idempotency
checking and audit tracing.

request_id is deterministic — derived from input, contract, and schema
hashes. The same file through the same contract and schema always produces
the same request_id. It is used as the idempotency_key passed to Analyzer.

run_id is a UUID generated per execution attempt. It is distinct from
request_id so that retries and replays are traceable even when the
request_id is unchanged.

Public API
----------
AnalysisRequest      Frozen dataclass representing one analysis job.
build_request        Factory: constructs an AnalysisRequest from config and file.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rey_lib.llm.analysis import load_analysis_contract

from rey_analyzer.error_utils import ConfigurationError, SourceError

__all__ = ["AnalysisRequest", "build_request"]

_PROJECT_ROOT = Path(__file__).parent.parent


@dataclass(frozen=True)
class AnalysisRequest:
    """
    Immutable descriptor for one analysis job.

    Attributes
    ----------
    request_id : str
        Deterministic 16-char hex derived from input, contract, and schema
        hashes. Used as the idempotency_key passed to Analyzer.analyze().
    run_id : str
        UUID generated per execution attempt. Unique across retries.
    source_name : str
        Name of the data source config that produced this request.
    analysis_name : str
        Name of the analysis config applied.
    file_path : Path
        Absolute path of the file being analyzed (in processing_path).
    input_hash : str
        SHA-256 hex digest of the file bytes.
    contract_path : Path
        Resolved path to the analysis contract file.
    contract_hash : str
        Hash from the loaded AnalysisContract.
    schema_hash : str
        SHA-256 hex digest of the schema file bytes, or empty string if
        no schema file is configured.
    llm_profile_name : str
        Name of the LLM profile to use.
    idempotency_mode : str
        One of: reuse_success, rerun_always, fail_if_exists.
    requires_approval : bool
        Whether the result requires human approval before moving to success.
    """

    request_id:        str
    run_id:            str
    source_name:       str
    analysis_name:     str
    file_path:         Path
    input_hash:        str
    contract_path:     Path
    contract_hash:     str
    schema_hash:       str
    llm_profile_name:  str
    idempotency_mode:  str
    requires_approval: bool


def build_request(
    source_cfg:   Any,
    analysis_cfg: Any,
    file_path:    Path,
) -> AnalysisRequest:
    """
    Construct an AnalysisRequest from config objects and the target file.

    Computes all identity hashes, loads the contract for its hash, and
    resolves the schema hash when a schema file is configured.

    Parameters
    ----------
    source_cfg : Any
        Data source config Namespace (from ctx.data_sources).
    analysis_cfg : Any
        Analysis config Namespace (from ctx.analysis_configs).
    file_path : Path
        Absolute path to the file to be analyzed (in inbox or processing).

    Returns
    -------
    AnalysisRequest
        Fully populated request ready for runner.run_analysis().

    Raises
    ------
    SourceError
        If file_path does not exist or cannot be read.
    ConfigurationError
        If the contract path or analysis config fields are missing.
    """
    if not file_path.exists():
        raise SourceError(f"Input file not found: {file_path}")

    try:
        input_hash = _hash_bytes(file_path.read_bytes())
    except OSError as exc:
        raise SourceError(f"Cannot read input file: {file_path}") from exc

    contract_path = _resolve_path(getattr(analysis_cfg, "contract", None), "contract")
    try:
        contract      = load_analysis_contract(contract_path)
        contract_hash = contract.hash
    except Exception as exc:
        raise ConfigurationError(
            f"Cannot load contract from {contract_path}: {exc}"
        ) from exc

    schema_file = getattr(analysis_cfg, "schema", None)
    schema_hash = ""
    if schema_file:
        schema_path = _resolve_path(schema_file, "schema")
        try:
            schema_hash = _hash_bytes(schema_path.read_bytes())
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot read schema file: {schema_path}"
            ) from exc

    request_id = _compute_request_id(input_hash, contract_hash, schema_hash)

    return AnalysisRequest(
        request_id       = request_id,
        run_id           = str(uuid.uuid4()),
        source_name      = source_cfg.name,
        analysis_name    = analysis_cfg.name,
        file_path        = file_path,
        input_hash       = input_hash,
        contract_path    = contract_path,
        contract_hash    = contract_hash,
        schema_hash      = schema_hash,
        llm_profile_name = getattr(analysis_cfg, "llm_profile", "primary"),
        idempotency_mode = getattr(analysis_cfg, "idempotency_mode", "reuse_success"),
        requires_approval = bool(getattr(analysis_cfg, "requires_approval", False)),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _hash_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _compute_request_id(
    input_hash:    str,
    contract_hash: str,
    schema_hash:   str,
) -> str:
    """Return a 16-char deterministic ID from three content hashes."""
    combined = f"{input_hash}:{contract_hash}:{schema_hash}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def _resolve_path(relative: str | None, label: str) -> Path:
    """Resolve a config-relative path against the project root."""
    if not relative:
        raise ConfigurationError(f"analysis_config.{label} is not set.")
    return (_PROJECT_ROOT / relative).resolve()
