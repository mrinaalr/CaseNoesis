"""
Join PDF-wrapped ``Source:`` URLs while preserving literal source text.

For strict URL-fragment lines (no spaces), append directly.
For spaced continuation lines seen in some PDFs, append them as literal text
(prefixed by a single space) rather than converting spaces to hyphens.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

_URL_FRAGMENT_RE = re.compile(r"^[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+$")

# e.g. .../202109-16 — remainder of path often wrapped on the next line
_DATE_SLUG_TAIL_RE = re.compile(r"(?:^|/)\d{6}-\d{2}$")

_BOILERPLATE_START_RE = re.compile(
    r"^(FOR\s+IMMEDIATE|CONTACT\s*:|\#\#\#)",
    re.IGNORECASE,
)


def normalize_spaced_url_path_line(nxt: str) -> Optional[str]:
    """If *nxt* looks like a spaced path fragment, return literal segment."""
    nxt = nxt.strip()
    if not nxt or _URL_FRAGMENT_RE.match(nxt):
        return None
    if len(nxt) > 280:
        return None
    if nxt.startswith("(") or _BOILERPLATE_START_RE.match(nxt):
        return None
    if nxt[:1] in ("—", "–"):
        return None
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9\s\-,\'.%]*$", nxt):
        return None
    if nxt.count(".") > 2:
        return None
    seg = re.sub(r"\s+", " ", nxt).strip()
    if not seg.lower().endswith(".pdf"):
        seg = seg.rstrip(".,;")
    return seg


def _spaced_literal_append_piece(
    url_so_far: str, nxt: str, continuing_spaced_chain: bool
) -> Optional[str]:
    seg = normalize_spaced_url_path_line(nxt)
    if seg is None:
        return None
    u = url_so_far.rstrip("/")
    if u.lower().endswith(".pdf"):
        return None
    eligible = bool(_DATE_SLUG_TAIL_RE.search(u)) or (
        continuing_spaced_chain and not url_so_far.lower().endswith(".pdf")
    )
    if not eligible:
        return None
    return " " + seg


def consume_same_line_slug_after_url(url: str, trailing_after_url: str) -> Tuple[str, int]:
    """
    Some PDFs put the spaced filename slug on the *same* line after the URL
    (``Source: https://.../202109-16 macoupin county...``). ``https?://\\S*`` stops
    at the first space, so callers must pass text after that match here.
    Returns ``(updated_url, spaced_slug_segment_count)`` — 0 or 1.
    """
    rest = trailing_after_url.strip()
    if not rest:
        return url, 0
    piece = _spaced_literal_append_piece(url, rest, continuing_spaced_chain=False)
    if piece is None:
        return url, 0
    return url + piece, 1


def try_append_source_url_continuation(
    url_so_far: str,
    nxt: str,
    spaced_slug_segments: int,
) -> Optional[Tuple[str, bool]]:
    """
    If *nxt* continues *url_so_far*, return ``(fragment_to_append, is_spaced_slug)``.
    *spaced_slug_segments* is how many spaced continuation lines were appended (max 2).
    """
    if _URL_FRAGMENT_RE.match(nxt):
        return (nxt, False)
    if spaced_slug_segments >= 2:
        return None
    piece = _spaced_literal_append_piece(
        url_so_far, nxt, continuing_spaced_chain=spaced_slug_segments > 0
    )
    if piece is None:
        return None
    return (piece, True)
