"""Tests for rey_analyzer.requests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import rey_analyzer.requests as requests_mod
from rey_analyzer.error_utils import ConfigurationError, SourceError
from rey_analyzer.requests import _compute_request_id, _hash_bytes, build_request



class _Control:
    """The runtime's Control, answering get_analysis_contract from a mapping."""

    installation_id = 7

    def __init__(self, rows: dict | None = None) -> None:
        self.rows = rows or {}

    def analysis_contract(self, name: str) -> dict | None:
        return self.rows.get(name)


def _stored(name: str) -> SimpleNamespace:
    """What the seam answers: a parsed contract with no output schema."""
    return SimpleNamespace(name=name, hash="contract_hash",
                           spec=SimpleNamespace(output_schema=None))


_CTX = SimpleNamespace(shared_control=_Control())


def test_hash_bytes_is_sha256_hex(tmp_path: Path) -> None:
    """_hash_bytes returns a 64-char hex string."""
    data = b"hello"
    result = _hash_bytes(data)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_bytes_deterministic(tmp_path: Path) -> None:
    """Same bytes always produce the same hash."""
    assert _hash_bytes(b"test") == _hash_bytes(b"test")


def test_compute_request_id_is_16_chars() -> None:
    """request_id is 16 hex chars."""
    rid = _compute_request_id("aaa", "bbb", "ccc")
    assert len(rid) == 16
    assert all(c in "0123456789abcdef" for c in rid)


def test_compute_request_id_deterministic() -> None:
    """Same inputs always produce the same request_id."""
    a = _compute_request_id("x", "y", "z")
    b = _compute_request_id("x", "y", "z")
    assert a == b


def test_compute_request_id_differs_on_different_inputs() -> None:
    """Different inputs produce different request_ids."""
    assert _compute_request_id("a", "b", "c") != _compute_request_id("x", "y", "z")


def test_build_request_missing_file_raises_source_error(
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    tmp_path: Path,
) -> None:
    """build_request raises SourceError when the file does not exist."""
    with pytest.raises(SourceError):
        build_request(sample_source_cfg, sample_analysis_cfg, tmp_path / "missing.jsonl")


def test_build_request_missing_contract_raises_config_error(
    sample_source_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
    tmp_path: Path,
) -> None:
    """build_request raises ConfigurationError when no contract has that name."""
    bad_cfg = SimpleNamespace(
        name              = "bad",
        contract          = "nonexistent",
        llm_execution_profile = "primary",
        idempotency_mode  = "reuse_success",
        requires_approval = False,
        schema            = None,
    )
    with pytest.raises(ConfigurationError):
        build_request(
            sample_source_cfg,
            bad_cfg,
            sample_jsonl_file,
            ctx=_CTX,
        )


def test_build_request_no_contract_field_raises_config_error(
    sample_source_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
) -> None:
    """build_request raises ConfigurationError when analysis_cfg has no contract."""
    cfg = SimpleNamespace(
        name              = "bad",
        contract          = None,
        llm_execution_profile = "primary",
        idempotency_mode  = "reuse_success",
        requires_approval = False,
        schema            = None,
    )
    with pytest.raises(ConfigurationError):
        build_request(
            sample_source_cfg,
            cfg,
            sample_jsonl_file,
            ctx=_CTX,
        )


def test_build_request_uses_llm_execution_profile(
    monkeypatch: pytest.MonkeyPatch,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
) -> None:
    """build_request reads the canonical llm_execution_profile field."""
    monkeypatch.setattr(
        requests_mod,
        "analysis_contract",
        lambda control, name: _stored(name),
    )

    req = build_request(
        sample_source_cfg,
        sample_analysis_cfg,
        sample_jsonl_file,
        ctx=_CTX,
    )

    assert req.llm_profile_name == "primary"


def test_build_request_accepts_legacy_llm_profile(
    monkeypatch: pytest.MonkeyPatch,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
) -> None:
    """build_request temporarily accepts legacy llm_profile for compatibility."""
    monkeypatch.setattr(
        requests_mod,
        "analysis_contract",
        lambda control, name: _stored(name),
    )
    legacy_cfg = SimpleNamespace(**vars(sample_analysis_cfg))
    delattr(legacy_cfg, "llm_execution_profile")
    legacy_cfg.llm_profile = "legacy_primary"

    req = build_request(
        sample_source_cfg,
        legacy_cfg,
        sample_jsonl_file,
        ctx=_CTX,
    )

    assert req.llm_profile_name == "legacy_primary"


def test_build_request_rejects_both_execution_profile_fields(
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
) -> None:
    """build_request fails closed when canonical and legacy fields both exist."""
    bad_cfg = SimpleNamespace(**vars(sample_analysis_cfg))
    bad_cfg.llm_profile = "legacy_primary"

    with pytest.raises(ConfigurationError, match="both 'llm_execution_profile'"):
        build_request(
            sample_source_cfg,
            bad_cfg,
            sample_jsonl_file,
            ctx=_CTX,
        )


def test_build_request_requires_execution_profile(
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
) -> None:
    """build_request fails closed when no LLM execution profile is configured."""
    bad_cfg = SimpleNamespace(**vars(sample_analysis_cfg))
    delattr(bad_cfg, "llm_execution_profile")

    with pytest.raises(ConfigurationError, match="missing required 'llm_execution_profile'"):
        build_request(
            sample_source_cfg,
            bad_cfg,
            sample_jsonl_file,
            ctx=_CTX,
        )


def test_a_runtime_without_a_control_database_has_no_contract(
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
) -> None:
    """The contract is read from control.analysis_contract; there is no file fallback."""
    with pytest.raises(ConfigurationError, match="control database"):
        build_request(
            sample_source_cfg,
            sample_analysis_cfg,
            sample_jsonl_file,
            ctx=SimpleNamespace(),
        )
