"""HTTP endpoints for analysis and review, nested under the owning case."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.analysis.runner import AnalysisRunner, build_default_analysis_runner
from app.modules.analysis.schemas import (
    AlternativeCreate,
    AnalysisRunOut,
    AnalysisRunState,
    CandidateList,
    ClaimDetail,
    ClaimList,
    ClaimReviewRequest,
    ContradictionDetail,
    ContradictionList,
    ContradictionReviewRequest,
    DashboardOut,
    EntityDetail,
    EntityList,
    EntityReviewRequest,
    EvidenceAnalysisSummary,
    GraphOut,
    RelationshipList,
    RelationshipOut,
    RelationshipReviewRequest,
    ReviewHistory,
    ReviewQueueOut,
    SegmentReviewCreate,
    SegmentReviewList,
)
from app.modules.analysis.service import (
    DEFAULT_CLAIM_LIMIT,
    MAX_CLAIM_LIMIT,
    AnalysisService,
    run_out,
)

router = APIRouter(prefix="/api/cases/{case_id}", tags=["analysis"])


def get_analysis_service(db: Session = Depends(get_db)) -> AnalysisService:
    return AnalysisService(db)


def get_analysis_runner() -> AnalysisRunner:
    return build_default_analysis_runner()


# --- analysis runs ---------------------------------------------------------------


@router.post("/analysis", response_model=AnalysisRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_analysis(
    case_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    service: AnalysisService = Depends(get_analysis_service),
    runner: AnalysisRunner = Depends(get_analysis_runner),
) -> AnalysisRunOut:
    run = service.start_run(case_id, runner.method)
    out = run_out(run)
    background_tasks.add_task(runner.run, case_id, run.id)
    return out


@router.get("/analysis/latest", response_model=AnalysisRunState)
def latest_analysis(
    case_id: uuid.UUID, service: AnalysisService = Depends(get_analysis_service)
) -> AnalysisRunState:
    return service.latest_run(case_id)


# --- claims ------------------------------------------------------------------------


@router.get("/claims", response_model=ClaimList)
def list_claims(
    case_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    evidence_id: uuid.UUID | None = Query(default=None),
    review_status: str | None = Query(default=None, max_length=24),
    claim_type: str | None = Query(default=None, max_length=32),
    modality: str | None = Query(default=None, max_length=16),
    entity_id: uuid.UUID | None = Query(default=None),
    segment_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    include_superseded: bool = Query(default=False),
    limit: int = Query(default=DEFAULT_CLAIM_LIMIT, ge=1, le=MAX_CLAIM_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> ClaimList:
    return service.list_claims(
        case_id,
        evidence_id=evidence_id,
        review_status=review_status,
        claim_type=claim_type,
        modality=modality,
        entity_id=entity_id,
        segment_id=segment_id,
        search=q,
        include_superseded=include_superseded,
        limit=limit,
        offset=offset,
    )


@router.get("/claims/{claim_id}", response_model=ClaimDetail)
def get_claim(
    case_id: uuid.UUID,
    claim_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
) -> ClaimDetail:
    return service.get_claim(case_id, claim_id)


@router.post("/claims/{claim_id}/review", response_model=ClaimDetail)
def review_claim(
    case_id: uuid.UUID,
    claim_id: uuid.UUID,
    payload: ClaimReviewRequest,
    service: AnalysisService = Depends(get_analysis_service),
) -> ClaimDetail:
    return service.review_claim(case_id, claim_id, payload)


# --- entities ----------------------------------------------------------------------


@router.get("/entities", response_model=EntityList)
def list_entities(
    case_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    entity_type: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=200),
    include_merged: bool = Query(default=False),
) -> EntityList:
    return service.list_entities(
        case_id, entity_type=entity_type, search=q, include_merged=include_merged
    )


@router.get("/entities/candidates", response_model=CandidateList)
def entity_candidates(
    case_id: uuid.UUID, service: AnalysisService = Depends(get_analysis_service)
) -> CandidateList:
    return service.candidates(case_id)


@router.get("/entities/{entity_id}", response_model=EntityDetail)
def get_entity(
    case_id: uuid.UUID,
    entity_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
) -> EntityDetail:
    return service.get_entity(case_id, entity_id)


@router.post("/entities/{entity_id}/review", response_model=EntityDetail)
def review_entity(
    case_id: uuid.UUID,
    entity_id: uuid.UUID,
    payload: EntityReviewRequest,
    service: AnalysisService = Depends(get_analysis_service),
) -> EntityDetail:
    return service.review_entity(case_id, entity_id, payload)


# --- relationships -----------------------------------------------------------------


@router.get("/relationships", response_model=RelationshipList)
def list_relationships(
    case_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    relation_type: str | None = Query(default=None, max_length=48),
    evidence_id: uuid.UUID | None = Query(default=None),
    claim_id: uuid.UUID | None = Query(default=None),
) -> RelationshipList:
    return service.list_relationships(
        case_id, relation_type=relation_type, evidence_id=evidence_id, claim_id=claim_id
    )


@router.post("/relationships/{relationship_id}/review", response_model=RelationshipOut)
def review_relationship(
    case_id: uuid.UUID,
    relationship_id: uuid.UUID,
    payload: RelationshipReviewRequest,
    service: AnalysisService = Depends(get_analysis_service),
) -> RelationshipOut:
    return service.review_relationship(case_id, relationship_id, payload)


# --- potential contradictions ------------------------------------------------------


@router.get("/contradictions", response_model=ContradictionList)
def list_contradictions(
    case_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    review_status: str | None = Query(default=None, max_length=24),
    severity: str | None = Query(default=None, max_length=8),
    evidence_id: uuid.UUID | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
) -> ContradictionList:
    return service.list_contradictions(
        case_id,
        review_status=review_status,
        severity=severity,
        evidence_id=evidence_id,
        entity_id=entity_id,
    )


@router.get("/contradictions/{contradiction_id}", response_model=ContradictionDetail)
def get_contradiction(
    case_id: uuid.UUID,
    contradiction_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
) -> ContradictionDetail:
    return service.get_contradiction(case_id, contradiction_id)


@router.post("/contradictions/{contradiction_id}/review", response_model=ContradictionDetail)
def review_contradiction(
    case_id: uuid.UUID,
    contradiction_id: uuid.UUID,
    payload: ContradictionReviewRequest,
    service: AnalysisService = Depends(get_analysis_service),
) -> ContradictionDetail:
    return service.review_contradiction(case_id, contradiction_id, payload)


@router.post(
    "/contradictions/{contradiction_id}/alternatives",
    response_model=ContradictionDetail,
    status_code=status.HTTP_201_CREATED,
)
def add_alternative(
    case_id: uuid.UUID,
    contradiction_id: uuid.UUID,
    payload: AlternativeCreate,
    service: AnalysisService = Depends(get_analysis_service),
) -> ContradictionDetail:
    return service.add_alternative(case_id, contradiction_id, payload)


# --- review queue, history ---------------------------------------------------------


@router.get("/review-queue", response_model=ReviewQueueOut)
def review_queue(
    case_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    limit: int = Query(default=50, ge=1, le=200),
) -> ReviewQueueOut:
    return service.review_queue(case_id, limit=limit)


@router.get("/reviews", response_model=ReviewHistory)
def review_history(
    case_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    target_type: str | None = Query(default=None, max_length=24),
    target_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ReviewHistory:
    return service.reviews(case_id, target_type=target_type, target_id=target_id, limit=limit)


# --- segment corrections -----------------------------------------------------------


@router.get(
    "/evidence/{evidence_id}/segments/{segment_id}/reviews", response_model=SegmentReviewList
)
def segment_reviews(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    segment_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
) -> SegmentReviewList:
    return service.segment_reviews(case_id, evidence_id, segment_id)


@router.post(
    "/evidence/{evidence_id}/segments/{segment_id}/reviews",
    response_model=SegmentReviewList,
    status_code=status.HTTP_201_CREATED,
)
def add_segment_review(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    segment_id: uuid.UUID,
    payload: SegmentReviewCreate,
    service: AnalysisService = Depends(get_analysis_service),
) -> SegmentReviewList:
    return service.add_segment_review(case_id, evidence_id, segment_id, payload)


# --- graph, dashboard, per-evidence summary ----------------------------------------


@router.get("/graph", response_model=GraphOut)
def knowledge_graph(
    case_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    include_claims: bool = Query(default=True),
    entity_type: str | None = Query(default=None, max_length=32),
    evidence_id: uuid.UUID | None = Query(default=None),
    contradictions_only: bool = Query(default=False),
    limit: int = Query(default=250, ge=10, le=1000),
) -> GraphOut:
    return service.graph(
        case_id,
        include_claims=include_claims,
        entity_type=entity_type,
        evidence_id=evidence_id,
        contradictions_only=contradictions_only,
        limit=limit,
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    case_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
    runner: AnalysisRunner = Depends(get_analysis_runner),
) -> DashboardOut:
    return service.dashboard(case_id, runner.method)


@router.get("/evidence/{evidence_id}/analysis-summary", response_model=EvidenceAnalysisSummary)
def evidence_analysis_summary(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    service: AnalysisService = Depends(get_analysis_service),
) -> EvidenceAnalysisSummary:
    return service.evidence_summary(case_id, evidence_id)
