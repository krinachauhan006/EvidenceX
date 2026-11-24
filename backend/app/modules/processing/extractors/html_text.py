"""Safe HTML-to-text conversion for email bodies.

Nothing is rendered, executed or fetched. The converter is a small ``HTMLParser``
subclass that:

- drops ``script``, ``style``, ``template``, ``noscript`` and ``head`` content,
- puts line breaks at block-level tags,
- lists link targets as plain text (never as links),
- separates text inside hidden elements (``display:none``, ``visibility:hidden``,
  ``font-size:0``, ``opacity:0``, the ``hidden`` attribute) from the visible text.
  Hidden text is kept in ``hidden_text``, not discarded, and the caller flags it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_DROP_TAGS = frozenset({"script", "style", "template", "noscript", "head"})
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }
)
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|%)?\s*(?:;|$)"
    r"|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)",
    re.IGNORECASE,
)
MAX_LINKS = 200


@dataclass
class HtmlText:
    text: str
    links: list[str] = field(default_factory=list)
    hidden_text: str = ""

    @property
    def has_hidden_content(self) -> bool:
        return bool(self.hidden_text.strip())


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, bool, bool]] = []  # (tag, drops, hidden)
        self._drop_depth = 0
        self._hidden_depth = 0
        self._visible: list[str] = []
        self._hidden: list[str] = []
        self.links: list[str] = []

    def _is_hidden(self, attrs: list[tuple[str, str | None]]) -> bool:
        for name, value in attrs:
            if name == "hidden":
                return True
            if name == "style" and value and _HIDDEN_STYLE.search(value):
                return True
        return False

    def _break(self) -> None:
        target = self._hidden if self._hidden_depth else self._visible
        target.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._break()
            return
        if tag in _VOID_TAGS:
            return
        if tag == "a":
            href = next((v for k, v in attrs if k == "href" and v), None)
            if href and len(self.links) < MAX_LINKS and href not in self.links:
                self.links.append(href.strip()[:2000])
        drops = tag in _DROP_TAGS
        hidden = self._is_hidden(attrs)
        self._stack.append((tag, drops, hidden))
        self._drop_depth += drops
        self._hidden_depth += hidden
        if tag in _BLOCK_TAGS:
            self._break()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS:
            return
        # Close up to the matching open tag; tolerate unbalanced markup.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                for _, drops, hidden in self._stack[index:]:
                    self._drop_depth -= drops
                    self._hidden_depth -= hidden
                del self._stack[index:]
                break
        if tag in _BLOCK_TAGS:
            self._break()

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        (self._hidden if self._hidden_depth else self._visible).append(data)


def _tidy(parts: list[str]) -> str:
    text = "".join(parts).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    blank = 0
    for line in lines:
        if line:
            blank = 0
            out.append(line)
        else:
            blank += 1
            if blank == 1 and out:
                out.append("")
    return "\n".join(out).strip()


def html_to_text(html: str) -> HtmlText:
    parser = _Converter()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must not fail the whole message
        pass
    return HtmlText(
        text=_tidy(parser._visible),
        links=parser.links,
        hidden_text=_tidy(parser._hidden),
    )
