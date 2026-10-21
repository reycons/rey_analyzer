"""
rey_analyzer — entry point.

Contract-driven LLM analysis runs as a governed Workflow step (the ``analysis``
operation, rey_analyzer.workflow); its data source is the Workflow's (backlog
1032). The run, run-source, submit-file, analyze-file and build-payload commands
that resolved a data source from the context are retired. This entry point keeps
the review commands over persisted run records.

Usage
-----
    python main.py --config-path /path/to/configs/v01/config.yaml status --run-id <run_id>
    python main.py --config-path /path/to/configs/v01/config.yaml approve --run-id <run_id>
    python main.py --config-path /path/to/configs/v01/config.yaml reject --run-id <run_id>
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Pre-parse --config-path / --config-dir and call load_dotenv before other imports.
from rey_lib.config.cli import preparse_config_args
preparse_config_args()

from rey_lib.config.cli import add_config_args, apply_env_overrides, build_ctx_from_args
from rey_lib.config.bootstrap import app_runtime
from rey_lib.logs import (
    AppLogger,
)
from rey_lib.run_lifecycle import run_app_operation
from rey_lib.logs import finalize_run_log

from rey_analyzer.error_utils import ConfigurationError


__all__: list[str] = []

_PROJECT_ROOT = Path(__file__).parent
APP_NAME = "rey_analyzer"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Parse CLI arguments, build ctx, and dispatch to the requested command."""
    args = _parse_args()
    apply_env_overrides(args.env_overrides)

    ctx = build_ctx_from_args(args, app_name=APP_NAME)

    object.__setattr__(ctx, "batch_start_dt", datetime.now())
    object.__setattr__(ctx, "cli_call", " ".join(sys.argv))

    # app_runtime is the process boundary: it composes the context and,
    # when this block exits, collects the shared runtime objects it
    # created. It encloses everything below, so any existing finalization
    # runs while those objects are still live and collection happens after.
    with app_runtime(ctx=ctx, operation=args.command, on_terminate="ABORTED") as (ctx, run_log):
        log = AppLogger(__name__)
        log.info("rey_analyzer starting — command=%s", args.command)

        # A failure propagates as its own AppError; app_runtime normalises
        # anything else and reports it once (rule 79).
        try:
            return run_app_operation(
                ctx,
                run_log, str(args.command),
                lambda: _execute_command(ctx, run_log, args, log),
            )

        finally:
            # The top-level owner explicitly creates the RESULTS_SUMMARY after its
            # final RUN_COMPLETE — on success or failure
            # (SGC_Rey_Lib_Explicit_Results_Summary_Creation).
            finalize_run_log(run_log, ai=getattr(ctx, "shared_ai", None))


def _execute_command(ctx: Any, run_log, args: argparse.Namespace, log: Any) -> int:
    """Execute the selected analyzer command body."""
    if args.command == "status":
        _cmd_status(ctx, args, log)

    elif args.command == "approve":
        _cmd_approve(ctx, args, log)

    elif args.command == "reject":
        _cmd_reject(ctx, args, log)

    log.info("rey_analyzer complete.")
    return 0


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_status(ctx: Any, args: argparse.Namespace, log: Any) -> None:
    """Print the status of a past run by run_id."""
    from rey_lib.analysis import load_latest_record  # noqa: PLC0415

    records_path = Path(ctx.app.records_path).expanduser().resolve()
    record = load_latest_record(records_path, args.run_id)
    if record is None:
        log.warning("No record found for run_id=%s", args.run_id)
        return
    log.info("run_id=%s status=%s", args.run_id, record.status)


def _cmd_approve(ctx: Any, args: argparse.Namespace, log: Any) -> None:
    """Approve a pending-approval run and move its file to success."""
    from rey_lib.analysis import approve, load_latest_record, store_record  # noqa: PLC0415

    records_path = Path(ctx.app.records_path).expanduser().resolve()
    record = load_latest_record(records_path, args.run_id)
    if record is None:
        raise ConfigurationError(f"No record found for run_id={args.run_id}")

    updated = approve(record, reviewer=getattr(args, "reviewer", ""), comments="")
    store_record(records_path, updated)
    log.info("approved run_id=%s", args.run_id)


def _cmd_reject(ctx: Any, args: argparse.Namespace, log: Any) -> None:
    """Reject a pending-approval run and move its file to failed."""
    from rey_lib.analysis import load_latest_record, reject, store_record  # noqa: PLC0415

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
