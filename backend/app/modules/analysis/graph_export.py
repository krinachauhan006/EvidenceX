"""Knowledge-graph exports from stored case data: JSON, GraphML and a readable PDF.

The PDF never squeezes a large graph onto one page:
- page 1: overview of evidence, entities, events and potential inconsistencies
  (claims left out), limited to the most connected nodes when large;
- one focused page per confirmed/proposed event and per potential inconsistency,
  showing only its neighbourhood;
- a written list of the most important connections with their sources.
Layout is a deterministic spring layout (networkx, fixed seed).
"""

from __future__ import annotations

import io
import json
from collections import Counter
from typing import Any

import networkx as nx

from app.modules.analysis.report_text import DISCLAIMER, esc
from app.modules.analysis.schemas import GraphOut

NODE_STYLE = {
    "evidence": ((0.17, 0.25, 0.38), (0.55, 0.66, 0.80), "Evidence item"),
    "claim": ((0.30, 0.34, 0.42), (0.62, 0.66, 0.73), "Claim"),
    "entity": ((0.07, 0.36, 0.40), (0.30, 0.74, 0.76), "Entity"),
    "event": ((0.18, 0.20, 0.45), (0.55, 0.58, 0.92), "Event (proposed / confirmed)"),
    "contradiction": ((0.55, 0.36, 0.02), (0.96, 0.62, 0.04), "Potential inconsistency"),
}
EDGE_STYLE = {
    "contains": ((0.6, 0.64, 0.7), None, "contains"),
    "mentions": ((0.3, 0.7, 0.72), None, "mentions"),
    "conflicts": ((0.96, 0.62, 0.04), None, "potential inconsistency"),
    "account_of": ((0.45, 0.5, 0.9), [3, 2], "account of event"),
    "mentions_same_entity": ((0.5, 0.55, 0.62), [1, 2], "same entity"),
}
OVERVIEW_MAX = 60


def to_networkx(graph: GraphOut) -> nx.Graph:
    g = nx.Graph()
    for n in graph.nodes:
        g.add_node(
            n.id,
            kind=n.kind,
            label=n.label,
            sublabel=n.sublabel or "",
            status=n.status or "",
            ref_id=str(n.ref_id),
        )
    for e in graph.edges:
        if e.source in g and e.target in g:
            g.add_edge(e.source, e.target, kind=e.kind, label=e.label or "")
    return g


def to_json(graph: GraphOut, case: dict[str, Any]) -> bytes:
    payload = {
        "format": "evidencex-graph/1",
        "case": case,
        "note": "Relationships are extracted or reviewed associations, not verified facts.",
        "nodes": [n.model_dump(mode="json") for n in graph.nodes],
        "edges": [e.model_dump(mode="json") for e in graph.edges],
        "truncated": graph.truncated,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def to_graphml(graph: GraphOut) -> bytes:
    buf = io.BytesIO()
    nx.write_graphml(to_networkx(graph), buf, encoding="utf-8")
    return buf.getvalue()


def _layout(g: nx.Graph) -> dict[str, tuple[float, float]]:
    if g.number_of_nodes() == 0:
        return {}
    if g.number_of_nodes() == 1:
        return {next(iter(g.nodes)): (0.0, 0.0)}
    k = 1.6 / max(1, g.number_of_nodes()) ** 0.5
    pos = nx.spring_layout(g, seed=7, k=k, iterations=120)
    return {n: (float(x), float(y)) for n, (x, y) in pos.items()}


def _draw(page: Any, g: nx.Graph, rect: Any, title: str, subtitle: str) -> None:
    import pymupdf

    page.insert_text((rect.x0, rect.y0 - 22), title[:90], fontsize=13, color=(0.05, 0.1, 0.18))
    page.insert_text((rect.x0, rect.y0 - 8), subtitle[:140], fontsize=8, color=(0.36, 0.40, 0.47))
    pos = _layout(g)
    if not pos:
        page.insert_text((rect.x0, rect.y0 + 20), "Nothing to show for this view.", fontsize=10)
        return
    xs, ys = [p[0] for p in pos.values()], [p[1] for p in pos.values()]
    span_x, span_y = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
    pad = 40

    def place(n: str) -> Any:
        x, y = pos[n]
        return pymupdf.Point(
            rect.x0 + pad + (x - min(xs)) / span_x * (rect.width - 2 * pad),
            rect.y0 + pad + (y - min(ys)) / span_y * (rect.height - 2 * pad),
        )

    shape = page.new_shape()
    for a, b, data in g.edges(data=True):
        color, dash, _ = EDGE_STYLE.get(data.get("kind", ""), ((0.6, 0.6, 0.6), None, ""))
        shape.draw_line(place(a), place(b))
        shape.finish(
            color=color,
            width=1.4 if data.get("kind") == "conflicts" else 0.6,
            dashes=f"[{' '.join(map(str, dash))}] 0" if dash else None,
            stroke_opacity=0.8,
        )
    shape.commit()
    for n, data in g.nodes(data=True):
        p = place(n)
        fill, stroke, _ = NODE_STYLE.get(data["kind"], NODE_STYLE["claim"])
        r = 7 if data["kind"] in ("entity", "event", "evidence") else 5
        s = page.new_shape()
        if data["kind"] == "contradiction":
            # Quad(ul, ur, ll, lr) = (top, right, left, bottom) draws a diamond.
            s.draw_quad(
                pymupdf.Quad(p + (0, -r - 1), p + (r + 1, 0), p + (-r - 1, 0), p + (0, r + 1))
            )
        elif data["kind"] == "evidence":
            s.draw_rect(pymupdf.Rect(p.x - r, p.y - r * 0.75, p.x + r, p.y + r * 0.75))
        else:
            s.draw_circle(p, r)
        dashed = data["kind"] == "event" and data.get("status") == "proposed"
        s.finish(fill=fill, color=stroke, width=1.2, dashes="[2 1] 0" if dashed else None)
        s.commit()
        if data["kind"] != "claim" or g.number_of_nodes() <= 25:
            label = data["label"] if len(data["label"]) <= 30 else data["label"][:29] + "…"
            page.insert_text((p.x + r + 2, p.y + 3), label, fontsize=6.5, color=(0.12, 0.16, 0.24))


def _legend(page: Any, x: float, y: float) -> None:
    import pymupdf

    page.insert_text((x, y), "Legend", fontsize=9, color=(0.05, 0.1, 0.18))
    for i, (_k, (fill, stroke, label)) in enumerate(NODE_STYLE.items()):
        s = page.new_shape()
        s.draw_circle(pymupdf.Point(x + 5, y + 12 + i * 12), 4)
        s.finish(fill=fill, color=stroke)
        s.commit()
        page.insert_text((x + 14, y + 15 + i * 12), label, fontsize=7.5)
    base = y + 12 + len(NODE_STYLE) * 12
    for i, (_k, (color, dash, label)) in enumerate(EDGE_STYLE.items()):
        s = page.new_shape()
        yy = base + 4 + i * 11
        s.draw_line(pymupdf.Point(x, yy), pymupdf.Point(x + 12, yy))
        s.finish(color=color, width=1.2, dashes=f"[{' '.join(map(str, dash))}] 0" if dash else None)
        s.commit()
        page.insert_text((x + 16, yy + 3), label, fontsize=7.5)
    page.insert_text(
        (x, base + 4 + len(EDGE_STYLE) * 11 + 8),
        "Dashed event outline = proposed, solid = confirmed by a reviewer.",
        fontsize=7,
    )


def graph_pdf(graph: GraphOut, case: dict[str, Any], *, scope: str) -> tuple[bytes, int, dict]:
    import pymupdf

    g = to_networkx(graph)
    doc = pymupdf.open()
    paper = pymupdf.paper_rect("a4-l")
    w, h = paper.width, paper.height
    area = pymupdf.Rect(36, 76, w - 200, h - 40)
    # 1. overview without claims, most connected nodes first
    overview = g.subgraph([n for n, d in g.nodes(data=True) if d["kind"] != "claim"]).copy()
    for n, d in g.nodes(data=True):  # keep evidence-entity links through claims
        if d["kind"] == "claim":
            nbrs = [m for m in g.neighbors(n) if g.nodes[m]["kind"] != "claim"]
            for i, a in enumerate(nbrs):
                for b in nbrs[i + 1 :]:
                    if a in overview and b in overview and not overview.has_edge(a, b):
                        kinds = {g.nodes[a]["kind"], g.nodes[b]["kind"]}
                        kind = (
                            "conflicts"
                            if "contradiction" in kinds
                            else ("account_of" if "event" in kinds else "mentions")
                        )
                        overview.add_edge(a, b, kind=kind, label="via claim")
    shown = overview
    note = ""
    if overview.number_of_nodes() > OVERVIEW_MAX:
        keep = sorted(overview.degree, key=lambda x: (-x[1], x[0]))[:OVERVIEW_MAX]
        must = [n for n, d in overview.nodes(data=True) if d["kind"] in ("contradiction", "event")]
        shown = overview.subgraph({n for n, _ in keep} | set(must[:20])).copy()
        note = (
            f" Showing the {shown.number_of_nodes()} most connected of "
            f"{overview.number_of_nodes()} nodes."
        )
    page = doc.new_page(width=w, height=h)
    counts = Counter(d["kind"] for _, d in g.nodes(data=True))
    _draw(
        page,
        shown,
        area,
        f"Knowledge graph — {case['title']}",
        f"Overview ({scope}). Claims are folded into their evidence-entity links." + note,
    )
    _legend(page, w - 185, 90)
    page.insert_text((w - 185, h - 120), "Counts in this export:", fontsize=8)
    for i, (k, v) in enumerate(sorted(counts.items())):
        page.insert_text((w - 185, h - 108 + i * 10), f"{k}: {v}", fontsize=7.5)
    # 2. focused pages
    focus = [n for n, d in g.nodes(data=True) if d["kind"] in ("contradiction", "event")]
    for n in focus[:30]:
        hood = {n, *g.neighbors(n)}
        for m in list(hood):
            hood |= {x for x in g.neighbors(m) if g.nodes[x]["kind"] in ("evidence", "entity")}
        sub = g.subgraph(list(hood)[:45]).copy()
        page = doc.new_page(width=w, height=h)
        d = g.nodes[n]
        status = {
            "proposed": "proposed (not reviewed)",
            "confirmed": "confirmed by a reviewer",
            "unreviewed": "awaiting review",
            "rejected": "rejected",
        }.get(d["status"], d["status"])
        _draw(page, sub, area, f"Focus: {d['label']}", f"{d['kind']} · {status}")
        _legend(page, w - 185, 90)
        sources = sorted(
            sub.nodes[x]["label"] for x in sub.nodes if sub.nodes[x]["kind"] == "evidence"
        )
        page.insert_text((w - 185, h - 150), "Sources in this view:", fontsize=8)
        for i, label in enumerate(sources[:8]):
            name = label if len(label) <= 34 else label[:33] + "…"
            page.insert_text((w - 185, h - 138 + i * 10), f"• {name}", fontsize=7.5)
        if len(sources) > 8:
            page.insert_text(
                (w - 185, h - 138 + 80), f"… and {len(sources) - 8} more", fontsize=7.5
            )
    # 3. connections in words (Story), appended
    lines = []
    for a, b, data in g.edges(data=True):
        ka, kb = g.nodes[a]["kind"], g.nodes[b]["kind"]
        if data.get("kind") in ("conflicts", "account_of") or "entity" in (ka, kb):
            lines.append(
                (
                    data.get("kind"),
                    g.nodes[a]["label"],
                    g.nodes[b]["label"],
                    data.get("label") or "",
                )
            )
    order = {"conflicts": 0, "account_of": 1, "mentions": 2}
    lines.sort(key=lambda x: order.get(x[0], 3))
    html = [
        "<h2>Important connections</h2><p>Each line is a stored association between two "
        "records. Associations are extracted by rules or AI, or confirmed by reviewers; "
        "they are not independently verified facts.</p><table><tr><th>Type</th>"
        "<th>From</th><th>To</th><th>Basis</th></tr>"
    ]
    for kind, a, b, basis in lines[:120]:
        html.append(
            f"<tr><td>{esc(EDGE_STYLE.get(kind, ((0,), None, kind))[2])}</td>"
            f"<td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(basis)}</td></tr>"
        )
    html.append(f"</table><p>{esc(DISCLAIMER)}</p>")
    from app.modules.analysis.reports import html_to_pdf

    text_pdf, _ = html_to_pdf(
        "<html><body>" + "".join(html) + "</body></html>",
        title="graph connections",
        header=f"EvidenceX · {case['title']}",
    )
    doc.insert_pdf(pymupdf.open("pdf", text_pdf))
    total = doc.page_count
    for i, p in enumerate(doc):
        p.insert_text(
            (p.rect.width - 110, p.rect.height - 20),
            f"Page {i + 1} of {total}",
            fontsize=7.5,
            color=(0.36, 0.40, 0.47),
        )
        if i < total - (pymupdf.open("pdf", text_pdf).page_count):
            p.insert_text(
                (36, p.rect.height - 20),
                "Graph relationships are extracted or reviewed associations, not verified facts.",
                fontsize=7,
                color=(0.45, 0.48, 0.55),
            )
    from app.modules.analysis.pdf_notice import pdf_metadata

    doc.set_metadata(pdf_metadata(f"Knowledge graph — {case['title']}", "Knowledge graph export"))
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return (
        data,
        total,
        {
            "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges(),
            "focus_pages": min(len(focus), 30),
            "counts": dict(counts),
        },
    )
