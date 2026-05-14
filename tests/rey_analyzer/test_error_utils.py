"""Tests for rey_analyzer.error_utils."""

from __future__ import annotations

import pytest

from rey_lib.errors.error_utils import AppError

from rey_analyzer.error_utils import (
    AnalysisError,
    AnalyzerError,
    ApprovalError,
    ConfigurationError,
    FileMovementError,
    IdempotencyError,
    SourceError,
)


def test_all_subclass_analyzer_error() -> None:
    """Every app error is a subtype of AnalyzerError."""
    for cls in (
        ConfigurationError,
        SourceError,
        AnalysisError,
        FileMovementError,
        IdempotencyError,
        ApprovalError,
    ):
        assert issubclass(cls, AnalyzerError)


def test_analyzer_error_subclasses_app_error() -> None:
    """AnalyzerError chains up to rey_lib AppError."""
    assert issubclass(AnalyzerError, AppError)


def test_raise_and_catch_as_base() -> None:
    """Specific errors can be caught as AnalyzerError."""
    with pytest.raises(AnalyzerError):
        raise ConfigurationError("bad config")


def test_exception_message_preserved() -> None:
    """Error message is accessible on the instance."""
    exc = SourceError("file not found")
    assert "file not found" in str(exc)
