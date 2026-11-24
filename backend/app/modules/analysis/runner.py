"""Background case analysis: claims -> entities -> relationships -> potential
contradictions.

Runs with its OWN database session after the HTTP response. Each evidence item is
analysed inside its own savepoint, so a failure on one item is recorded in the run's
stats and never affects the others. Re-running is idempotent: an extraction that
already has claims from the active method is skipped, and claims, mentions,
relationships and contradictions are de-duplicated by key.

Logging rule: ids, counts and error types only. Never evidence text.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db_types import utcnow
from app.core.logging import get_logger
from app.modules.analysis import extract
from app.modules.analysis.engine import ClaimFacts, detect
from app.modules.analysis.extract import ClaimDraft, MentionDraft, SegmentView
from app.modules.analysis.models import (
    AlternativeExplanation,
    AnalysisRun,
    Claim,
    ClaimEntity,
    ClaimRelationship,
    Entity,
    PotentialContradiction,
)
from app.modules.analysis.repository import AnalysisRepository
from app.modules.evidence.models import Evidence
from app.modules.processing.models import Extraction, ExtractionSegment

logger = get_logger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

# Identifier-like mentions share one entity record when their normalized key is
# identical, whatever context word ("shipment", none) surrounded them.
_IDENTIFIER_FAMILY = ("shipment", "identifier")
MAX_LINKS_PER_ENTITY = 50
MAX_ALIASES = 20
_KIND_LABELS = {
    "shipment": "shipment identifier",
    "identifier": "identifier",
    "vehicle": "vehicle",
    "location": "location",
    "contact": "contact",
}


def _kind_label(entity_type: str) -> str:
    return _KIND_LABELS.get(entity_type, "entity")


class ClaimExtractor(Protocol):
    method: str

    def extract(self, segments: list[SegmentView]) -> list[ClaimDraft]: ...


class RuleBasedClaimExtractor:
    """Deterministic pattern rules. Not an AI model; labelled ``rule_based_v1``."""

    method = extract.METHOD

    def extract(self, segments: list[SegmentView]) -> list[ClaimDraft]:
        return extract.extract_claims(segments)


def build_claim_extractor(settings: Settings) -> ClaimExtractor:
    """The configured extractor. Gemini only when explicitly enabled AND keyed."""
    if settings.claim_extractor == "gemini" and settings.gemini_api_key:
        from app.ai.claims_llm import GeminiClaimExtractor
        from app.ai.gemini_client import GeminiClient

        return GeminiClaimExtractor(
            GeminiClient(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                timeout_seconds=settings.gemini_timeout_seconds,
            )
        )
    return RuleBasedClaimExtractor()


def ground(draft: ClaimDraft, segment: ExtractionSegment | None) -> ClaimDraft:
    """Enforce the provenance invariant on a draft before it is stored.

    The quote must be found verbatim in the anchored segment's text. Offsets are
    recomputed when the quote is present elsewhere in the text. Otherwise the claim
    keeps its segment anchor but is marked ``insufficient`` and loses its offsets; it
    is never given an invented locator. A draft without any segment is stripped of
    its anchor here and the runner refuses to store it.
    """
    if segment is None:
        draft.grounding = "insufficient"
        draft.segment_id = None
        draft.quote_start = draft.quote_end = None
        draft.locator = None
        return draft
    text = segment.text or ""
    qs, qe = draft.quote_start, draft.quote_end
    if draft.quote and qs is not None and qe is not None and text[qs:qe] == draft.quote:
        return draft
    if draft.quote and draft.quote in text:
        draft.quote_start = text.index(draft.quote)
        draft.quote_end = draft.quote_start + len(draft.quote)
        return draft
    if segment.segment_type == "email_header" and draft.quote == text:
        return draft
    draft.grounding = "insufficient"
    draft.quote_start = draft.quote_end = None
    draft.uncertainty = [*draft.uncertainty, "the quoted text was not found in the source"]
    return draft


class AnalysisRunner:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        settings: Settings,
        extractor: ClaimExtractor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._extractor = extractor or build_claim_extractor(settings)

    @property
    def method(self) -> str:
        return self._extractor.method

    def run(self, case_id: uuid.UUID, run_id: uuid.UUID) -> None:
        """Analyse the case. Never raises."""
        with self._session_factory() as db:
            repo = AnalysisRepository(db)
            run = repo.get_run(case_id, run_id)
            if run is None:
                return
            stats: dict = {
                "evidence_total": 0,
                "evidence_analysed": 0,
                "evidence_skipped": 0,
                "claims_created": 0,
                "claims_insufficient": 0,
                "claims_dropped_unanchored": 0,
                "entities_created": 0,
                "mentions_created": 0,
                "relationships_created": 0,
                "contradictions_created": 0,
                "errors": [],
            }
            try:
                cache: dict[tuple[str, str], Entity] = {}
                for extraction, evidence in repo.current_extractions(case_id):
                    stats["evidence_total"] += 1
                    if repo.extraction_has_claims(extraction.id, self.method):
                        stats["evidence_skipped"] += 1
                        continue
                    try:
                        with db.begin_nested():
                            self._analyse_extraction(repo, run, extraction, evidence, stats, cache)
                        stats["evidence_analysed"] += 1
                    except Exception as exc:  # noqa: BLE001 - isolate one item
                        cache.clear()  # rolled-back entities must not be reused
                        stats["errors"].append(
                            {"evidence_id": str(evidence.id), "error_type": type(exc).__name__}
                        )
                        logger.error(
                            "analysis item failed evidence=%s error_type=%s",
                            evidence.id,
                            type(exc).__name__,
                        )
                    db.commit()
                with db.begin_nested():
                    self._link_and_detect(repo, case_id, stats)
                run.status = "completed"
                run.stats = stats
                run.completed_at = utcnow()
                db.commit()
                logger.info(
                    "analysis completed case=%s run=%s claims=%d contradictions=%d",
                    case_id,
                    run_id,
                    stats["claims_created"],
                    stats["contradictions_created"],
                )
            except Exception as exc:  # noqa: BLE001
                run = repo.get_run(case_id, run_id)
                if run is not None:
                    run.status = "failed"
                    run.error = f"Analysis stopped unexpectedly ({type(exc).__name__})."
                    run.stats = stats
                    run.completed_at = utcnow()
                    db.commit()
                logger.error(
                    "analysis failed case=%s run=%s error_type=%s",
                    case_id,
                    run_id,
                    type(exc).__name__,
                )

    # --- step 1: claims and entities -------------------------------------------

    def _analyse_extraction(
        self,
        repo: AnalysisRepository,
        run: AnalysisRun,
        extraction: Extraction,
        evidence: Evidence,
        stats: dict,
        cache: dict[tuple[str, str], Entity],
    ) -> None:
        segments = repo.segments_for_extraction(extraction.id)
        by_id = {str(s.id): s for s in segments}
        views = [
            SegmentView(
                id=str(s.id),
                segment_type=s.segment_type,
                text=s.text,
                data=s.data,
                locator=dict(s.locator or {}),
                engine_confidence=s.engine_confidence,
                evidence_type=evidence.evidence_type,
            )
            for s in segments
        ]
        drafts = self._extractor.extract(views)
        keyed: dict[str, ClaimDraft] = {}
        for draft in drafts:
            segment = by_id.get(draft.segment_id or "")
            if segment is None:
                # No source anchor in this extraction: never stored (provenance rule).
                stats["claims_dropped_unanchored"] += 1
                continue
            ground(draft, segment)
            keyed.setdefault(draft.dedupe_key(str(evidence.id)), draft)
        existing = repo.existing_dedupe_keys(run.case_id, keyed)
        for key, draft in keyed.items():
            if key in existing:
                continue
            claim = Claim(
                case_id=run.case_id,
                evidence_id=evidence.id,
                extraction_id=extraction.id,
                segment_id=uuid.UUID(draft.segment_id) if draft.segment_id else None,
                analysis_run_id=run.id,
                claim_text=draft.claim_text,
                claim_type=draft.claim_type,
                subject=draft.subject,
                predicate=draft.predicate,
                predicate_key=draft.predicate_key,
                object_value=draft.object_value,
                event_time=draft.event_time,
                location=draft.location,
                quote=draft.quote,
                quote_start=draft.quote_start,
                quote_end=draft.quote_end,
                locator=draft.locator,
                modality=draft.modality,
                grounding=draft.grounding,
                extraction_method=draft.method,
                is_inferred=draft.is_inferred,
                extraction_confidence=draft.extraction_confidence,
                source_engine_confidence=draft.source_engine_confidence,
                uncertainty=list(draft.uncertainty),
                review_status="unreviewed",
                dedupe_key=key,
            )
            repo.add(claim)
            repo.flush()
            stats["claims_created"] += 1
            if draft.grounding != "grounded":
                stats["claims_insufficient"] += 1
            for mention in draft.mentions:
                entity = self._entity_for(repo, run.case_id, mention, stats, cache)
                if not repo.mention_exists(claim.id, entity.id, mention.text):
                    repo.add(
                        ClaimEntity(
                            case_id=run.case_id,
                            claim_id=claim.id,
                            entity_id=entity.id,
                            mention_text=mention.text,
                            role=mention.role,
                        )
                    )
                    stats["mentions_created"] += 1
            repo.flush()

    def _entity_for(
        self,
        repo: AnalysisRepository,
        case_id: uuid.UUID,
        mention: MentionDraft,
        stats: dict,
        cache: dict[tuple[str, str], Entity],
    ) -> Entity:
        family = "id" if mention.entity_type in _IDENTIFIER_FAMILY else mention.entity_type
        types = _IDENTIFIER_FAMILY if family == "id" else (mention.entity_type,)
        entity = cache.get((family, mention.normalized_key)) or repo.find_entity(
            case_id, types, mention.normalized_key
        )
        if entity is None:
            entity = Entity(
                case_id=case_id,
                entity_type=mention.entity_type,
                display_name=mention.display,
                normalized_key=mention.normalized_key,
                aliases=[mention.text],
            )
            repo.add(entity)
            repo.flush()
            stats["entities_created"] += 1
        else:
            if entity.entity_type == "identifier" and mention.entity_type == "shipment":
                entity.entity_type = "shipment"  # context now says what the identifier is
            if mention.text not in (entity.aliases or []) and len(entity.aliases) < MAX_ALIASES:
                entity.aliases = [*entity.aliases, mention.text]
        cache[(family, mention.normalized_key)] = entity
        return entity

    # --- step 2 + 3: relationships and potential contradictions -----------------

    def _link_and_detect(self, repo: AnalysisRepository, case_id: uuid.UUID, stats: dict) -> None:
        rows, _ = repo.list_claims(case_id, current_only=True)
        claims = {c.id: (c, ev) for c, ev, _ex in rows if c.review_status != "rejected"}
        entities = {e.id: e for e in repo.list_entities(case_id)}

        def canonical(entity_id: uuid.UUID) -> uuid.UUID | None:
            seen: set[uuid.UUID] = set()
            entity = entities.get(entity_id)
            while entity is not None and entity.merged_into_id and entity.id not in seen:
                seen.add(entity.id)
                entity = entities.get(entity.merged_into_id)
            if entity is None or entity.resolution_status == "rejected":
                return None
            return entity.id

        facts: dict[uuid.UUID, ClaimFacts] = {}
        per_entity: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {}
        for mention, _entity in repo.mentions_for_claims(list(claims)):
            if mention.claim_id not in claims:
                continue
            ent = canonical(mention.entity_id)
            if ent is None:
                continue
            claim, evidence = claims[mention.claim_id]
            fact = facts.get(claim.id)
            if fact is None:
                fact = facts[claim.id] = ClaimFacts(
                    id=str(claim.id),
                    evidence_id=str(claim.evidence_id),
                    evidence_name=evidence.original_filename,
                    modality=claim.modality,
                    quote=claim.quote,
                    predicate_key=claim.predicate_key,
                    event_time=claim.event_time,
                    object_value=claim.object_value,
                    claim_type=claim.claim_type,
                    uncertainty=list(claim.uncertainty or []),
                )
            fact.entity_ids.add(str(ent))
            # First claim per evidence item for each entity: enough to link the items.
            per_entity.setdefault(ent, {}).setdefault(claim.evidence_id, claim.id)

        # The session does not autoflush, so pairs added in this pass are invisible to
        # relationship_exists. Two claims sharing several entities must still get ONE
        # link per relation type (unique constraint), whatever the direction.
        linked: set[tuple[frozenset[uuid.UUID], str]] = set()
        for entity_id, by_evidence in per_entity.items():
            items = list(by_evidence.values())
            made = 0
            for i, a in enumerate(items):
                for b in items[i + 1 :]:
                    if made >= MAX_LINKS_PER_ENTITY:
                        break
                    pair = (frozenset((a, b)), "mentions_same_entity")
                    if pair in linked or repo.relationship_exists(a, b, "mentions_same_entity"):
                        continue
                    linked.add(pair)
                    entity = entities[entity_id]
                    name = entity.display_name
                    repo.add(
                        ClaimRelationship(
                            case_id=case_id,
                            source_claim_id=a,
                            target_claim_id=b,
                            via_entity_id=entity_id,
                            relation_type="mentions_same_entity",
                            rationale=(
                                f"Both claims mention the same {_kind_label(entity.entity_type)}"
                                f" '{name}' (exact normalized match)."
                            ),
                            origin=extract.METHOD,
                        )
                    )
                    made += 1
                    stats["relationships_created"] += 1
        repo.flush()

        flagged: set[tuple[frozenset[uuid.UUID], str]] = set()
        for found in detect(list(facts.values())):
            a, b = uuid.UUID(found.claim_a_id), uuid.UUID(found.claim_b_id)
            key = (frozenset((a, b)), found.category)
            if key in flagged or repo.contradiction_exists(a, b, found.category):
                continue
            flagged.add(key)
            record = PotentialContradiction(
                case_id=case_id,
                claim_a_id=a,
                claim_b_id=b,
                via_entity_id=uuid.UUID(found.via_entity_id),
                category=found.category,
                explanation=found.explanation,
                severity=found.severity,
                detection_confidence=found.detection_confidence,
                uncertainty=found.uncertainty,
                origin=found.origin,
                linked_evidence_ids=[],
            )
            repo.add(record)
            repo.flush()
            for alt in found.alternatives:
                repo.add(
                    AlternativeExplanation(
                        case_id=case_id,
                        contradiction_id=record.id,
                        explanation=alt.explanation,
                        supporting_evidence=alt.supporting_evidence,
                        weakening_evidence=alt.weakening_evidence,
                        missing_information=alt.missing_information,
                        verification_recommendation=alt.verification_recommendation,
                        basis=alt.basis,
                    )
                )
            conflict_pair = (frozenset((a, b)), "potentially_conflicts_with")
            if conflict_pair not in linked and not repo.relationship_exists(
                a, b, "potentially_conflicts_with"
            ):
                linked.add(conflict_pair)
                repo.add(
                    ClaimRelationship(
                        case_id=case_id,
                        source_claim_id=a,
                        target_claim_id=b,
                        via_entity_id=uuid.UUID(found.via_entity_id),
                        relation_type="potentially_conflicts_with",
                        rationale=found.explanation["why"],
                        origin=found.origin,
                    )
                )
                stats["relationships_created"] += 1
            stats["contradictions_created"] += 1
        repo.flush()


def build_default_analysis_runner() -> AnalysisRunner:
    from app.core.database import SessionLocal

    return AnalysisRunner(session_factory=SessionLocal, settings=get_settings())
