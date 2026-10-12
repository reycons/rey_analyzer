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

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rey_lib.encryption import sha256_bytes, sha256_file, sha256_text
from rey_lib.ai.errors import AIConfigurationError
from rey_lib.analysis import analysis_contract
from rey_lib.errors.error_utils import ConfigError

from rey_analyzer.error_utils import ConfigurationError, SourceError

__all__ = ["AnalysisRequest", "build_request"]

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
    contract : Any
        The AnalysisContract, read by name from control.analysis_contract.
    contract_hash : str
        Hash from the AnalysisContract.
    schema_hash : str
        Hash of the contract's embedded output_schema as canonical JSON --
        the definition the execution record uses -- or empty string when the
        contract declares none.
    llm_profile_name : str
        Name of the LLM execution profile to use.
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
    contract:          Any
    contract_hash:     str
    schema_hash:       str
    llm_profile_name:  str
    idempotency_mode:  str
    requires_approval: bool


def build_request(
    source_cfg:   Any,
    analysis_cfg: Any,
    file_path:    Path,
    ctx:          Any = None,
) -> AnalysisRequest:
    """
    Construct an AnalysisRequest from config objects and the target file.

    Computes all identity hashes. The contract is read by its name from
    control.analysis_contract (backlog 903); its hash and the hash of its
    embedded output_schema are part of the request identity.

    Parameters
    ----------
    source_cfg : Any
        Data source config Namespace (from ctx.data_sources).
    analysis_cfg : Any
        Analysis config Namespace (from ctx.analysis_configs).
    file_path : Path
        Absolute path to the file to be analyzed (in inbox or processing).
    ctx : Any, optional
        Application context; its ``shared_control`` reads the contract.

    Returns
    -------
    AnalysisRequest
        Fully populated request ready for runner.run_analysis().

    Raises
    ------
    SourceError
        If file_path does not exist or cannot be read.
    ConfigurationError
        If the contract or analysis config fields are missing.
    """
    if not file_path.exists():
        raise SourceError(f"Input file not found: {file_path}")

    try:
        input_hash = sha256_file(file_path)
    except OSError as exc:
        raise SourceError(f"Cannot read input file: {file_path}") from exc

    llm_profile_name = _resolve_llm_execution_profile(analysis_cfg)

    try:
        contract = analysis_contract(
            getattr(ctx, "shared_control", None) if ctx is not None else None,
            getattr(analysis_cfg, "contract", None),
        )
    except (ConfigError, AIConfigurationError) as exc:
        raise ConfigurationError(
            f"Cannot read analysis contract "
            f"'{getattr(analysis_cfg, 'contract', None)}': {exc}"
        ) from exc
    contract_hash = contract.hash

    output_schema = contract.spec.output_schema
    schema_hash = (
        sha256_text(json.dumps(output_schema, sort_keys=True)) if output_schema else ""
    )

    request_id = _compute_request_id(input_hash, contract_hash, schema_hash)

    return AnalysisRequest(
        request_id       = request_id,
        run_id           = str(uuid.uuid4()),
        source_name      = source_cfg.name,
        analysis_name    = analysis_cfg.name,
        file_path        = file_path,
        input_hash       = input_hash,
        contract         = contract,
        contract_hash    = contract_hash,
        schema_hash      = schema_hash,
        llm_profile_name = llm_profile_name,
        idempotency_mode = getattr(analysis_cfg, "idempotency_mode", "reuse_success"),
        requires_approval = bool(getattr(analysis_cfg, "requires_approval", False)),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_request_id(
    input_hash:    str,
    contract_hash: str,
    schema_hash:   str,
) -> str:
    """Return a 16-char deterministic ID from three content hashes."""
    combined = f"{input_hash}:{contract_hash}:{schema_hash}"
    return sha256_bytes(combined.encode())[:16]


def _resolve_llm_execution_profile(analysis_cfg: Any) -> str:
    """Return the named LLM execution profile for an analysis config."""
    has_current = hasattr(analysis_cfg, "llm_execution_profile")
    has_legacy = hasattr(analysis_cfg, "llm_profile")
    name = getattr(analysis_cfg, "name", "<unknown>")

    if has_current and has_legacy:
        raise ConfigurationError(
            f"Invalid analysis config '{name}': both 'llm_execution_profile' "
            "and legacy 'llm_profile' are present. Use only "
            "'llm_execution_profile'."
        )

    if has_current:
        profile = getattr(analysis_cfg, "llm_execution_profile")
    elif has_legacy:
        profile = getattr(analysis_cfg, "llm_profile")
    else:
        raise ConfigurationError(
            f"Invalid analysis config '{name}': missing required "
            "'llm_execution_profile'."
        )

    if not str(profile or "").strip():
        raise ConfigurationError(
            f"Invalid analysis config '{name}': 'llm_execution_profile' "
            "must not be empty."
        )

    return str(profile)


def _hash_bytes(data: bytes) -> str:
    """Return the shared SHA-256 hex digest for raw bytes."""
    return sha256_bytes(data)
