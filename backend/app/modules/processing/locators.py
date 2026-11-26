"""Typed source locators.

A locator says exactly where in the original file a segment came from. It is a
discriminated union on ``kind`` so every format has its own validated shape.

``promoted_columns`` derives the few values that are also stored in indexed
columns (page, start and end time). Deriving them from the locator in one place
guarantees the columns and the JSON can never disagree.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

BBox = tuple[float, float, float, float]


class _Locator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PdfLocator(_Locator):
    kind: Literal["pdf"] = "pdf"
    page: int = Field(ge=1)  # 1-based
    bbox: BBox | None = None  # [x0, y0, x1, y1] in PDF points
    page_width: float | None = Field(default=None, gt=0)
    page_height: float | None = Field(default=None, gt=0)
    unit: Literal["pt"] = "pt"


class ImageLocator(_Locator):
    kind: Literal["image"] = "image"
    bbox: BBox  # [x0, y0, x1, y1] in pixels
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    unit: Literal["px"] = "px"


class AudioLocator(_Locator):
    kind: Literal["audio"] = "audio"
    start: float = Field(ge=0)  # seconds
    end: float = Field(ge=0)

    @model_validator(mode="after")
    def _end_not_before_start(self) -> AudioLocator:
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self


class CsvLocator(_Locator):
    kind: Literal["csv"] = "csv"
    row: int = Field(ge=1)  # 1-based record number, blank records included
    line: int = Field(ge=1)  # first physical line of the record
    column: str | None = None  # None means the whole row


class XlsxLocator(_Locator):
    kind: Literal["xlsx"] = "xlsx"
    sheet: str
    row: int = Field(ge=1)
    range: str  # for example "A12:F12"


class VideoLocator(_Locator):
    """A sampled frame (or a text region on it) at an exact media time."""

    kind: Literal["video"] = "video"
    t: float = Field(ge=0)  # seconds from the start of the video
    frame_width: int = Field(gt=0)
    frame_height: int = Field(gt=0)
    bbox: BBox | None = None  # text region in frame pixels (OCR line), if any
    unit: Literal["px"] = "px"


class EmailLocator(_Locator):
    kind: Literal["email"] = "email"
    part: Literal["header", "body_text", "body_html", "attachment"]
    name: str | None = None  # header name or attachment filename (display only)
    index: int | None = Field(default=None, ge=0)


Locator = Annotated[
    PdfLocator
    | ImageLocator
    | AudioLocator
    | CsvLocator
    | XlsxLocator
    | EmailLocator
    | VideoLocator,
    Field(discriminator="kind"),
]

_adapter: TypeAdapter[Locator] = TypeAdapter(Locator)


def locator_to_json(locator: _Locator) -> dict:
    """Serialize a locator to a JSON-safe dict for storage."""
    return locator.model_dump(mode="json")


def locator_from_json(value: dict) -> Locator:
    """Validate and parse a stored locator."""
    return _adapter.validate_python(value)


def promoted_columns(locator: _Locator) -> tuple[int | None, float | None, float | None]:
    """Return (page, t_start, t_end) for the indexed columns."""
    if isinstance(locator, PdfLocator):
        return locator.page, None, None
    if isinstance(locator, AudioLocator):
        return None, locator.start, locator.end
    if isinstance(locator, VideoLocator):
        return None, locator.t, locator.t
    return None, None, None
