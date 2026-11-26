"""Operator commands.

    python -m app.cli claim-legacy-cases EMAIL [--dry-run]

Gives every case that has NO members (created before authentication existed) to the
existing account with this e-mail address, as owner. Cases with any member are never
changed. Nothing is deleted; each claim is recorded in the case's audit chain.
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    claim = sub.add_parser("claim-legacy-cases", help="own all cases that have no members")
    claim.add_argument("email")
    claim.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "claim-legacy-cases":
        return claim_legacy_cases(args.email, args.dry_run)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
