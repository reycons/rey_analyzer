"""
rey_analyzer — entry point.

Configurable assembly-line application for contract-driven LLM analysis.
Consumes files from configured inbox folders, runs them through analysis
contracts via rey_lib.llm, writes result artifacts, and moves files to
final folders.

Usage
-----
    python main.py --env dev run
    python main.py --env dev run-source rey_loader_logs
    python main.py --env dev submit-file --source rey_loader_logs --file /path/file.jsonl
    python main.py --env dev analyze-file --source rey_loader_logs --file /path/file.jsonl
    python main.py --env dev status --run-id <run_id>
    python main.py --env dev approve --run-id <run_id>
    python main.py --env dev reject --run-id <run_id>
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Pre-parse --config-path / --config-dir and call load_dotenv before other imports.
from rey_lib.config.cli import preparse_config_args
preparse_config_args()

from rey_lib.config.bootstrap import build_ctx_for_app
from rey_lib.config.cli import add_config_args, apply_env_overrides
from rey_lib.config.config_utils import build_ctx
from rey_lib.config.ctx import find_in_ctx
from rey_lib.errors.error_utils import AppError, handle_exception
from rey_lib.logs import get_logger, setup_logging

from rey_analyzer.error_utils import AnalyzerError, ConfigurationError
from rey_analyzer.runner import run_all, run_analysis, run_source

__all__: list[str] = []

_PROJECT_ROOT = Path(__file__).parent
_VALID_ENVS   = frozenset({"dev", "prod"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Parse CLI arguments, build ctx, and dispatch to the requested command."""
    args = _parse_args()
    apply_env_overrides(args.env_overrides)

    if args.config_path:
        ctx = build_ctx_for_app(
            installation_config_path=Path(args.config_path),
            app_name="rey_analyzer",
            project_root=_PROJECT_ROOT,
        )
    else:
        if not args.env:
            raise SystemExit("--env is required when --config-path is not provided.")
        config_dir = Path(args.config_dir).expanduser().resolve() if args.config_dir else None
        ctx = build_ctx(env=args.env, project_root=_PROJECT_ROOT, config_dir=config_dir)

    object.__setattr__(ctx, "batch_start_dt", datetime.now())
    object.__setattr__(ctx, "cli_call", " ".join(sys.argv))

    setup_logging(ctx, operation=args.command)
    log = get_logger(__name__)
    log.info("rey_analyzer starting — env=%s command=%s", ctx.env, args.command)

    try:
        if args.command == "run":
            success, failed, pending = run_all(ctx)
            log.info(
                "run complete: success=%d failed=%d pending=%d",
                success, failed, pending,
            )
            if failed:
                log.error("rey_analyzer run failed: %d file(s) failed.", failed)
                return 1

        elif args.command == "run-source":
            source_cfg   = _resolve_source(ctx, args.source)
            analysis_cfg = _resolve_analysis(ctx, source_cfg.analysis_config)
            success, failed, pending = run_source(ctx, source_cfg, analysis_cfg)
            log.info(
                "run-source complete: success=%d failed=%d pending=%d",
                success, failed, pending,
            )
            if failed:
                log.error("run-source failed: %d file(s) failed.", failed)
                return 1

        elif args.command == "submit-file":
            source_cfg   = _resolve_source(ctx, args.source)
            analysis_cfg = _resolve_analysis(ctx, source_cfg.analysis_config)
            file_path    = Path(args.file).expanduser().resolve()
            status       = run_analysis(ctx, source_cfg, analysis_cfg, file_path)
            log.info("submit-file complete: status=%s", status)
            if status == "failed":
                return 1

        elif args.command == "analyze-file":
            # analyze-file runs the analysis without moving the file.
            source_cfg   = _resolve_source(ctx, args.source)
            analysis_cfg = _resolve_analysis(ctx, source_cfg.analysis_config)
            file_path    = Path(args.file).expanduser().resolve()
            status       = run_analysis(
                ctx, source_cfg, analysis_cfg, file_path,
            )
            log.info("analyze-file complete: status=%s", status)
            if status == "failed":
                return 1

        elif args.command == "status":
            _cmd_status(ctx, args, log)

        elif args.command == "approve":
            _cmd_approve(ctx, args, log)

        elif args.command == "reject":
            _cmd_reject(ctx, args, log)

        log.info("rey_analyzer complete.")
        return 0

    except (AnalyzerError, AppError) as exc:
        handle_exception(log, exc, "rey_analyzer error")
        return 1

    except Exception as exc:  # noqa: BLE001  — top-level safety net only
        handle_exception(log, exc, "Unexpected error in rey_analyzer")
        return 2


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_status(ctx: Any, args: argparse.Namespace, log: Any) -> None:
    """Print the status of a past run by run_id."""
    from rey_lib.llm.records import load_latest_record  # noqa: PLC0415

    records_path = Path(ctx.app.records_path).expanduser().resolve()
    record = load_latest_record(records_path, args.run_id)
    if record is None:
        log.warning("No record found for run_id=%s", args.run_id)
        return
    log.info("run_id=%s status=%s", args.run_id, record.status)


def _cmd_approve(ctx: Any, args: argparse.Namespace, log: Any) -> None:
    """Approve a pending-approval run and move its file to success."""
    from rey_lib.llm.records import approve, load_latest_record, store_record  # noqa: PLC0415

    records_path = Path(ctx.app.records_path).expanduser().resolve()
    record = load_latest_record(records_path, args.run_id)
    if record is None:
        raise ConfigurationError(f"No record found for run_id={args.run_id}")

    updated = approve(record, reviewer=getattr(args, "reviewer", ""), comments="")
    store_record(records_path, updated)
    log.info("approved run_id=%s", args.run_id)


def _cmd_reject(ctx: Any, args: argparse.Namespace, log: Any) -> None:
    """Reject a pending-approval run and move its file to failed."""
    from rey_lib.llm.records import load_latest_record, reject, store_record  # noqa: PLC0415

    records_path = Path(ctx.app.records_path).expanduser().resolve()
    record = load_latest_record(records_path, args.run_id)
    if record is None:
        raise ConfigurationError(f"No record found for run_id={args.run_id}")

    updated = reject(record, reviewer=getattr(args, "reviewer", ""), comments="")
    store_record(records_path, updated)
    log.info("rejected run_id=%s", args.run_id)


# ---------------------------------------------------------------------------
# Config resolution helpers
# ---------------------------------------------------------------------------

def _resolve_source(ctx: Any, name: str) -> Any:
    """Look up a data source config by name or raise ConfigurationError."""
    cfg = find_in_ctx(ctx, "data_sources", name)
    if cfg is None:
        raise ConfigurationError(
            f"data_source '{name}' not found. "
            f"Check config/data_sources/."
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
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Build the argument parser with all supported subcommands."""
    parser = argparse.ArgumentParser(
        description="rey_analyzer — contract-driven analysis orchestrator"
    )
    add_config_args(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Process all enabled data sources.")

    p_source = sub.add_parser("run-source", help="Process one named data source.")
    p_source.add_argument("--source", required=True, dest="source", help="Data source name.")

    p_submit = sub.add_parser("submit-file", help="Submit one file for analysis.")
    p_submit.add_argument("--source", required=True, help="Data source name.")
    p_submit.add_argument("--file",   required=True, help="Path to the file.")

    p_analyze = sub.add_parser("analyze-file", help="Analyze one file without moving it.")
    p_analyze.add_argument("--source", required=True, help="Data source name.")
    p_analyze.add_argument("--file",   required=True, help="Path to the file.")

    p_status = sub.add_parser("status", help="Print status of a past run.")
    p_status.add_argument("--run-id", required=True, dest="run_id", help="Run ID.")

    p_approve = sub.add_parser("approve", help="Approve a pending-approval run.")
    p_approve.add_argument("--run-id",   required=True, dest="run_id")
    p_approve.add_argument("--reviewer", default="")

    p_reject = sub.add_parser("reject", help="Reject a pending-approval run.")
    p_reject.add_argument("--run-id",   required=True, dest="run_id")
    p_reject.add_argument("--reviewer", default="")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Type hint stub — Any imported at module level would pull in typing
# ---------------------------------------------------------------------------
from typing import Any  # noqa: E402 — placed here to avoid circular import risk


if __name__ == "__main__":
    sys.exit(main())
