"""Tests for rey_analyzer.requests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from rey_analyzer.error_utils import ConfigurationError, SourceError
from rey_analyzer.requests import _compute_request_id, _hash_bytes, build_request


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
    """build_request raises ConfigurationError when contract path is invalid."""
    bad_cfg = SimpleNamespace(
        name              = "bad",
        contract          = "contracts/nonexistent/v01.md",
        llm_profile       = "primary",
        idempotency_mode  = "reuse_success",
        requires_approval = False,
        schema            = None,
    )
    with pytest.raises(ConfigurationError):
        build_request(sample_source_cfg, bad_cfg, sample_jsonl_file)


def test_build_request_no_contract_field_raises_config_error(
    sample_source_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
) -> None:
    """build_request raises ConfigurationError when analysis_cfg has no contract."""
    cfg = SimpleNamespace(
        name              = "bad",
        contract          = None,
        llm_profile       = "primary",
        idempotency_mode  = "reuse_success",
        requires_approval = False,
        schema            = None,
    )
    with pytest.raises(ConfigurationError):
        build_request(sample_source_cfg, cfg, sample_jsonl_file)
