"""Sentence splitting around numbers (extract._SENTENCE) and money amounts (_MONEY).

Regression for the prepared-dataset audit: "approved for 18,400.00 USD." used to be cut
at the decimal point into "...approved for 18,400." and "00 USD.", so the amount was
lost and a meaningless "00 USD" claim appeared. Pure functions; no database."""

from __future__ import annotations

from app.modules.analysis.extract import _SENTENCE, SegmentView, extract_claims


def sentences(text: str) -> list[str]:
    return [m.group(0).strip() for m in _SENTENCE.finditer(text) if m.group(0).strip()]


def pdf(text: str) -> SegmentView:
    return SegmentView(
        id="s1",
        segment_type="pdf_text_block",
        text=text,
        data=None,
        locator={"kind": "pdf", "page": 1, "bbox": [0, 0, 100, 20]},
        engine_confidence=None,
        evidence_type="document",
    )


def claims(text: str):
    return extract_claims([pdf(text)])


def test_usd_amount_with_cents_stays_in_one_sentence():
    text = "Purchase order PO-771 approved for 18,400.00 USD."
    assert sentences(text) == [text]
    (claim,) = claims(text)
    assert claim.quote == text
    assert claim.claim_type == "quantity"
    assert claim.object_value == "18,400.00 USD"
    assert not any(c.object_value == "00 USD" for c in claims(text))


def test_plain_decimal_amount_is_not_split():
    text = "The adjustment was 250.75 after review."
    assert sentences(text) == [text]


def test_inr_amount_is_kept_and_recognised_as_money():
    text = "Advance of 1,250.50 INR was paid to the vendor."
    assert sentences(text) == [text]
    (claim,) = claims(text)
    assert claim.claim_type == "quantity" and claim.object_value == "1,250.50 INR"
    (symbol,) = claims("Advance of ₹1,250.50 was paid.")
    assert symbol.object_value == "₹1,250.50"


def test_sentence_ending_in_a_decimal_number_ends_at_its_full_stop():
    text = "The measured value was 12.5. Sampling continued at the footbridge."
    assert sentences(text) == [
        "The measured value was 12.5.",
        "Sampling continued at the footbridge.",
    ]
    assert sentences("The total came to 250.75") == ["The total came to 250.75"]


def test_several_amounts_in_one_sentence_are_all_captured():
    text = "Invoice INV-771 for 18,940.00 USD exceeds PO-771 at 18,400.00 USD by 540.00 USD."
    assert sentences(text) == [text]
    (claim,) = claims(text)
    assert claim.object_value == "18,940.00 USD"  # the first amount, as before
    assert claim.quote == text
    assert {m.normalized_key for m in claim.mentions} >= {"INV771", "PO771"}


def test_sentence_boundary_after_an_amount_still_splits():
    text = (
        "Payment of 18,940.00 USD was settled. The goods receipt lists 16 units! Was it approved?"
    )
    assert sentences(text) == [
        "Payment of 18,940.00 USD was settled.",
        "The goods receipt lists 16 units!",
        "Was it approved?",
    ]
    first, second = claims(text)
    assert first.object_value == "18,940.00 USD"
    assert second.object_value == "16 units"


def test_dates_and_times_with_dots_are_not_split():
    assert sentences("Odour noticed at about 7.15, source unknown.") == [
        "Odour noticed at about 7.15, source unknown."
    ]
    assert sentences("Filed on 1.5.2026 by the clerk. Reviewed later.") == [
        "Filed on 1.5.2026 by the clerk.",
        "Reviewed later.",
    ]


def test_ordinary_sentence_boundaries_are_unchanged():
    assert sentences("Hello there. Shipment NS-88421 arrived at 10:30 at Gate 4.") == [
        "Hello there.",
        "Shipment NS-88421 arrived at 10:30 at Gate 4.",
    ]
    # A full stop directly after a digit ends the sentence unless another digit follows.
    assert sentences("Unloaded at Bay 3.Then the truck left.") == [
        "Unloaded at Bay 3.",
        "Then the truck left.",
    ]
    assert sentences("Count was 4.\n5 pallets remained.") == ["Count was 4.", "5 pallets remained."]
    assert sentences("Wait... it arrived at 10:30.") == ["Wait...", "it arrived at 10:30."]
