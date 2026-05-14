"""
Application exception hierarchy for rey_analyzer.

All errors raised within rey_analyzer are instances of AnalyzerError or one
of its subclasses. Callers catch AnalyzerError to handle all app-level
failures uniformly, or catch a specific subclass for targeted handling.

Public API
----------
AnalyzerError        Base for all rey_analyzer errors.
ConfigurationError   Missing or invalid configuration.
SourceError          File not found, unreadable, or unsupported input type.
AnalysisError        LLM execution, schema validation, or contract failure.
FileMovementError    File move or discovery failure.
IdempotencyError     Raised when idempotency_mode is fail_if_exists and a
                     prior successful result already exists.
ApprovalError        Approve or reject called on a record in the wrong status.
"""

from __future__ import annotations

from rey_lib.errors.error_utils import AppError

__all__ = [
    "AnalyzerError",
    "ConfigurationError",
    "SourceError",
    "AnalysisError",
    "FileMovementError",
    "IdempotencyError",
    "ApprovalError",
]


class AnalyzerError(AppError):
    """Base exception for all rey_analyzer errors."""


class ConfigurationError(AnalyzerError):
    """Raised when required configuration is missing or invalid."""


class SourceError(AnalyzerError):
    """Raised when an input file cannot be found, read, or interpreted."""


class AnalysisError(AnalyzerError):
    """Raised when the LLM call, schema validation, or contract fails."""


class FileMovementError(AnalyzerError):
    """Raised when a file cannot be moved between pipeline stages."""


class IdempotencyError(AnalyzerError):
    """Raised when idempotency_mode is fail_if_exists and a result exists."""


class ApprovalError(AnalyzerError):
    """Raised when approve or reject is called on a record in the wrong status."""
