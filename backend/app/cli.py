"""Operator commands.

    python -m app.cli claim-legacy-cases EMAIL [--dry-run]

Gives every case that has NO members (created before authentication existed) to the
existing account with this e-mail address, as owner. Cases with any member are never
changed. Nothing is deleted; each claim is recorded in the case's audit chain.

    python -m app.cli seed-demo --owner EMAIL [--viewer EMAIL ...] [--dry-run | --yes]

Creates the fictional Missing Shipment demo case once (see app/demo_seed.py), using
the configured database and evidence storage. Re-running it changes nothing.
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
    args = parser.parse_args(argv)
    if args.command == "claim-legacy-cases":
        return claim_legacy_cases(args.email, args.dry_run)
    if args.command == "seed-demo":
        return seed_demo(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
