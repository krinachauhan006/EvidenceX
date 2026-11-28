"""Seed the fictional "Missing Shipment" demonstration case, once, on request.

Run by an operator with ``python -m app.cli seed-demo`` (never on start-up). It goes
through the same services as the web app, so every file is validated by content,
stored under its SHA-256 in the CONFIGURED storage backend (local folder or S3
bucket), processed by the real extractors and analysed by the real rules:

1. the owner account must already exist (register it in the web app first);
2. a case with the same title owned by that account is left untouched (safe to re-run);
3. the case is created and owned by that account, exactly as "New investigation" does;
4. the six files in ``sample-evidence/demo-missing-shipment/`` are uploaded;
5. optional viewer accounts (for judges) are added with the read-only viewer role;
6. processing and one rule-based analysis run, unless ``--skip-processing`` is given.

Nothing is invented: the result reported is what the extractors and rules produced on
this machine. Review decisions (confirming the proposed event, generating reports) are
left to a person, as in normal use.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
# A byte-identical copy of sample-evidence/demo-missing-shipment, inside the backend
# package, so a deployment whose root is backend/ (Vercel) ships the files too. A test
# keeps the two copies identical.
BUNDLED_DEMO_DIR = Path(__file__).resolve().parent / "demo_assets" / "missing_shipment"
REPO_DEMO_DIR = BACKEND_DIR.parent / "sample-evidence" / "demo-missing-shipment"
DEMO_DIR = BUNDLED_DEMO_DIR if BUNDLED_DEMO_DIR.is_dir() else REPO_DEMO_DIR
# Audit action that marks a case as the user's copy of the demo (survives a rename).
DEMO_MARKER_ACTION = "demo_case_created"
DEMO_TITLE = "Missing pallet shipment (demo)"
DEMO_DESCRIPTION = (
    "Fictional demonstration case built from sample-evidence/demo-missing-shipment. "
    "All names, plates, companies and times are invented; this is not real evidence."
)
# Fixed manifest: only these files are uploaded, never whatever happens to be in the folder.
DEMO_FILES = (
    "delivery_receipt.pdf",
    "gate_log_photo.png",
    "dock_camera.mp4",
    "driver_call.wav",
    "pallet_ledger.csv",
    "witness_email.eml",
)

SessionFactory = Callable[[], AbstractContextManager[Session]]


class SeedError(RuntimeError):
    """The demo case cannot be seeded; nothing was changed."""


@dataclass
class SeedResult:
    status: str  # "created" | "exists" | "dry-run"
    case_id: uuid.UUID | None = None
    files: dict[str, str] = field(default_factory=dict)  # name -> processing status
    errors: dict[str, str] = field(default_factory=dict)  # name -> error code
    viewers: list[str] = field(default_factory=list)
    analysis: dict[str, int] = field(default_factory=dict)


def _user(db: Session, email: str):  # noqa: ANN202
    from app.modules.auth.models import User

    return db.scalar(select(User).where(User.email == email.strip().lower()))


def _existing_case(db: Session, owner_id: uuid.UUID, title: str) -> uuid.UUID | None:
    from app.modules.auth.models import CaseMember
    from app.modules.cases.models import Case

    return db.scalar(
        select(Case.id)
        .join(CaseMember, CaseMember.case_id == Case.id)
        .where(Case.title == title, CaseMember.user_id == owner_id, CaseMember.role == "owner")
    )


def seed_demo_case(
    *,
    session_factory: SessionFactory,
    settings: Settings,
    owner_email: str,
    viewer_emails: list[str] | None = None,
    title: str = DEMO_TITLE,
    demo_dir: Path = DEMO_DIR,
    dry_run: bool = False,
    process: bool = True,
) -> SeedResult:
    from app.modules.auth.schemas import MemberAdd
    from app.modules.auth.service import AuthService
    from app.modules.cases.schemas import CaseCreate
    from app.modules.cases.service import CaseService
    from app.modules.evidence.service import EvidenceService

    viewer_emails = [v.strip().lower() for v in (viewer_emails or []) if v.strip()]
    missing_files = [n for n in DEMO_FILES if not (demo_dir / n).is_file()]
    if missing_files:
        raise SeedError(f"demo files not found in {demo_dir}: {', '.join(missing_files)}")

    with session_factory() as db:
        owner = _user(db, owner_email)
        if owner is None:
            raise SeedError(f"no account uses {owner_email!r}; register it in the web app first")
        unknown = [v for v in viewer_emails if _user(db, v) is None]
        if unknown:
            raise SeedError(
                "no account uses "
                + ", ".join(repr(v) for v in unknown)
                + "; register the viewer accounts first"
            )
        existing = _existing_case(db, owner.id, title)
        if existing is not None:
            return SeedResult(status="exists", case_id=existing)
        if dry_run:
            return SeedResult(
                status="dry-run",
                files={n: "would upload" for n in DEMO_FILES},
                viewers=viewer_emails,
            )

        case = CaseService(db).create(CaseCreate(title=title, description=DEMO_DESCRIPTION))
        evidence = EvidenceService(db, settings=settings)
        uploaded: dict[str, uuid.UUID] = {}
        try:
            auth = AuthService(db, settings)
            auth.add_owner(case.id, owner)
            for name in DEMO_FILES:
                with (demo_dir / name).open("rb") as fh:
                    uploaded[name] = evidence.upload(case.id, filename=name, fileobj=fh).id
            for email in viewer_emails:
                auth.add_member(case.id, MemberAdd(email=email, role="viewer"), owner)
        except Exception as exc:
            # Never leave a half-seeded case: it would block every later run ("exists").
            _remove_partial_case(db, evidence, case.id)
            raise SeedError(
                f"seeding failed ({type(exc).__name__}); the partially created case and "
                "its stored files were removed, so the command can be run again"
            ) from exc
        case_id = case.id

    result = SeedResult(status="created", case_id=case_id, viewers=viewer_emails)
    if process:
        _process_and_analyse(session_factory, settings, case_id)
    _collect(session_factory, case_id, uploaded, result)
    return result


def _remove_partial_case(db: Session, evidence, case_id: uuid.UUID) -> None:  # noqa: ANN001
    """Undo a failed seed: blobs referenced only by this case (in the SEED's configured
    storage), then the case itself; its evidence rows and memberships go with it via
    ON DELETE CASCADE. Best effort: a failure here is logged, the original error wins."""
    from app.core.logging import get_logger
    from app.modules.cases.models import Case

    log = get_logger(__name__)
    try:
        db.rollback()
        evidence.cleanup_case_blobs(case_id)  # never raises
        case = db.get(Case, case_id)
        if case is not None:
            db.delete(case)
            db.commit()
    except Exception:  # noqa: BLE001 - reported, the seed error is raised by the caller
        db.rollback()
        log.warning("could not remove the partially seeded case %s", case_id)


def _process_and_analyse(
    session_factory: SessionFactory, settings: Settings, case_id: uuid.UUID
) -> None:
    from app.modules.analysis.runner import AnalysisRunner
    from app.modules.analysis.service import AnalysisService
    from app.modules.processing.executor import build_executor
    from app.modules.processing.registry import get_registry
    from app.modules.processing.runner import ProcessingRunner
    from app.modules.processing.service import ProcessingService
    from app.storage.factory import build_storage

    registry = get_registry()
    with session_factory() as db:
        queued = ProcessingService(db, registry, settings).enqueue_pending(case_id).queued
    ProcessingRunner(
        session_factory=session_factory,
        storage=build_storage(settings),
        registry=registry,
        executor=build_executor(settings),
        settings=settings,
    ).run_batch(case_id, list(queued))

    analysis = AnalysisRunner(session_factory=session_factory, settings=settings)
    with session_factory() as db:
        run_id = AnalysisService(db, settings).start_run(case_id, analysis.method).id
    analysis.run(case_id, run_id)


def _collect(
    session_factory: SessionFactory,
    case_id: uuid.UUID,
    uploaded: dict[str, uuid.UUID],
    result: SeedResult,
) -> None:
    from app.modules.analysis.models import Claim, Event, PotentialContradiction
    from app.modules.evidence.models import Evidence

    with session_factory() as db:
        for name, evidence_id in uploaded.items():
            ev = db.get(Evidence, evidence_id)
            result.files[name] = ev.processing_status
            if ev.processing_error_code:
                result.errors[name] = ev.processing_error_code

        def count(model) -> int:  # noqa: ANN001
            return int(
                db.scalar(select(func.count()).select_from(model).where(model.case_id == case_id))
                or 0
            )

        result.analysis = {
            "claims": count(Claim),
            "proposed_events": count(Event),
            "possible_inconsistencies": count(PotentialContradiction),
        }


# --- self-service demo for a signed-in user (POST /api/demo/missing-shipment) -------------


@dataclass
class ProvisionResult:
    status: str  # "created" | "exists" | "repaired"
    case_id: uuid.UUID
    uploaded: list[str] = field(default_factory=list)  # files added by THIS call


def _lock_user(db: Session, user_id: uuid.UUID) -> None:
    """Take the user's row lock until the next commit (a no-op UPDATE: ``updated_at``
    is set to itself). Concurrent demo requests of the same user are serialized, so
    a double click cannot create two demo cases or upload a file twice."""
    from sqlalchemy import update

    from app.modules.auth.models import User

    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(updated_at=User.updated_at)
        .execution_options(synchronize_session=False)
    )


def find_user_demo_case(db: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    """The demo case this user OWNS, if any: the case carrying the demo marker in its
    audit trail, or (for a case whose marker was never written) the demo title and
    description. Only the user's own cases are ever considered."""
    from app.modules.analysis.models import ReviewAction
    from app.modules.auth.models import CaseMember
    from app.modules.cases.models import Case

    owned = select(CaseMember.case_id).where(
        CaseMember.user_id == user_id, CaseMember.role == "owner"
    )
    marked = db.scalar(
        select(ReviewAction.case_id)
        .where(
            ReviewAction.case_id.in_(owned),
            ReviewAction.target_type == "case",
            ReviewAction.action == DEMO_MARKER_ACTION,
        )
        .order_by(ReviewAction.created_at.asc())
        .limit(1)
    )
    if marked is not None:
        return marked
    return db.scalar(
        select(Case.id)
        .where(
            Case.id.in_(owned),
            Case.title == DEMO_TITLE,
            Case.description == DEMO_DESCRIPTION,
        )
        .order_by(Case.created_at.asc())
        .limit(1)
    )


def _present_files(db: Session, case_id: uuid.UUID) -> set[str]:
    from app.modules.evidence.models import Evidence

    return set(db.scalars(select(Evidence.original_filename).where(Evidence.case_id == case_id)))


def provision_demo_case(
    db: Session,
    evidence,  # noqa: ANN001 - EvidenceService bound to ``db`` (storage injected)
    user,  # noqa: ANN001 - the signed-in User
    *,
    demo_dir: Path = DEMO_DIR,
) -> ProvisionResult:
    """Give ``user`` their own copy of the Missing Shipment demo case.

    * The case is created through the same services as "New investigation", owned by
      ``user`` and visible to nobody else.
    * Idempotent: an existing demo case of this user is returned, never duplicated.
    * Safe to retry: if an earlier attempt stopped part-way, the missing demo files are
      uploaded now ("repaired"). Each file is uploaded under the user's row lock and
      only when the case does not have it yet.
    * Nothing is processed here. Files are stored exactly as an upload would store
      them (validated by content, in the configured storage) and start "pending".
    """
    from app.modules.analysis.audit import record_action
    from app.modules.auth.models import CaseMember
    from app.modules.cases.models import Case

    missing_files = [n for n in DEMO_FILES if not (demo_dir / n).is_file()]
    if missing_files:
        raise SeedError("the demo files are not available on this server")

    _lock_user(db, user.id)
    case_id = find_user_demo_case(db, user.id)
    status = "exists"
    if case_id is None:
        # Case, owner membership and marker in ONE transaction (the repository helpers
        # commit, which would release the lock between the steps).
        case = Case(title=DEMO_TITLE, description=DEMO_DESCRIPTION, status="open")
        db.add(case)
        db.flush()
        db.add(CaseMember(case_id=case.id, user_id=user.id, role="owner"))
        record_action(
            db,
            case.id,
            "case",
            case.id,
            DEMO_MARKER_ACTION,
            to_status="open",
            note="Fictional demonstration case loaded from the built-in sample evidence.",
            payload={"files": list(DEMO_FILES)},
        )
        db.commit()  # releases the lock; the marker now identifies the case
        case_id = case.id
        status = "created"
    else:
        db.commit()  # nothing to write; release the lock

    uploaded: list[str] = []
    for name in DEMO_FILES:
        _lock_user(db, user.id)
        if name in _present_files(db, case_id):
            db.commit()
            continue
        with (demo_dir / name).open("rb") as fh:
            evidence.upload(case_id, filename=name, fileobj=fh)  # commits
        uploaded.append(name)
    if status == "exists" and uploaded:
        status = "repaired"
    return ProvisionResult(status=status, case_id=case_id, uploaded=uploaded)
