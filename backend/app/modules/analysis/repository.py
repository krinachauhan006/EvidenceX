"""Data access for analysis records. Every query is scoped by ``case_id``."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.analysis.models import (
    AlternativeExplanation,
    AnalysisRun,
    Claim,
    ClaimEntity,
    ClaimRelationship,
    Entity,
    PotentialContradiction,
    ReviewAction,
    SegmentReview,
)
from app.modules.evidence.models import Evidence
from app.modules.processing.models import Extraction, ExtractionSegment

ClaimRow = tuple[Claim, Evidence, Extraction]


class AnalysisRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    @property
    def db(self) -> Session:
        return self._db

    def add(self, obj: Any) -> None:
        self._db.add(obj)

    def flush(self) -> None:
        self._db.flush()

    # --- runs -------------------------------------------------------------------

    def get_run(self, case_id: uuid.UUID, run_id: uuid.UUID) -> AnalysisRun | None:
        return self._db.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.id == run_id, AnalysisRun.case_id == case_id)
            .execution_options(populate_existing=True)
        )

    def latest_run(self, case_id: uuid.UUID) -> AnalysisRun | None:
        return self._db.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.case_id == case_id)
            .order_by(AnalysisRun.started_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )

    def active_run(self, case_id: uuid.UUID, since: datetime) -> AnalysisRun | None:
        return self._db.scalar(
            select(AnalysisRun).where(
                AnalysisRun.case_id == case_id,
                AnalysisRun.status == "running",
                AnalysisRun.started_at >= since,
            )
        )

    # --- sources ----------------------------------------------------------------

    def current_extractions(self, case_id: uuid.UUID) -> list[tuple[Extraction, Evidence]]:
        stmt = (
            select(Extraction, Evidence)
            .join(Evidence, Evidence.id == Extraction.evidence_id)
            .where(
                Extraction.case_id == case_id,
                Extraction.is_current.is_(True),
                Extraction.run_status == "completed",
            )
            .order_by(Evidence.created_at.asc(), Evidence.id.asc())
        )
        return [(ex, ev) for ex, ev in self._db.execute(stmt).all()]

    def extraction_has_claims(self, extraction_id: uuid.UUID, method: str) -> bool:
        return (
            self._db.scalar(
                select(Claim.id)
                .where(Claim.extraction_id == extraction_id, Claim.extraction_method == method)
                .limit(1)
            )
            is not None
        )

    def segments_for_extraction(self, extraction_id: uuid.UUID) -> list[ExtractionSegment]:
        return list(
            self._db.scalars(
                select(ExtractionSegment)
                .where(ExtractionSegment.extraction_id == extraction_id)
                .order_by(ExtractionSegment.seq.asc())
            ).all()
        )

    def get_segment(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID, segment_id: uuid.UUID
    ) -> ExtractionSegment | None:
        return self._db.scalar(
            select(ExtractionSegment).where(
                ExtractionSegment.id == segment_id,
                ExtractionSegment.case_id == case_id,
                ExtractionSegment.evidence_id == evidence_id,
            )
        )

    def get_segment_any(self, segment_id: uuid.UUID) -> ExtractionSegment | None:
        return self._db.get(ExtractionSegment, segment_id)

    def get_evidence(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> Evidence | None:
        return self._db.scalar(
            select(Evidence).where(Evidence.id == evidence_id, Evidence.case_id == case_id)
        )

    def list_evidence(self, case_id: uuid.UUID) -> list[Evidence]:
        return list(
            self._db.scalars(
                select(Evidence)
                .where(Evidence.case_id == case_id)
                .order_by(Evidence.created_at.asc(), Evidence.id.asc())
            ).all()
        )

    def segment_count(self, case_id: uuid.UUID, evidence_id: uuid.UUID | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(ExtractionSegment)
            .join(Extraction, Extraction.id == ExtractionSegment.extraction_id)
            .where(ExtractionSegment.case_id == case_id, Extraction.is_current.is_(True))
        )
        if evidence_id is not None:
            stmt = stmt.where(ExtractionSegment.evidence_id == evidence_id)
        return int(self._db.scalar(stmt) or 0)

    # --- claims -----------------------------------------------------------------

    def existing_dedupe_keys(self, case_id: uuid.UUID, keys: Iterable[str]) -> set[str]:
        keys = list(keys)
        if not keys:
            return set()
        return set(
            self._db.scalars(
                select(Claim.dedupe_key).where(Claim.case_id == case_id, Claim.dedupe_key.in_(keys))
            ).all()
        )

    def _claim_query(self, case_id: uuid.UUID):  # noqa: ANN202 - SQLAlchemy Select
        return (
            select(Claim, Evidence, Extraction)
            .join(Evidence, Evidence.id == Claim.evidence_id)
            .join(Extraction, Extraction.id == Claim.extraction_id)
            .where(Claim.case_id == case_id)
        )

    def list_claims(
        self,
        case_id: uuid.UUID,
        *,
        evidence_id: uuid.UUID | None = None,
        review_status: Sequence[str] | None = None,
        claim_type: str | None = None,
        modality: str | None = None,
        entity_id: uuid.UUID | None = None,
        segment_id: uuid.UUID | None = None,
        search: str | None = None,
        current_only: bool = True,
        claim_ids: Sequence[uuid.UUID] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[ClaimRow], int]:
        stmt = self._claim_query(case_id)
        if evidence_id is not None:
            stmt = stmt.where(Claim.evidence_id == evidence_id)
        if review_status:
            stmt = stmt.where(Claim.review_status.in_(list(review_status)))
        if claim_type:
            stmt = stmt.where(Claim.claim_type == claim_type)
        if modality:
            stmt = stmt.where(Claim.modality == modality)
        if segment_id is not None:
            stmt = stmt.where(Claim.segment_id == segment_id)
        if entity_id is not None:
            stmt = stmt.where(
                Claim.id.in_(select(ClaimEntity.claim_id).where(ClaimEntity.entity_id == entity_id))
            )
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(func.lower(Claim.claim_text).like(like), func.lower(Claim.quote).like(like))
            )
        if current_only:
            stmt = stmt.where(Extraction.is_current.is_(True))
        if claim_ids is not None:
            stmt = stmt.where(Claim.id.in_(list(claim_ids)))
        total = int(self._db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        stmt = stmt.order_by(Evidence.created_at.asc(), Claim.created_at.asc(), Claim.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return [(c, ev, ex) for c, ev, ex in self._db.execute(stmt).all()], total

    def get_claim_row(self, case_id: uuid.UUID, claim_id: uuid.UUID) -> ClaimRow | None:
        row = self._db.execute(self._claim_query(case_id).where(Claim.id == claim_id)).first()
        return (row[0], row[1], row[2]) if row else None

    def get_claim(self, case_id: uuid.UUID, claim_id: uuid.UUID) -> Claim | None:
        return self._db.scalar(select(Claim).where(Claim.id == claim_id, Claim.case_id == case_id))

    def claim_count(self, case_id: uuid.UUID, **filters: Any) -> int:
        _, total = self.list_claims(case_id, limit=0, **filters)
        return total

    # --- entities and mentions --------------------------------------------------

    def find_entity(self, case_id: uuid.UUID, types: Sequence[str], key: str) -> Entity | None:
        return self._db.scalar(
            select(Entity)
            .where(
                Entity.case_id == case_id,
                Entity.entity_type.in_(list(types)),
                Entity.normalized_key == key,
            )
            .order_by(Entity.created_at.asc())
            .limit(1)
        )

    def get_entity(self, case_id: uuid.UUID, entity_id: uuid.UUID) -> Entity | None:
        return self._db.scalar(
            select(Entity).where(Entity.id == entity_id, Entity.case_id == case_id)
        )

    def list_entities(self, case_id: uuid.UUID) -> list[Entity]:
        return list(
            self._db.scalars(
                select(Entity)
                .where(Entity.case_id == case_id)
                .order_by(Entity.entity_type.asc(), Entity.display_name.asc())
            ).all()
        )

    def entities_merged_into(self, case_id: uuid.UUID, entity_id: uuid.UUID) -> list[Entity]:
        return list(
            self._db.scalars(
                select(Entity).where(Entity.case_id == case_id, Entity.merged_into_id == entity_id)
            ).all()
        )

    def mention_exists(self, claim_id: uuid.UUID, entity_id: uuid.UUID, text: str) -> bool:
        return (
            self._db.scalar(
                select(ClaimEntity.id).where(
                    ClaimEntity.claim_id == claim_id,
                    ClaimEntity.entity_id == entity_id,
                    ClaimEntity.mention_text == text,
                )
            )
            is not None
        )

    def mentions_for_claims(
        self, claim_ids: Sequence[uuid.UUID]
    ) -> list[tuple[ClaimEntity, Entity]]:
        if not claim_ids:
            return []
        stmt = (
            select(ClaimEntity, Entity)
            .join(Entity, Entity.id == ClaimEntity.entity_id)
            .where(ClaimEntity.claim_id.in_(list(claim_ids)))
            .order_by(ClaimEntity.created_at.asc())
        )
        return [(m, e) for m, e in self._db.execute(stmt).all()]

    def mentions_for_entities(
        self, case_id: uuid.UUID, entity_ids: Sequence[uuid.UUID]
    ) -> list[ClaimEntity]:
        if not entity_ids:
            return []
        return list(
            self._db.scalars(
                select(ClaimEntity).where(
                    ClaimEntity.case_id == case_id, ClaimEntity.entity_id.in_(list(entity_ids))
                )
            ).all()
        )

    def mention_stats(self, case_id: uuid.UUID) -> dict[uuid.UUID, tuple[int, int]]:
        """entity id -> (mentions, distinct evidence items), current sources only."""
        stmt = (
            select(
                ClaimEntity.entity_id,
                func.count(ClaimEntity.id),
                func.count(func.distinct(Claim.evidence_id)),
            )
            .join(Claim, Claim.id == ClaimEntity.claim_id)
            .join(Extraction, Extraction.id == Claim.extraction_id)
            .where(ClaimEntity.case_id == case_id, Extraction.is_current.is_(True))
            .group_by(ClaimEntity.entity_id)
        )
        return {eid: (int(n), int(ev)) for eid, n, ev in self._db.execute(stmt).all()}

    def entities_with_modalities(
        self, case_id: uuid.UUID, modalities: Sequence[str]
    ) -> set[uuid.UUID]:
        """Entity ids mentioned by at least one claim of the given source modalities."""
        stmt = (
            select(ClaimEntity.entity_id)
            .join(Claim, Claim.id == ClaimEntity.claim_id)
            .where(ClaimEntity.case_id == case_id, Claim.modality.in_(list(modalities)))
            .distinct()
        )
        return set(self._db.scalars(stmt).all())

    # --- relationships ----------------------------------------------------------

    def relationship_exists(self, source: uuid.UUID, target: uuid.UUID, kind: str) -> bool:
        return (
            self._db.scalar(
                select(ClaimRelationship.id).where(
                    or_(
                        and_(
                            ClaimRelationship.source_claim_id == source,
                            ClaimRelationship.target_claim_id == target,
                        ),
                        and_(
                            ClaimRelationship.source_claim_id == target,
                            ClaimRelationship.target_claim_id == source,
                        ),
                    ),
                    ClaimRelationship.relation_type == kind,
                )
            )
            is not None
        )

    def list_relationships(
        self,
        case_id: uuid.UUID,
        *,
        claim_ids: Sequence[uuid.UUID] | None = None,
        relation_type: str | None = None,
        review_status: Sequence[str] | None = None,
    ) -> list[ClaimRelationship]:
        stmt = select(ClaimRelationship).where(ClaimRelationship.case_id == case_id)
        if claim_ids is not None:
            ids = list(claim_ids)
            stmt = stmt.where(
                or_(
                    ClaimRelationship.source_claim_id.in_(ids),
                    ClaimRelationship.target_claim_id.in_(ids),
                )
            )
        if relation_type:
            stmt = stmt.where(ClaimRelationship.relation_type == relation_type)
        if review_status:
            stmt = stmt.where(ClaimRelationship.review_status.in_(list(review_status)))
        return list(self._db.scalars(stmt.order_by(ClaimRelationship.created_at.asc())).all())

    def get_relationship(
        self, case_id: uuid.UUID, relationship_id: uuid.UUID
    ) -> ClaimRelationship | None:
        return self._db.scalar(
            select(ClaimRelationship).where(
                ClaimRelationship.id == relationship_id, ClaimRelationship.case_id == case_id
            )
        )

    # --- contradictions ---------------------------------------------------------

    def contradiction_exists(self, a: uuid.UUID, b: uuid.UUID, category: str) -> bool:
        return (
            self._db.scalar(
                select(PotentialContradiction.id).where(
                    or_(
                        and_(
                            PotentialContradiction.claim_a_id == a,
                            PotentialContradiction.claim_b_id == b,
                        ),
                        and_(
                            PotentialContradiction.claim_a_id == b,
                            PotentialContradiction.claim_b_id == a,
                        ),
                    ),
                    PotentialContradiction.category == category,
                )
            )
            is not None
        )

    def list_contradictions(
        self,
        case_id: uuid.UUID,
        *,
        review_status: Sequence[str] | None = None,
        severity: str | None = None,
        claim_ids: Sequence[uuid.UUID] | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> list[PotentialContradiction]:
        stmt = select(PotentialContradiction).where(PotentialContradiction.case_id == case_id)
        if review_status:
            stmt = stmt.where(PotentialContradiction.review_status.in_(list(review_status)))
        if severity:
            stmt = stmt.where(PotentialContradiction.severity == severity)
        if entity_id is not None:
            stmt = stmt.where(PotentialContradiction.via_entity_id == entity_id)
        if claim_ids is not None:
            ids = list(claim_ids)
            stmt = stmt.where(
                or_(
                    PotentialContradiction.claim_a_id.in_(ids),
                    PotentialContradiction.claim_b_id.in_(ids),
                )
            )
        return list(
            self._db.scalars(
                stmt.order_by(
                    PotentialContradiction.created_at.asc(), PotentialContradiction.id.asc()
                )
            ).all()
        )

    def get_contradiction(
        self, case_id: uuid.UUID, contradiction_id: uuid.UUID
    ) -> PotentialContradiction | None:
        return self._db.scalar(
            select(PotentialContradiction).where(
                PotentialContradiction.id == contradiction_id,
                PotentialContradiction.case_id == case_id,
            )
        )

    def alternatives_for(
        self, contradiction_ids: Sequence[uuid.UUID]
    ) -> list[AlternativeExplanation]:
        if not contradiction_ids:
            return []
        return list(
            self._db.scalars(
                select(AlternativeExplanation)
                .where(AlternativeExplanation.contradiction_id.in_(list(contradiction_ids)))
                .order_by(AlternativeExplanation.created_at.asc(), AlternativeExplanation.id.asc())
            ).all()
        )

    # --- review history ---------------------------------------------------------

    def list_reviews(
        self,
        case_id: uuid.UUID,
        *,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        action: str | None = None,
        limit: int = 200,
    ) -> list[ReviewAction]:
        stmt = select(ReviewAction).where(ReviewAction.case_id == case_id)
        if target_type:
            stmt = stmt.where(ReviewAction.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(ReviewAction.target_id == target_id)
        if action:
            stmt = stmt.where(ReviewAction.action == action)
        stmt = stmt.order_by(ReviewAction.created_at.desc(), ReviewAction.id.desc()).limit(limit)
        return list(self._db.scalars(stmt).all())

    # --- segment reviews --------------------------------------------------------

    def segment_reviews(self, segment_id: uuid.UUID) -> list[SegmentReview]:
        return list(
            self._db.scalars(
                select(SegmentReview)
                .where(SegmentReview.segment_id == segment_id)
                .order_by(SegmentReview.created_at.desc(), SegmentReview.id.desc())
            ).all()
        )
