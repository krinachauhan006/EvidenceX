"""EML extractor (Python standard library ``email``).

Nothing is executed, rendered or fetched. Attachments are described (name, type,
size, SHA-256) and never parsed or stored. Nested messages are described as
attachments and are not opened.

Fidelity rules:
- Raw header text is kept next to any parsed form.
- A Date is stored as written. An ISO value is added only when it parses, and the
  timezone is reported as known or unknown. Nothing is converted to UTC.
- Hidden HTML text is kept apart from visible text and flagged, not dropped.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import re
from collections import Counter
from email.message import Message
from typing import Any

from app.modules.processing.errors import CorruptFileError
from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    ExtractionWarning,
    SegmentDraft,
)
from app.modules.processing.extractors.html_text import html_to_text
from app.modules.processing.locators import EmailLocator

HEADER_FIELDS = (
    "From",
    "To",
    "Cc",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "References",
)
ADDRESS_FIELDS = frozenset({"from", "to", "cc"})
_IDENTITY_HEADERS = frozenset(
    {
        "from",
        "to",
        "cc",
        "bcc",
        "sender",
        "reply-to",
        "message-id",
        "received",
        "return-path",
        "mime-version",
        "delivered-to",
    }
)
_OPAQUE_TYPES = frozenset(
    {"application/pkcs7-mime", "application/x-pkcs7-mime", "multipart/encrypted"}
)
_MAX_RAW_HEADER_CHARS = 10_000
_MAX_RECEIVED = 50
_MAX_FILENAME_CHARS = 255
# Control characters, and the bidirectional overrides used to disguise file names.
_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069\u200e\u200f]")


def sanitize_display_name(name: str | None) -> str | None:
    """A file name made safe to show: no control or direction-override characters,
    no path separators, capped in length."""
    if name is None:
        return None
    cleaned = _UNSAFE_NAME_CHARS.sub("", name).replace("/", "_").replace("\\", "_").strip()
    return cleaned[:_MAX_FILENAME_CHARS] or None


def _walk_parts(part: Message):
    """Depth-first walk that does NOT descend into attached messages (message/*).
    A forwarded or attached message is described as an attachment and never opened."""
    yield part
    if part.get_content_type().startswith("message/"):
        return
    if part.is_multipart():
        for child in part.iter_parts():  # type: ignore[attr-defined]
            yield from _walk_parts(child)


def _unfold(raw: str) -> str:
    return re.sub(r"\r?\n[ \t]+", " ", raw).strip()


def _decode_bytes(payload: bytes, charset: str | None) -> tuple[str, str, bool]:
    """Decode with the declared charset when it exists and works, otherwise UTF-8,
    then Windows-1252. Returns (text, encoding_used, fell_back)."""
    if charset:
        try:
            return payload.decode(charset), charset, False
        except (LookupError, UnicodeDecodeError):
            pass
    for encoding in ("utf-8", "cp1252"):
        try:
            return payload.decode(encoding), encoding, bool(charset)
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1"), "latin-1", True


def _parse_addresses(msg: Message, name: str, raw: str) -> list[dict[str, str]]:
    pairs: list[tuple[str, str]] = []
    try:
        header = msg.get(name)
        addresses = getattr(header, "addresses", None)
        if addresses is not None:
            for address in addresses:
                pairs.append((address.display_name, address.addr_spec))
    except Exception:  # noqa: BLE001 - fall back to the lenient parser
        pairs = []
    if not pairs:
        pairs = [(n, a) for n, a in email.utils.getaddresses([_unfold(raw)]) if a or n]
    return [{"display_name": n, "address": a} for n, a in pairs]


def _header_text(msg: Message, name: str, raw: str) -> str:
    try:
        return str(msg.get(name, raw))
    except Exception:  # noqa: BLE001 - a header the parser cannot decode shows raw
        return _unfold(raw)


class EmlExtractor:
    name = "eml"
    version = "1"

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        limits = inp.limits
        try:
            msg = email.message_from_bytes(inp.data, policy=email.policy.default)
        except Exception as exc:  # noqa: BLE001
            raise CorruptFileError("The file could not be parsed as an email message.") from exc

        raw_headers = [(k, v) for k, v in msg.raw_items()]
        header_names = {k.lower() for k, _ in raw_headers}
        if not header_names & _IDENTITY_HEADERS:
            raise CorruptFileError("The file does not contain recognizable email headers.")

        warnings: list[ExtractionWarning] = []
        segments: list[SegmentDraft] = []

        # --- header segments ------------------------------------------------------
        seen: Counter[str] = Counter()
        for field_name in HEADER_FIELDS:
            occurrences = [(k, v) for k, v in raw_headers if k.lower() == field_name.lower()]
            for position, (_, raw) in enumerate(occurrences):
                raw = raw[:_MAX_RAW_HEADER_CHARS]
                data: dict[str, Any] = {"raw": raw}
                lowered = field_name.lower()
                if lowered in ADDRESS_FIELDS:
                    data["addresses"] = _parse_addresses(msg, field_name, raw)
                if lowered == "date":
                    data.update(self._date_fields(raw, warnings))
                segments.append(
                    SegmentDraft(
                        segment_type="email_header",
                        text=_header_text(msg, field_name, raw)[:_MAX_RAW_HEADER_CHARS],
                        locator=EmailLocator(
                            part="header",
                            name=field_name,
                            index=position if len(occurrences) > 1 else None,
                        ),
                        data=data,
                    )
                )
            if len(occurrences) > 1:
                warnings.append(
                    ExtractionWarning(
                        "duplicate_header",
                        f"The header '{field_name}' appears {len(occurrences)} times. "
                        "All occurrences were kept.",
                        {"header": field_name, "count": len(occurrences)},
                    )
                )
            seen[field_name] += len(occurrences)

        # --- body parts and attachments -------------------------------------------
        body_index = {"body_text": 0, "body_html": 0}
        attachment_index = 0
        total_chars = 0
        stop = False
        opaque = False
        defects: Counter[str] = Counter(type(d).__name__ for d in msg.defects)
        structure: list[str] = []
        hidden_parts = 0
        charset_fallbacks = 0
        replaced_parts = 0
        truncated = False

        for part in _walk_parts(msg):
            structure.append(part.get_content_type())
            if part is not msg:
                defects.update(type(d).__name__ for d in part.defects)
            content_type = part.get_content_type()
            if content_type in _OPAQUE_TYPES:
                opaque = True
                continue
            if part.is_multipart() and not content_type.startswith("message/"):
                continue

            disposition = self._disposition(part)
            filename = self._filename(part)
            is_attachment = (
                disposition == "attachment"
                or filename is not None
                or content_type.startswith("message/")
                or not content_type.startswith("text/")
            )

            if is_attachment:
                segments.append(self._attachment_segment(part, filename, attachment_index))
                attachment_index += 1
                continue

            if stop:
                continue
            kind = "body_html" if content_type == "text/html" else "body_text"
            text, fallback, replaced = self._part_text(part)
            charset_fallbacks += fallback is not None
            replaced_parts += replaced
            if fallback is not None:
                warnings.append(
                    ExtractionWarning(
                        "charset_fallback",
                        "The declared character set could not be used, so the text was "
                        f"decoded as {fallback['used']}.",
                        fallback,
                    )
                )

            data = {"content_type": content_type}
            if kind == "body_html":
                converted = html_to_text(text)
                data["links"] = converted.links
                data["html_chars"] = len(text)
                if converted.has_hidden_content:
                    hidden_parts += 1
                    data["hidden_text"] = converted.hidden_text
                text = converted.text
                if not text and not converted.links and not converted.has_hidden_content:
                    continue  # markup only: nothing to record
            elif not text.strip():
                continue  # an empty body is not content

            if total_chars + len(text) > limits.max_extracted_chars:
                text = text[: max(0, limits.max_extracted_chars - total_chars)]
                truncated = stop = True
            total_chars += len(text)

            segments.append(
                SegmentDraft(
                    segment_type="email_body_html" if kind == "body_html" else "email_body_text",
                    text=text,
                    locator=EmailLocator(part=kind, index=body_index[kind]),
                    data=data,
                )
            )
            body_index[kind] += 1

        # --- warnings -------------------------------------------------------------
        if hidden_parts:
            warnings.append(
                ExtractionWarning(
                    "html_hidden_content",
                    "The HTML body contains text inside hidden elements. It is kept "
                    "separately in the segment data, not mixed into the visible text.",
                    {"parts": hidden_parts},
                )
            )
        if replaced_parts:
            warnings.append(
                ExtractionWarning(
                    "decoding_replacements",
                    "Some characters could not be decoded and were replaced.",
                    {"parts": replaced_parts},
                )
            )
        for defect, count in sorted(defects.items()):
            warnings.append(
                ExtractionWarning(
                    "mime_defect",
                    f"The message has a MIME defect: {defect}.",
                    {"defect": defect, "count": count},
                )
            )
        if opaque:
            warnings.append(
                ExtractionWarning(
                    "body_not_readable",
                    "The message body is encrypted or opaque and could not be read.",
                )
            )
        if truncated:
            warnings.append(
                ExtractionWarning(
                    "char_limit_reached",
                    "Extraction stopped because the total text limit was reached.",
                    {"limit": limits.max_extracted_chars},
                )
            )
        if not body_index["body_text"] and not body_index["body_html"] and not opaque:
            warnings.append(ExtractionWarning("no_body", "The message has no readable body."))

        outcome = "partial" if (opaque or truncated) else "ok"
        metadata = {
            "header_count": len(raw_headers),
            "is_multipart": msg.is_multipart(),
            "mime_structure": structure[:100],
            "body_text_parts": body_index["body_text"],
            "body_html_parts": body_index["body_html"],
            "attachment_count": attachment_index,
            "reply_to": self._raw_all(raw_headers, "reply-to"),
            "return_path": self._raw_all(raw_headers, "return-path"),
            "received": self._raw_all(raw_headers, "received")[:_MAX_RECEIVED],
        }
        return ExtractionResult(self.name, self.version, outcome, segments, metadata, warnings)

    # --- helpers --------------------------------------------------------------

    @staticmethod
    def _raw_all(raw_headers: list[tuple[str, str]], name: str) -> list[str]:
        return [_unfold(v)[:_MAX_RAW_HEADER_CHARS] for k, v in raw_headers if k.lower() == name]

    @staticmethod
    def _date_fields(raw: str, warnings: list[ExtractionWarning]) -> dict[str, Any]:
        try:
            parsed = email.utils.parsedate_to_datetime(_unfold(raw))
        except (TypeError, ValueError, IndexError):
            warnings.append(
                ExtractionWarning(
                    "date_unparseable",
                    "The Date header is not a valid date. It is kept as written.",
                )
            )
            return {"date_iso": None, "tz_known": None, "date_precision": "unknown"}
        return {
            "date_iso": parsed.isoformat(),
            "tz_known": parsed.tzinfo is not None,
            "date_precision": "exact",
        }

    @staticmethod
    def _disposition(part: Message) -> str | None:
        try:
            return part.get_content_disposition()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _filename(part: Message) -> str | None:
        try:
            name = part.get_filename()
        except Exception:  # noqa: BLE001 - malformed parameter encoding
            name = None
        return sanitize_display_name(name) if name else None

    @staticmethod
    def _part_text(part: Message) -> tuple[str, dict[str, Any] | None, bool]:
        """Text of a body part: (text, fallback_detail_or_None, had_replacements)."""
        charset = part.get_content_charset()
        try:
            text = part.get_content()
            if isinstance(text, str):
                return text, None, "\ufffd" in text
        except Exception:  # noqa: BLE001 - unknown charset or broken encoding
            pass
        payload = part.get_payload(decode=True) or b""
        text, used, fell_back = _decode_bytes(payload, charset)
        detail = {"declared": charset, "used": used} if fell_back else None
        return text, detail, "\ufffd" in text

    @staticmethod
    def _attachment_segment(part: Message, filename: str | None, index: int) -> SegmentDraft:
        content_type = part.get_content_type()
        if part.is_multipart() or content_type.startswith("message/"):
            try:
                payload = part.as_bytes()
            except Exception:  # noqa: BLE001
                payload = b""
        else:
            payload = part.get_payload(decode=True) or b""
        size = len(payload)
        label = filename or "(unnamed)"
        content_id = part.get("Content-ID")
        return SegmentDraft(
            segment_type="email_attachment",
            text=f"{label} ({content_type}, {size} bytes)",
            locator=EmailLocator(part="attachment", name=filename, index=index),
            data={
                "filename": filename,
                "content_type": content_type,
                "size": size,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "disposition": EmlExtractor._disposition(part),
                "content_id": str(content_id)[:200] if content_id else None,
                "content_stored": False,
            },
        )
