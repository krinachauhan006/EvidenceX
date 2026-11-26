"""Phase 2 pure rules: dates, event proposals and comparisons, sequence checks,
lexical search, the report language guard and OCR preprocessing box mapping.

All inputs are synthetic.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from app.modules.analysis import events as ev
from app.modules.analysis import search, temporal
from app.modules.analysis.report_text import LanguageGuardError, cite, guard
from app.modules.processing.extractors import ocr_preprocess as pre

# --- dates ------------------------------------------------------------------------


def test_dates_in_reads_common_formats_and_flags_ambiguity():
    found = temporal.dates_in("On 2026-10-12, then 13 October 2026, and October 14, 2026.")
    assert [r.value for r in found] == ["2026-10-12", "2026-10-13", "2026-10-14"]
    assert all(r.precision == "day" and r.source == "sentence" for r in found)
    (amb,) = temporal.dates_in("Signed 03/04/2026")
    assert amb.value is None and amb.precision == "ambiguous"
    assert amb.alternatives == ["2026-03-04", "2026-04-03"]
    (clear,) = temporal.dates_in("Signed 25/04/2026")
    assert clear.value == "2026-04-25"
    assert temporal.dates_in("31 February 2026") == []  # invalid dates are not invented


def test_claim_date_prefers_sentence_then_email_then_document():
    assert temporal.claim_date("Arrived 10:30 on 12 October 2026").precision == "day"
    from_mail = temporal.claim_date("Arrived 10:30", email_date_iso="2026-10-12T14:00:00+00:00")
    assert (from_mail.value, from_mail.source) == ("2026-10-12", "email_header")
    inherited = temporal.claim_date("Arrived 10:30", doc_date="2026-10-12")
    assert (inherited.value, inherited.precision) == ("2026-10-12", "inherited_day")
    unknown = temporal.claim_date("Arrived 10:30")
    assert (unknown.value, unknown.precision) == (None, "unknown")


def test_document_date_requires_a_single_distinct_date():
    assert temporal.document_date(["12 October 2026", "2026-10-12"]) == "2026-10-12"
    assert temporal.document_date(["12 October 2026", "13 October 2026"]) is None


def test_tz_and_day_comparability():
    assert temporal.tz_of({"value": "2026-10-12T10:30:00+05:30"}) == "+05:30"
    assert temporal.tz_of({"value": "10:30"}) is None
    assert temporal.comparable("2026-10-12", "2026-10-12") == "same_day"
    assert temporal.comparable("2026-10-12", "2026-10-13") == "different_day"
    assert temporal.comparable("2026-10-12", None) == "unknown_day"


# --- event proposals ----------------------------------------------------------------


def info(
    cid: str,
    evidence: str,
    quote: str,
    minutes: int | None,
    *,
    predicate: str = "arrival",
    date: str | None = "2026-10-12",
    precision: str = "day",
    entities: list | None = None,
    uncertainty: list | None = None,
    tz: str | None = None,
    span: int = 0,
) -> ev.ClaimInfo:
    return ev.ClaimInfo(
        id=cid,
        evidence_id=evidence,
        evidence_name=f"{evidence}.txt",
        modality="document",
        quote=quote,
        predicate_key=predicate,
        interval=None if minutes is None else (minutes, minutes + span),
        time_raw=None if minutes is None else f"{minutes // 60:02d}:{minutes % 60:02d}",
        time_precision="exact" if not span else "approximate",
        date=date,
        date_precision=precision if date else "unknown",
        date_source="sentence" if date else None,
        tz=tz,
        uncertainty=uncertainty or [],
        entities=entities or [],
    )


PLATE = [("vehicle", "kx4471", "KX-4471", "ent-1")]


def test_attribution_and_object_words():
    assert ev.attribution_of("Delivery receipt: Truck arrived 10:30") == "delivery receipt"
    assert ev.attribution_of("A separate witness statement says the van left") == (
        "witness statement"
    )
    assert ev.attribution_of("Truck arrived: 10:30") is None  # not a source noun
    assert ev.object_classes("The lorry and two parcels") == ["truck", "parcel"]


def test_identifier_anchor_beats_object_word_for_the_same_claims():
    a = info("a", "e1", "Gate log: truck KX-4471 arrived 10:30", 630, entities=PLATE)
    b = info("b", "e2", "Driver statement: truck KX-4471 arrived 12:15", 735, entities=PLATE)
    (p,) = ev.propose_events([a, b])
    assert p.anchor_kind == "vehicle" and p.event_type == "arrival"
    assert p.association_confidence == pytest.approx(0.70 + 0.05 + 0.05)
    assert p.link_basis == "identifier"
    assert "no account states a time zone" in p.missing_links


def test_object_only_link_is_weak_and_says_why():
    a = info("a", "e1", "Gate log: the truck arrived 10:30", 630)
    b = info("b", "e2", "Witness statement: a truck arrived 12:15", 735)
    (p,) = ev.propose_events([a, b])
    assert p.anchor_kind == "object" and p.association_confidence < 0.5
    assert any("may concern different trucks" in m for m in p.missing_links)


def test_object_word_never_joins_explicitly_different_vehicles():
    other = [("vehicle", "mh1234", "MH-1234", "ent-2")]
    a = info("a", "e1", "Gate log: the truck KX-4471 arrived 10:30", 630, entities=PLATE)
    b = info("b", "e2", "Witness statement: a truck MH-1234 arrived 12:15", 735, entities=other)
    assert ev.propose_events([a, b]) == []
    # One account without a plate is still ambiguous-but-possible: proposed, weak.
    c = info("c", "e3", "Clerk note: a truck arrived 12:00", 720)
    props = ev.propose_events([a, c])
    assert [p.anchor_kind for p in props] == ["object"]
    assert ev.explicitly_different([a, b]) and not ev.explicitly_different([a, c])


def test_planned_and_actual_events_are_never_grouped():
    a = info("a", "e1", "Gate log: truck KX-4471 arrived 10:30", 630, entities=PLATE)
    b = info(
        "b",
        "e2",
        "Schedule: truck KX-4471 expected 09:00",
        540,
        predicate="planned_arrival",
        entities=PLATE,
    )
    assert ev.propose_events([a, b]) == []


def test_one_account_is_not_an_event_but_two_attributed_accounts_in_one_file_are():
    a = info("a", "e1", "Delivery receipt: truck KX-4471 arrived 10:30", 630, entities=PLATE)
    same = info("b", "e1", "Delivery receipt: truck KX-4471 arrived 10:35", 635, entities=PLATE)
    assert ev.propose_events([a, same]) == []
    other = info("c", "e1", "Witness statement: truck KX-4471 arrived 12:15", 735, entities=PLATE)
    (p,) = ev.propose_events([a, other])
    assert {m.attribution for m in p.members} == {"delivery receipt", "witness statement"}


def test_different_days_are_separate_proposals_and_undated_join_a_single_day():
    a = info("a", "e1", "Gate log: truck KX-4471 arrived 10:30", 630, entities=PLATE)
    b = info("b", "e2", "Driver log: truck KX-4471 arrived 10:40", 640, entities=PLATE)
    c = info("c", "e3", "Clerk note: truck KX-4471 arrived 11:00", 660, date=None, entities=PLATE)
    (p,) = ev.propose_events([a, b, c])
    assert len(p.members) == 3 and p.event_date == "2026-10-12"
    assert p.date_precision == "inherited_day"  # one account does not state the date
    assert any("does not state a date" in m for m in p.missing_links)
    d = info(
        "d", "e4", "Guard log: truck KX-4471 arrived 9:00", 540, date="2026-10-13", entities=PLATE
    )
    # The 13 October account stands alone, so it is not grouped with the 12 October ones.
    (only,) = ev.propose_events([a, b, d])
    assert only.event_date == "2026-10-12" and {m.claim.id for m in only.members} == {"a", "b"}


def test_proposals_are_deterministic():
    a = info("a", "e1", "Gate log: truck KX-4471 arrived 10:30", 630, entities=PLATE)
    b = info("b", "e2", "Driver statement: truck KX-4471 arrived 12:15", 735, entities=PLATE)
    assert [p.signature for p in ev.propose_events([a, b])] == [
        p.signature for p in ev.propose_events([b, a])
    ]


# --- comparing accounts ---------------------------------------------------------------


def member(c: ev.ClaimInfo) -> ev.Member:
    attr = ev.attribution_of(c.quote)
    return ev.Member(c, attr, ev.account_label(c, attr), [])


@pytest.mark.parametrize(
    ("a_kwargs", "b_kwargs", "expected"),
    [
        ({"minutes": 630}, {"minutes": 735}, "conflict_candidate"),
        ({"minutes": 630}, {"minutes": 636}, "within_tolerance"),
        (
            {"minutes": 630},
            {"minutes": 644, "uncertainty": ["hedged wording: 'around'"]},
            "possible_rounding",
        ),
        ({"minutes": 630}, {"minutes": 690}, "possible_timezone"),
        ({"minutes": 630, "tz": "+00:00"}, {"minutes": 690, "tz": "+01:00"}, "conflict_candidate"),
        ({"minutes": 630}, {"minutes": None}, "missing_time"),
        ({"minutes": 630}, {"minutes": 735, "date": "2026-10-13"}, "different_day"),
        ({"minutes": 600, "span": 60}, {"minutes": 630}, "approximate_overlap"),
    ],
)
def test_compare_pair_classifies_without_overclaiming(a_kwargs, b_kwargs, expected):
    a = info("a", "e1", "Gate log: truck arrived", a_kwargs.pop("minutes"), **a_kwargs)
    b = info("b", "e2", "Witness statement: truck arrived", b_kwargs.pop("minutes"), **b_kwargs)
    result = ev.compare_pair(member(a), member(b))
    assert result.classification == expected, result.explanation
    assert result.is_candidate == (expected in ("conflict_candidate", "possible_timezone"))


def test_same_account_is_never_compared_against_itself():
    a = info("a", "e1", "Gate log: truck arrived", 630)
    b = info("b", "e1", "Gate log: truck arrived", 735)
    assert ev.compare_pair(member(a), member(b)).classification == "same_account"


def test_sequence_conflict_needs_reversed_order_beyond_tolerance():
    dispatch = member(info("a", "e1", "Dispatch log: truck left", 780, predicate="dispatch"))
    arrival = member(info("b", "e2", "Gate log: truck arrived", 690))
    events = [
        ("dispatch", "vehicle", "kx4471", "2026-10-12", [dispatch]),
        ("arrival", "vehicle", "kx4471", "2026-10-12", [arrival]),
    ]
    ((first, later, why),) = ev.sequence_conflicts(events)
    assert first is dispatch and later is arrival and "usual order" in why
    ok = member(info("c", "e1", "Dispatch log: truck left", 600, predicate="dispatch"))
    events[0] = ("dispatch", "vehicle", "kx4471", "2026-10-12", [ok])
    assert ev.sequence_conflicts(events) == []


# --- search ----------------------------------------------------------------------------


def docs() -> list[search.Doc]:
    return [
        search.Doc("claim", "1", "The lorry reached Warehouse A at 10:30.", "Gate log"),
        search.Doc("claim", "2", "Invoice INV-2207 was paid on 12 October.", "Ledger"),
        search.Doc("claim", "3", "The witness saw the truck arrive at 12:15.", "Statement"),
        search.Doc("segment", "4", "Café opening hours", "Notice"),
    ]


def test_search_uses_synonyms_stemming_and_explains_matches():
    hits, terms = search.rank(docs(), "truck arrival")
    assert {h.doc.id for h in hits} >= {"1", "3"}
    assert hits[0].doc.id == "3"  # exact words beat synonyms
    lorry = next(h for h in hits if h.doc.id == "1")
    assert "synonym" in lorry.why
    assert {"arrive", "lorry"} <= set(terms)


def test_search_tolerates_typos_and_accents():
    hits, _ = search.rank(docs(), "invoce")  # a dropped letter
    assert hits and hits[0].doc.id == "2" and "close spelling" in hits[0].why
    # Transposed letters are a known limit of the trigram check: no hit, not a wrong one.
    assert search.rank(docs(), "invioce")[0] == []
    hits, _ = search.rank(docs(), "cafe")
    assert hits and hits[0].doc.id == "4"


def test_search_ignores_stop_words_only_queries():
    assert search.rank(docs(), "the of and") == ([], [])
    assert "Not embedding-based" in search.METHOD_LABEL


def test_excerpt_centres_on_the_match():
    text = "x" * 400 + " the truck arrived " + "y" * 400
    snippet = search.excerpt(text, ["truck"])
    assert "truck" in snippet and snippet.startswith("…") and snippet.endswith("…")


# --- report wording ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "The driver lied about the time.",
        "This proves the receipt is false.",
        "The document is genuine.",
        "The suspect is guilty.",
        "The invoice was authenticated.",
    ],
)
def test_guard_rejects_adjudicating_language(sentence):
    with pytest.raises(LanguageGuardError):
        guard(sentence)


def test_guard_allows_neutral_wording():
    text = "Two accounts appear to differ by 105 minutes; a reviewer has not confirmed this."
    assert guard(text) == text


def test_citations_name_the_exact_location():
    assert cite("r.pdf", {"kind": "pdf", "page": 2, "bbox": [0, 0, 10, 20]}) == (
        "r.pdf, page 2, region (0,0)–(10,20) pt"
    )
    audio = cite("call.wav", {"kind": "audio", "start": 65.0, "end": 70.0})
    assert audio == "call.wav, audio 00:01:05–00:01:10"
    video = cite("cam.mp4", {"kind": "video", "t": 4.0, "bbox": [1, 2, 3, 4]})
    assert video == "cam.mp4, video frame at 00:00:04 (text region)"
    assert cite("m.eml", {"kind": "email", "part": "header", "name": "Date"}) == (
        "m.eml, email header 'Date'"
    )
    assert cite("x", None) == "x, location not recorded"


# --- OCR preprocessing -----------------------------------------------------------------------


def test_map_box_is_identity_without_rotation():
    ctx = {"w": 400, "h": 300, "rot90": 0, "skew": 0.0, "rw": 400, "rh": 300}
    assert pre.map_box([10, 20, 50, 60], ctx) == [10, 20, 50, 60]
    data = {"text": ["a"], "left": [1], "top": [2], "width": [3], "height": [4]}
    assert pre.map_data_back(data, ctx) == data


def test_map_box_undoes_a_180_degree_rotation():
    ctx = {"w": 400, "h": 300, "rot90": 180, "skew": 0.0, "rw": 400, "rh": 300}
    assert pre.map_box([10, 20, 50, 60], ctx) == [350, 240, 390, 280]


def test_map_box_undoes_a_90_degree_rotation_onto_the_original():
    # Original 400x300 with a mark at (300..340, 40..60). Rotating clockwise by 90 for
    # OCR (PIL rotate(-90, expand=True)) gives a 300x400 image.
    original = Image.new("L", (400, 300), 255)
    ImageDraw.Draw(original).rectangle((300, 40, 340, 60), fill=0)
    rotated = original.rotate(-90, expand=True, fillcolor=255)
    x0, y0, x1, y1 = rotated.point(lambda p: 255 - p).getbbox()
    ctx = {"w": 400, "h": 300, "rot90": 90, "skew": 0.0, "rw": 300, "rh": 400}
    mx0, my0, mx1, my1 = pre.map_box([x0, y0, x1, y1], ctx)
    assert abs(mx0 - 300) <= 2 and abs(my0 - 40) <= 2
    assert abs(mx1 - 341) <= 2 and abs(my1 - 61) <= 2


def test_estimate_skew_finds_a_small_rotation():
    img = Image.new("L", (600, 400), 255)
    draw = ImageDraw.Draw(img)
    for y in range(40, 380, 30):
        draw.rectangle((40, y, 560, y + 8), fill=0)
    assert pre.estimate_skew(img) == 0.0
    tilted = img.rotate(3, expand=False, fillcolor=255)
    angle = pre.estimate_skew(tilted)
    assert 2.0 <= abs(angle) <= 4.0
    # Correcting by the estimate straightens the lines again.
    assert pre.estimate_skew(tilted.rotate(angle, expand=False, fillcolor=255)) == 0.0


def test_prepare_without_osd_records_steps_and_keeps_size(monkeypatch):
    monkeypatch.setattr(pre, "_osd_rotation", lambda image, options: 0)
    img = Image.new("RGB", (200, 120), (240, 240, 240))
    processed, ctx = pre.prepare(img, {})
    assert processed.size == (200, 120) and ctx["steps"][0] == "contrast"
    assert (ctx["w"], ctx["h"], ctx["rot90"]) == (200, 120, 0)


# --- entity resolution tiers -------------------------------------------------------------


def test_candidate_tiers():
    from app.modules.analysis.extract import assess_candidate

    exact = assess_candidate(("shipment", "NS88421", "NS88421"), ("identifier", "NS88421", "x"))
    assert exact["tier"] == "exact" and exact["score"] == 0.9
    strong = assess_candidate(("shipment", "NS88421", "NS88421"), ("identifier", "88421", "88421"))
    assert strong["tier"] == "strong"
    weak = assess_candidate(("shipment", "NS88421", "a"), ("shipment", "NS88427", "b"))
    assert weak["tier"] == "weak" and any(f["effect"] == "-" for f in weak["factors"])
    assert (
        assess_candidate(
            ("shipment", "NS88421", "a"), ("shipment", "NS88427", "b"), misreading_possible=False
        )
        is None
    )
    series = assess_candidate(("identifier", "INV5521", "a"), ("identifier", "PO5521", "b"))
    assert series["tier"] == "conflicting"
    assert {f["effect"] for f in series["factors"]} == {"+", "-"}


def test_contacts_with_the_same_name_are_conflicting_not_merged():
    from app.modules.analysis.extract import assess_candidate

    same_name = assess_candidate(
        ("contact", "ravi@example.org", "Ravi Kumar"),
        ("contact", "r.kumar@example.net", "Ravi  Kumar"),
    )
    assert same_name["tier"] == "conflicting"
    assert "different people can share a name" in same_name["factors"][1]["detail"]
    other = assess_candidate(
        ("contact", "a@example.org", "a@example.org"), ("contact", "b@example.org", "b@example.org")
    )
    assert other is None
    assert assess_candidate(("contact", "a@example.org", "Ann"), ("person", "ann", "Ann")) is None
