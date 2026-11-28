"""Operator commands.

    python -m app.cli claim-legacy-cases EMAIL [--dry-run]

Gives every case that has NO members (created before authentication existed) to the
existing account with this e-mail address, as owner. Cases with any member are never
changed. Nothing is deleted; each claim is recorded in the case's audit chain.

    python -m app.cli seed-demo --owner EMAIL [--viewer EMAIL ...] [--dry-run | --yes]

Creates the fictional Missing Shipment demo case once (see app/demo_seed.py), using
the configured database and evidence storage. Re-running it changes nothing.

    python -m app.cli worker [--dry-run | --once] [--poll-seconds N] [...]

Processes OCR, speech and video evidence (and scanned PDFs) of the configured database
and storage on this computer, for a deployment that cannot (see app/worker.py and
docs/PROCESSING_WORKER.md). --dry-run lists candidates without changing anything.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.modules.auth.models import CaseMember, User
from app.modules.cases.models import Case


def claim_legacy_cases(email: str, dry_run: bool = False) -> int:
    from app.modules.auth.service import AuthService

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            print(f"No account uses {email!r}. Register it first.", file=sys.stderr)
            return 2
        owned = select(CaseMember.case_id)
        ownerless = list(db.scalars(select(Case.title).where(Case.id.not_in(owned))))
        print(f"{len(ownerless)} case(s) without members:")
        for title in ownerless:
            print(f"  - {title}")
        if dry_run or not ownerless:
            print("Nothing changed." if not ownerless else "Dry run: nothing changed.")
            return 0
        n = AuthService(db).claim_legacy_cases(user, "claimed by the operator (app.cli)")
        db.commit()
        print(f"{n} case(s) now owned by {user.display_name} <{user.email}>.")
        return 0


def _describe_target(settings) -> str:  # noqa: ANN001
    """Where the command will write, without credentials or hosts."""
    dialect = settings.database_url.split(":", 1)[0]
    storage = (
        f"s3 bucket {settings.s3_bucket!r}"
        if settings.storage_backend == "s3"
        else f"local folder {settings.storage_root!r}"
    )
    return f"database: {dialect}; evidence storage: {storage}"


def seed_demo(args: argparse.Namespace) -> int:
    from pathlib import Path

    from app.core.config import get_settings
    from app.demo_seed import DEMO_DIR, DEMO_TITLE, SeedError, seed_demo_case

    settings = get_settings()
    print(_describe_target(settings))
    if not args.dry_run and not args.yes:
        print("Refusing to write without --yes. Run with --dry-run first.", file=sys.stderr)
        return 2
    try:
        result = seed_demo_case(
            session_factory=SessionLocal,
            settings=settings,
            owner_email=args.owner,
            viewer_emails=args.viewer,
            title=args.title or DEMO_TITLE,
            demo_dir=Path(args.demo_dir) if args.demo_dir else DEMO_DIR,
            dry_run=args.dry_run,
            process=not args.skip_processing,
        )
    except SeedError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if result.status == "exists":
        print(f"The demo case already exists ({result.case_id}). Nothing changed.")
        return 0
    if result.status == "dry-run":
        print("Dry run: nothing changed. Would upload: " + ", ".join(result.files))
        if result.viewers:
            print("Would add viewers: " + ", ".join(result.viewers))
        return 0
    print(f"Created demo case {result.case_id}.")
    for name, status in result.files.items():
        code = result.errors.get(name)
        print(f"  {name}: {status}" + (f" ({code})" if code else ""))
    if result.viewers:
        print("Viewers added: " + ", ".join(result.viewers))
    if result.analysis:
        print("Analysis: " + ", ".join(f"{k}={v}" for k, v in result.analysis.items()))
    print(
        "Next: sign in as the owner, confirm the proposed event under Events if you agree "
        "with it, then generate the reports."
    )
    return 0


def _worker_refusal(settings, heartbeat_seconds: float, allow_local_storage: bool) -> str | None:  # noqa: ANN001
    """Why the worker must not write with this configuration (None = fine)."""
    from app.storage.factory import missing_s3_settings

    if settings.storage_backend == "s3":
        missing = missing_s3_settings(settings)
        if missing:
            return "STORAGE_BACKEND=s3 requires " + ", ".join(missing) + " to be set."
    elif settings.database_url.startswith("postgresql") and not allow_local_storage:
        # A shared PostgreSQL database with local storage would find none of the
        # deployment's files and mark real evidence failed (storage_missing).
        return (
            "DATABASE_URL is PostgreSQL but STORAGE_BACKEND is local. Set STORAGE_BACKEND=s3 "
            "and the S3_* variables of the deployment's bucket (or pass "
            "--allow-local-storage if this database really uses local storage)."
        )
    stale_seconds = settings.processing_stale_minutes * 60
    if heartbeat_seconds * 2 > stale_seconds:
        return (
            f"--heartbeat-seconds {heartbeat_seconds:g} is too long for "
            f"PROCESSING_STALE_MINUTES={settings.processing_stale_minutes}; use at most "
            f"{stale_seconds / 2:g} seconds."
        )
    return None


def run_worker(args: argparse.Namespace) -> int:
    import threading

    from app.core.config import get_settings
    from app.modules.processing.registry import get_registry
    from app.worker import (
        DEFAULT_LOCK_FILE,
        PDF_MIME,
        ProcessingWorker,
        WorkerLock,
        WorkerLockError,
        cases_needing_analysis,
        describe_pass,
        engine_report,
        find_candidates,
        install_stop_handlers,
        worker_mime_types,
    )

    settings = get_settings()
    print(_describe_target(settings))
    for line in engine_report(settings):
        print(f"  {line}")
    print("  file types: " + ", ".join(sorted(worker_mime_types(settings))))
    if settings.processing_isolation != "subprocess":
        print(
            "  warning: PROCESSING_ISOLATION is not 'subprocess'; PDF and video files then "
            "run without the per-item timeout.",
            file=sys.stderr,
        )

    if args.dry_run:
        found = find_candidates(
            SessionLocal,
            settings,
            include_scanned_pdfs=not args.no_scanned_pdfs,
            pdf_supported=get_registry().supports(PDF_MIME),
            retry_failed=args.retry_failed,
        )
        print(f"{len(found)} eligible item(s):")
        for c in found:
            print(f"  {c.filename} ({c.mime_type}, case {c.case_id}): {c.reason}")
        if not args.no_analysis:
            due = cases_needing_analysis(
                SessionLocal, settings, include_scanned_pdfs=not args.no_scanned_pdfs
            )
            print(f"{len(due)} case(s) already processed but not analysed since.")
        print("Dry run: nothing was claimed or changed.")
        return 0

    problem = _worker_refusal(settings, args.heartbeat_seconds, args.allow_local_storage)
    if problem:
        print(problem, file=sys.stderr)
        return 2

    lock = WorkerLock(args.lock_file or DEFAULT_LOCK_FILE)
    try:
        lock.acquire()
    except WorkerLockError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    from app.modules.analysis.runner import AnalysisRunner
    from app.modules.processing.executor import build_executor
    from app.storage.factory import build_storage

    stop = threading.Event()
    restore = install_stop_handlers(stop, print)
    try:
        worker = ProcessingWorker(
            session_factory=SessionLocal,
            settings=settings,
            storage=build_storage(settings),
            registry=get_registry(),
            executor=build_executor(settings),
            analysis_runner=AnalysisRunner(session_factory=SessionLocal, settings=settings),
            analyse=not args.no_analysis,
            include_scanned_pdfs=not args.no_scanned_pdfs,
            retry_failed=args.retry_failed,
            heartbeat_seconds=args.heartbeat_seconds,
            stop=stop,
            emit=print,
        )
        if args.once:
            print(describe_pass(worker.run_pass(), continuous=False))
        else:
            print(f"Polling every {args.poll_seconds:g} s. Press Ctrl+C to stop.")
            worker.run_forever(args.poll_seconds)
        print("Worker stopped.")
        return 0
    except KeyboardInterrupt:
        print(
            "Stopped immediately. An item that was being processed stays 'processing' and "
            "is picked up again after PROCESSING_STALE_MINUTES.",
            file=sys.stderr,
        )
        return 130
    finally:
        restore()
        lock.release()


def _poll_seconds(value: str) -> float:
    seconds = float(value)
    if seconds < 5:
        raise argparse.ArgumentTypeError("must be at least 5 seconds")
    return seconds


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    claim = sub.add_parser("claim-legacy-cases", help="own all cases that have no members")
    claim.add_argument("email")
    claim.add_argument("--dry-run", action="store_true")
    seed = sub.add_parser(
        "seed-demo", help="create the fictional Missing Shipment demo case (once)"
    )
    seed.add_argument("--owner", required=True, help="e-mail of an existing account")
    seed.add_argument(
        "--viewer",
        action="append",
        default=[],
        help="e-mail of an existing account to add as viewer (repeatable)",
    )
    seed.add_argument("--title", default=None)
    seed.add_argument(
        "--demo-dir", default=None, help="folder with the demo files (default: sample-evidence/...)"
    )
    seed.add_argument(
        "--skip-processing",
        action="store_true",
        help="upload only; process and analyse later in the web app",
    )
    seed.add_argument("--dry-run", action="store_true")
    seed.add_argument("--yes", action="store_true", help="confirm writing to the target")
    worker = sub.add_parser(
        "worker",
        help="process OCR, speech and video evidence for a deployment that cannot",
    )
    mode = worker.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="list eligible evidence; claim and change nothing"
    )
    mode.add_argument("--once", action="store_true", help="process one polling pass, then exit")
    worker.add_argument(
        "--poll-seconds",
        type=_poll_seconds,
        default=30.0,
        help="seconds between polling passes when running continuously (default 30, min 5)",
    )
    worker.add_argument(
        "--heartbeat-seconds",
        type=_positive_seconds,
        default=60.0,
        help="how often a running item's claim is refreshed (default 60)",
    )
    worker.add_argument(
        "--retry-failed",
        action="store_true",
        help=(
            "also retry worker file types that failed for reasons other than a missing "
            "engine or an interruption (those are always retried)"
        ),
    )
    worker.add_argument(
        "--no-scanned-pdfs", action="store_true", help="do not re-run OCR for scanned PDFs"
    )
    worker.add_argument(
        "--no-analysis", action="store_true", help="do not analyse cases after processing"
    )
    worker.add_argument("--lock-file", default=None, help="lock file (default: in the temp folder)")
    worker.add_argument(
        "--allow-local-storage",
        action="store_true",
        help="allow a PostgreSQL database with STORAGE_BACKEND=local",
    )
    args = parser.parse_args(argv)
    if args.command == "claim-legacy-cases":
        return claim_legacy_cases(args.email, args.dry_run)
    if args.command == "seed-demo":
        return seed_demo(args)
    if args.command == "worker":
        return run_worker(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
