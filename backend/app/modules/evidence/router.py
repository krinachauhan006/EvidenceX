"""HTTP endpoints for evidence, nested under their owning case.

All operations are scoped by case_id so evidence is never reachable through a
different case.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Path, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import BadRequestError
from app.modules.evidence.preview import (
    MAX_DPI,
    MIN_DPI,
    PreviewUnavailableError,
    render_pdf_page,
)
from app.modules.evidence.schemas import EvidenceList, EvidenceOut
from app.modules.evidence.service import EvidenceService

DOWNLOAD_CHUNK_SIZE = 64 * 1024

router = APIRouter(prefix="/api/cases/{case_id}/evidence", tags=["evidence"])


def get_service(db: Session = Depends(get_db)) -> EvidenceService:
    return EvidenceService(db)


@router.post("", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
def upload_evidence(
    case_id: uuid.UUID,
    file: UploadFile = File(...),
    service: EvidenceService = Depends(get_service),
) -> EvidenceOut:
    evidence = service.upload(
        case_id,
        filename=file.filename or "unnamed",
        fileobj=file.file,
    )
    return EvidenceOut.model_validate(evidence)


@router.get("", response_model=EvidenceList)
def list_evidence(
    case_id: uuid.UUID,
    service: EvidenceService = Depends(get_service),
) -> EvidenceList:
    items, total = service.list_for_case(case_id)
    return EvidenceList(
        items=[EvidenceOut.model_validate(e) for e in items],
        total=total,
    )


@router.get("/{evidence_id}", response_model=EvidenceOut)
def get_evidence(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    service: EvidenceService = Depends(get_service),
) -> EvidenceOut:
    return EvidenceOut.model_validate(service.get(case_id, evidence_id))


@router.get("/{evidence_id}/download")
def download_evidence(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    service: EvidenceService = Depends(get_service),
) -> StreamingResponse:
    data = service.open_file(case_id, evidence_id)
    # Serve as a non-executable attachment. nosniff prevents the browser from
    # second-guessing the content type; attachment forces download, never inline
    # execution.
    ascii_name = data.original_filename.encode("ascii", "ignore").decode() or "download"
    disposition = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(data.original_filename)}"
    )
    return StreamingResponse(
        _read_and_close(data.stream),
        media_type=data.mime_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(data.byte_size),
            "X-Content-Type-Options": "nosniff",
        },
        # Also runs after a normal finish, so the handle is released even if the
        # generator is never resumed. close() is idempotent.
        background=BackgroundTask(data.stream.close),
    )


def _read_and_close(stream: BinaryIO) -> Iterator[bytes]:
    """Stream a stored blob in chunks and always release the file handle.

    An open handle blocks deleting the blob on Windows, which would leave an orphan
    file behind after the evidence is deleted.
    """
    try:
        while chunk := stream.read(DOWNLOAD_CHUNK_SIZE):
            yield chunk
    finally:
        stream.close()


@router.get("/{evidence_id}/pages/{page_number}/image")
def pdf_page_image(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    page_number: int = Path(ge=1, le=100_000),
    dpi: int = Query(default=72, ge=MIN_DPI, le=MAX_DPI),
    service: EvidenceService = Depends(get_service),
) -> Response:
    """A rendered PNG of one PDF page (thumbnail/preview). Case-scoped, DPI-capped."""
    data = service.open_file(case_id, evidence_id)
    try:
        if data.mime_type != "application/pdf":
            raise BadRequestError("page previews are only available for PDF evidence")
        if not get_settings().pdf_extraction_enabled:
            raise PreviewUnavailableError("PDF handling is disabled (PDF_EXTRACTION_ENABLED)")
        content = data.stream.read()
    finally:
        data.stream.close()
    png = render_pdf_page(content, page_number, dpi)
    return Response(
        content=png,
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.get("/{evidence_id}/frame")
def video_frame(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    t: float = Query(ge=0, le=86_400),
    width: int = Query(default=640, ge=80, le=1280),
    service: EvidenceService = Depends(get_service),
) -> Response:
    """A JPEG of the video frame at ``t`` seconds, decoded on demand (never stored)."""
    import io as _io

    from app.modules.processing.errors import ExtractionError
    from app.modules.processing.extractors.video import frame_at

    data = service.open_file(case_id, evidence_id)
    try:
        if not data.mime_type.startswith("video/"):
            raise BadRequestError("frames are only available for video evidence")
        content = data.stream.read()
    finally:
        data.stream.close()
    try:
        img = frame_at(content, t, max_width=width)
    except ExtractionError as exc:
        raise BadRequestError(exc.message) from None
    buf = _io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=82)
    return Response(
        content=buf.getvalue(),
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.delete("/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evidence(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    service: EvidenceService = Depends(get_service),
) -> Response:
    service.delete(case_id, evidence_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
