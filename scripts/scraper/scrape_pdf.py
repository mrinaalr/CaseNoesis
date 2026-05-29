#!/usr/bin/env python3
"""
Fetch HTML pages from a URL list and build a merged PDF for CaseLinker ingestion.

Works with typical article / press-release markup (article, main, role=main,
common content class names). Title from ``og:title`` / ``twitter:title``, repeated-masthead ``<h1>``
heuristic, ``<title>`` (``|`` / en-dash splits), or URL slug; publication date from meta,
visible date fields, URL path segments, or the first Month D, YYYY dateline in body
text. Emits ``Publication date: YYYY-MM-DD`` before ``Source:`` for merged-PDF batching.

deps:  pip install requests beautifulsoup4 reportlab pypdf pdfplumber
usage:
    python3 scrape_pdf.py --url-file source_urls.txt --out-dir ./out --out-name batch.pdf
    python3 scrape_pdf.py --url-file source_urls.txt --limit 5
    python3 scrape_pdf.py --url-file urls.txt --jina-fallback   # hosts that return 403 to bots
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("pip install requests beautifulsoup4")

try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate
    from reportlab.lib import colors
except ImportError:
    sys.exit("pip install reportlab")

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.exit("pip install pypdf")

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore[assignment]

DEFAULT_URL_FILE = Path.cwd() / "source_urls.txt"
DEFAULT_OUT_DIR = Path.cwd() / "scrape_output"
DEFAULT_OUT_NAME = "scraped_cases.pdf"
REQUEST_DELAY = 1.2
REQUEST_TIMEOUT = 30
JINA_READER_TIMEOUT = 90
MIN_BODY_CHARS = 80

# news.delaware.gov: breadcrumb lines vary — e.g.
#   ``Department of Justice Press Releases | Date Posted:``
#   ``Department of Justice | Date Posted:``
#   ``... Press Releases | Family | Date Posted:``
# Fusion sometimes emits the full breadcrumb + article twice.
_DE_DOJ_DATELINE_LINE_RE = re.compile(
    r"(?m)^[^\n]*Department\s+of\s+Justice[^\n]*\|\s*Date\s+Posted:\s*[^\n]*\s*$",
    re.I,
)


def _collapse_consecutive_duplicate_paragraphs(paras: list[str]) -> list[str]:
    """Drop back-to-back duplicate ``<p>`` text (common when themes duplicate columns)."""
    out: list[str] = []
    prev_key: str | None = None
    for raw in paras:
        key = re.sub(r"\s+", " ", raw.strip())
        if len(key) < 30:
            continue
        if prev_key is not None and key == prev_key:
            continue
        out.append(raw.strip())
        prev_key = key
    return out


def _trim_news_delaware_duplicate_press_rail(body: str) -> str:
    """
    news.delaware.gov (Fusion / Avada) often emits the DOJ breadcrumb +
    ``Date Posted:`` line twice (possibly with ``| Family |`` etc. between crumbs).
    Subscribe widgets may sit between copies. Cut before the second breadcrumb line.
    """
    if not body:
        return body
    matches = list(_DE_DOJ_DATELINE_LINE_RE.finditer(body))
    if len(matches) < 2:
        return body
    second_start = matches[1].start()
    cut = body.rfind("\n\n", 0, second_start)
    if cut == -1:
        cut = body.rfind("\n", 0, second_start)
    if cut <= 0:
        return body[:second_start].rstrip()
    return body[:cut].rstrip()


def _dedupe_news_delaware_paragraph_blocks(body: str, *, min_chars: int = 120) -> str:
    """
    Drop repeated paragraph-sized blocks (normalized whitespace). Catches duplicated
    rails/columns where the second copy does not restart with the DOJ dateline line.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", body.strip()) if b.strip()]
    if len(blocks) < 2:
        return body.strip()

    seen: set[str] = set()
    out: list[str] = []
    for b in blocks:
        if len(b) < min_chars:
            out.append(b)
            continue
        key = re.sub(r"\s+", " ", b.strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return "\n\n".join(out)


# Match batching._merged_news_dateline_year (month + day + year in prose).
_DATELINE_MDY_RE = re.compile(
    r"\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?))\s+"
    r"(\d{1,2}),?\s+((?:19|20)\d{2})\b",
    re.I,
)
_DOB_LINE_HINT_RE = re.compile(
    r"date\s+of\s+birth|\bd\.?\s*o\.?\s*b\.?\s*:|\bborn\b|birthdate|birth\s+date",
    re.I,
)

# Month token (regex capture group 1) -> calendar month number
_MONTH_TOKEN_TO_NUM: dict[str, int] = {}
for i, names in enumerate(
    (
        ("january", "jan"),
        ("february", "feb"),
        ("march", "mar"),
        ("april", "apr"),
        ("may",),
        ("june", "jun"),
        ("july", "jul"),
        ("august", "aug"),
        ("september", "sep", "sept"),
        ("october", "oct"),
        ("november", "nov"),
        ("december", "dec"),
    ),
    start=1,
):
    for n in names:
        _MONTH_TOKEN_TO_NUM[n] = i


def _parse_dateline_match(mon: str, day_s: str, year_s: str) -> date | None:
    tok = mon.lower().strip().rstrip(".")
    month = _MONTH_TOKEN_TO_NUM.get(tok)
    if not month:
        return None
    try:
        d_i, y_i = int(day_s), int(year_s)
        return date(y_i, month, d_i)
    except ValueError:
        return None


def _first_dateline_date_in_text(blob: str) -> date | None:
    """First Month D, YYYY in blob that is not near a DOB hint."""
    if not blob:
        return None
    head = blob[:12000]
    for m in _DATELINE_MDY_RE.finditer(head):
        pre = head[max(0, m.start() - 120) : m.start()]
        if _DOB_LINE_HINT_RE.search(pre):
            continue
        d = _parse_dateline_match(m.group(1), m.group(2), m.group(3))
        if d:
            return d
    return None


def _publication_date_from_meta(soup: BeautifulSoup) -> date | None:
    raw = _meta_content(soup, prop="article:published_time") or _meta_content(
        soup, name="article:published_time"
    )
    raw = raw or _meta_content(soup, prop="og:published_time")
    if raw:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw.strip())
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    t = soup.find("time", attrs={"datetime": True})
    if t:
        dt = str(t.get("datetime", "")).strip()
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", dt)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    return None


def _publication_date_from_url_path(url: str) -> date | None:
    for pat in (
        r"/(\d{4})/(\d{2})/(\d{2})/",
        r"/(\d{4})/(\d{2})/(\d{2})-",
        r"/(\d{4})-(\d{2})-(\d{2})/",
    ):
        m = re.search(pat, url)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    return None


def _publication_date_from_visible_markup(soup: BeautifulSoup) -> date | None:
    """Drupal / news themes: date in header row, field, or meta without standard names."""
    for tag in soup.find_all(["time", "span", "div", "p", "h6", "h5", "h4", "small"]):
        cls = tag.get("class") or []
        cl = " ".join(str(c) for c in cls).lower()
        if any(k in cl for k in ("date", "published", "created", "submitted", "posted")):
            d = _first_dateline_date_in_text(tag.get_text(" ", strip=True))
            if d:
                return d
    return None


def resolve_publication_date(soup: BeautifulSoup, url: str, body: str) -> date | None:
    """
    Best-effort calendar date for the article. Used for ``Publication date: YYYY-MM-DD``
    before ``Source:`` so merged-PDF batching can assign case_id years.
    """
    for fn in (
        lambda: _publication_date_from_meta(soup),
        lambda: _publication_date_from_url_path(url),
        lambda: _publication_date_from_visible_markup(soup),
        lambda: _first_dateline_date_in_text(body),
        lambda: _first_dateline_date_in_text(soup.get_text(" ", strip=True)[:8000]),
    ):
        d = fn()
        if d:
            return d
    return None


def _default_headers(referer: str | None) -> dict[str, str]:
    ref = referer or "https://www.google.com/"
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": ref,
        "DNT": "1",
    }


def _build_styles():
    base = getSampleStyleSheet()
    title_s = ParagraphStyle(
        "DocTitle",
        parent=base["Heading1"],
        fontSize=15,
        leading=19,
        spaceAfter=4,
        textColor=colors.HexColor("#1a1a1a"),
        fontName="Times-Bold",
    )
    meta_s = ParagraphStyle(
        "DocMeta",
        parent=base["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#555555"),
        fontName="Helvetica",
        spaceAfter=2,
    )
    source_s = ParagraphStyle(
        "DocSource",
        parent=base["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#0645ad"),
        fontName="Helvetica",
        spaceAfter=8,
    )
    body_s = ParagraphStyle(
        "DocBody",
        parent=base["Normal"],
        fontSize=10.5,
        leading=15,
        fontName="Times-Roman",
        textColor=colors.HexColor("#111111"),
        spaceAfter=7,
    )
    return title_s, meta_s, source_s, body_s


_TITLE_S, _META_S, _SOURCE_S, _BODY_S = _build_styles()


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def load_urls(path: Path) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().split("#", 1)[0].strip()
        if not line or not line.startswith("http"):
            continue
        key = line.rstrip("/")
        if key not in seen:
            seen.add(key)
            urls.append(line)
    return urls


def fetch(url: str, headers: dict[str, str], *, verify: bool = True) -> str | None:
    try:
        r = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            verify=verify,
        )
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"    [fetch error] {e}", file=sys.stderr)
        return None


def fetch_bytes(url: str, headers: dict[str, str], *, verify: bool = True) -> bytes | None:
    try:
        r = requests.get(
            url,
            headers={**headers, "Accept": "application/pdf,*/*;q=0.8"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            verify=verify,
        )
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"    [fetch error] {e}", file=sys.stderr)
        return None


def _publication_date_from_filename(url: str) -> date | None:
    """Best-effort date from common city press-release PDF names."""
    slug = url.rstrip("/").split("/")[-1]
    stem = re.sub(r"\.pdf$", "", slug, flags=re.I)
    stem = re.sub(r"%20", " ", stem, flags=re.I)
    for pat, conv in (
        (r"^(\d{4})-(\d{2})-(\d{2})", lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
        (r"^(\d{8})_", lambda m: _yyyymmdd(int(m[1]))),
        (r"^(\d{8})(?:_|$)", lambda m: _yyyymmdd(int(m[1]))),
        (r"^(\d{6})_", lambda m: _mmddyy(int(m[1]))),
        (r"^nr(\d{2})(\d{2})(\d{2})", lambda m: date(2000 + int(m[1]), int(m[2]), int(m[3]))),
        (r"^pr_(\d{2})-(\d{2})-(\d{2})", lambda m: date(2000 + int(m[3]), int(m[1]), int(m[2]))),
        (r"^(\d{4})/(\d{2})/(\d{2})", lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
    ):
        m = re.search(pat, stem, re.I)
        if m:
            try:
                return conv(m)
            except ValueError:
                pass
    m = re.search(r"/(\d{4})-(\d{2})/", url)
    if m:
        try:
            return date(int(m[1]), int(m[2]), 1)
        except ValueError:
            pass
    return None


def _yyyymmdd(n: int) -> date:
    y, mo, d = n // 10000, (n // 100) % 100, n % 100
    return date(y, mo, d)


def _mmddyy(n: int) -> date:
    mo, d, y = n // 10000, (n // 100) % 100, n % 100
    return date(2000 + y if y < 100 else y, mo, d)


def _title_from_url(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    stem = re.sub(r"\.pdf$", "", slug, flags=re.I)
    stem = re.sub(r"%20", " ", stem)
    return stem.replace("-", " ").replace("_", " ").strip().title() or "Press release"


def extract_from_native_pdf(pdf_bytes: bytes, url: str) -> tuple[str, str, str, date | None] | None:
    """Downloaded city PDF → title, byline, body, publication date."""
    if not pdfplumber:
        print("    [skip] pdfplumber not installed", file=sys.stderr)
        return None
    import io

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
    except Exception as e:
        print(f"    [pdf extract error] {e}", file=sys.stderr)
        return None
    body = "\n\n".join(p.strip() for p in pages if p.strip())
    if len(body) < MIN_BODY_CHARS:
        return None
    title = _title_from_url(url)
    pub_date = _first_dateline_date_in_text(body) or _publication_date_from_filename(url)
    byline = format_display_byline(pub_date, None)
    return title, byline, body.strip(), pub_date


def fetch_via_jina_reader(target_url: str, *, verify: bool = True, retries: int = 5) -> str | None:
    """Some hosts (e.g. mass.gov) block datacenter IPs; Jina Reader returns markdown + metadata."""
    jina_url = "https://r.jina.ai/" + target_url
    hdrs = {
        "User-Agent": _default_headers(None)["User-Agent"],
        "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.8",
    }
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(
                jina_url,
                headers=hdrs,
                timeout=JINA_READER_TIMEOUT,
                allow_redirects=True,
                verify=verify,
            )
            if r.status_code == 429:
                wait = min(60, 4 * (2**attempt))
                print(f"    [jina 429] waiting {wait}s …", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(min(30, 2 * (attempt + 1)))
    if last_err is not None:
        print(f"    [jina fetch error] {last_err}", file=sys.stderr)
    return None


def _parse_jina_published_time(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# Mass.gov / Mayflower: Jina reader often prepends global nav + trust banner before the press lede.
_JINA_MASS_GOV_PRESS_LEDE = re.compile(
    r"(?m)^(?:[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){0,5})\s+\u2014\s+\S.{25,}\s*$"
)


def _strip_jina_embedded_images(md: str) -> str:
    return re.sub(r"!\[[^\]]*\]\([^)]*\)\s*", "", md)


def _unwrap_jina_markdown_links(md: str) -> str:
    """Turn [label](url) into spaces around label so words do not glue (e.g. Barker[was](u)by)."""
    out = re.sub(r"\[([^\]]+)\]\([^)]+\)", r" \1 ", md)
    return re.sub(r"[ \t]{2,}", " ", out)


def _trim_mass_gov_jina_preface(body: str) -> str:
    """Drop site chrome / duplicate H1 when Jina returns the full page shell."""
    m = _JINA_MASS_GOV_PRESS_LEDE.search(body)
    if m:
        return body[m.start() :].strip()
    return body


def _trim_mass_gov_jina_postface(body: str) -> str:
    """Remove repeated media blocks, feedback widgets, and global footer after the release."""
    m = re.search(r"(?m)^###\s*$", body)
    if m:
        return body[: m.end()].rstrip()
    m2 = re.search(r"(?m)^##\s*Help Us Improve Mass\.gov", body)
    if m2:
        return body[: m2.start()].strip()
    return body


def _trim_nmdoj_jina_preface(body: str) -> str:
    """WordPress/Elementor shell before City, NM dateline (bold, italic, or plain)."""
    # Torrez-era releases: long Elementor nav before "**Albuquerque, NM –**".
    m_abq = re.search(
        r"(?m)^\*\*(?:Albuquerque|Santa\s+Fe|Las\s+Cruces|Gallup|Roswell),?\s*NM\s*[\u2013\u2014\-]",
        body,
    )
    if m_abq:
        return body[m_abq.start() :].strip()
    patterns = (
        re.compile(
            r"(?m)^\*\*(?:[A-Z][^*\n]{0,140}),\s*NM\*\*\s*[\u2013\u2014\-]\s+\S",
        ),
        re.compile(
            r"(?m)^\*\*(?:[A-Z][^*\n]{0,140}),\s*NM\s*[\u2013\u2014\-]\*\*\s+\S",
        ),
        re.compile(
            r"(?m)^_(?:.+?),\s*NM_\s*[\u2013\u2014\-]\s+\S",
        ),
        re.compile(
            r"(?m)^(?:[A-Z]{2,}(?:\s+[A-Z]{2,})*)\s+[\u2014\u2013\-]\s+(?:Today|This|The|Attorney|Special|Octo|Immediately|A\s)",
        ),
        re.compile(
            r"(?m)^(?:[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)*)?,\s*NM\s*[\u2013\u2014\-]\s+\S",
        ),
    )
    best: re.Match[str] | None = None
    for pat in patterns:
        m = pat.search(body)
        if m and (best is None or m.start() < best.start()):
            best = m
    if best:
        return body[best.start() :].strip()
    return body


def _trim_nmdoj_jina_postface(body: str) -> str:
    """Clip Elementor sidebar (Most Viewed) and standard ### / # # # closers."""
    for pat in (
        r"(?m)^##\s*Most Viewed\b",
        r"(?m)^#\s*#\s*#\s*$",
        r"(?m)^###\s*$",
    ):
        m = re.search(pat, body)
        if m:
            return body[: m.start()].strip()
    return body


def _trim_sjpd_jina_body(body: str) -> str:
    """sjpd.org (CivicPlus/Granicus) via Jina: site chrome before FOR IMMEDIATE RELEASE; footer after release."""
    if not (body or "").strip():
        return body
    trimmed = body
    for pat in (
        r"(?m)^\*\*FOR IMMEDIATE RELEASE\*\*\s*$",
        r"(?m)^FOR IMMEDIATE RELEASE\s*$",
        r"(?m)^TYPE OF CRIME:",
        r"(?m)^##\s+(?:SJPD|Additional|Public Notification)[^\n]{8,220}\n+\s*Post Date:",
        r"(?m)^Post Date:\s*\d{1,2}/\d{1,2}/\d{4}",
    ):
        m = re.search(pat, trimmed)
        if m:
            trimmed = trimmed[m.start() :].strip()
            break
    # Drop duplicate page-title H1 when Jina leaves nav above the release block
    trimmed = re.sub(
        r"(?m)^#\s+[^|\n]{8,220}\|\s*News & Announcements\s*\|\s*San Jose Police Department, CA\s*$",
        "",
        trimmed,
    ).strip()
    end_markers = (
        r"Return to full list",
        r"(?m)^\s*Click to submit a tip anonymously",
        r"(?m)^\s*Archived News\s*:",
        r"(?m)^\s*Contact the Media Relations Unit",
        r"(?m)^\s*Older News:\s*\(Prior to",
        r"(?m)^\s*PRESS RELEASE, According to Cal Govt",
        r"(?m)\]\(https?://nextdoor\.com/",
        r"(?m)^\s*OUR MISSION:",
        r"(?m)^\s*E-Government Policy",
        r"(?m)^\s*Created By Granicus",
        r"(?m)^\s*###\s+Stay Connected",
        r"(?m)^\s*Powered by Translate",
        r"(?m)^Skip to Main Content",
        r"(?m)^\[Home\]\(",
        r"(?m)^Online Services\s*\+",
        r"(?m)^Join SJPD\s*$",
        r"(?m)^Phone Directory\b",
    )
    end_at: int | None = None
    for marker in end_markers:
        m = re.search(marker, trimmed)
        if m and m.start() > 400 and (end_at is None or m.start() < end_at):
            end_at = m.start()
    if end_at is not None:
        trimmed = trimmed[:end_at].strip()
    lines = []
    for line in trimmed.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^!\[[^\]]*\]\([^)]+\)\s*$", s):
            continue
        if re.match(r"^\[\]\(https?://", s):
            continue
        if s.startswith("*   [") or (s.startswith("+") and "[" in s):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _trim_ice_gov_jina_body(body: str) -> str:
    """
    ice.gov (USWDS/Drupal) via Jina: full site nav, mega-menu, and mobile footer
    precede the release dateline and article body.
    """
    if not (body or "").strip():
        return body
    trimmed = body
    start_patterns = (
        r"(?m)^[A-Z][a-z]+ \d{1,2}, \d{4} .{2,120}United States (?:Child Exploitation|Enforcement and Removal|Human Trafficking)\s*$",
        r"(?m)^[A-Z][A-Z\s,\.]{3,60} – ",
        r"(?m)^[A-Z][A-Z\s,\.]{3,60} - ",
        r"(?m)^\*\*FOR IMMEDIATE RELEASE\*\*\s*$",
        r"(?m)^FOR IMMEDIATE RELEASE\s*$",
        r"(?m)^#\s+[^|\n]{12,220}\|\s*ICE\s*$",
    )
    for pat in start_patterns:
        m = re.search(pat, trimmed)
        if m and m.start() > 0:
            trimmed = trimmed[m.start() :].strip()
            break
    # Drop duplicate article H1 when dateline start left a trailing title line
    trimmed = re.sub(
        r"(?m)^#\s+[^|\n]{12,220}\|\s*ICE\s*\n+",
        "",
        trimmed,
        count=1,
    ).strip()
    end_markers = (
        r"(?m)^Updated:\s*\d",
        r"(?m)^### Media Inquiries",
        r"(?m)^## ICE USWDS Footer",
        r"(?m)^\[Return to top\]",
        r"(?m)^You have been selected to participate",
        r"(?m)^## Mobile Menu",
        r"(?m)^## Main Navigation on Mobile",
        r"(?m)^\[Close menu\]",
        r"(?m)^Search Search\s*$",
        r"(?m)^\[AddToAny\]",
    )
    end_at: int | None = None
    for marker in end_markers:
        m = re.search(marker, trimmed)
        if m and m.start() > 350 and (end_at is None or m.start() < end_at):
            end_at = m.start()
    if end_at is not None:
        trimmed = trimmed[:end_at].strip()
    lines: list[str] = []
    for line in trimmed.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^!\[[^\]]*\]\([^)]+\)\s*$", s):
            continue
        if re.match(r"^\[\]\(https?://", s):
            continue
        if s.startswith("*   [") or (s.startswith("+") and "[" in s):
            continue
        if re.match(r"^#{1,6}\s+(About Us|Enforcement and Removal|Homeland Security|Newsroom)\s*$", s):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _justice_pr_url_from_blob(blob: str) -> str | None:
    """NCIS press pages often only link to a USAO press release on justice.gov."""
    m = re.search(r"https://www\.justice\.gov/usao-[a-z]+/pr/[a-z0-9\-]+", blob or "", re.I)
    return m.group(0).rstrip(".,)>]") if m else None


def _ncis_doj_follow_url(
    page_url: str, body: str, *blobs: str | None
) -> str | None:
    """Return justice.gov PR URL when NCIS page is a shell or press-release stub."""
    if "ncis.navy.mil" not in (page_url or "").lower():
        return None
    doj_url: str | None = None
    for blob in blobs:
        if blob:
            doj_url = _justice_pr_url_from_blob(blob)
            if doj_url:
                break
    if not doj_url:
        return None
    b = (body or "").strip()
    if "/Press-Releases/" in page_url or len(b) < 400:
        return doj_url
    if re.search(
        r"Site Map\s*\|.*Privacy|Facebook X Email Share|Read the full DOJ",
        b,
        re.I,
    ):
        return doj_url
    return None


def _trim_justice_gov_jina_body(body: str) -> str:
    """USAO press releases on justice.gov: drop site chrome and related-articles rail."""
    if not (body or "").strip():
        return body
    trimmed = body
    start = None
    for pat in (
        r"(?m)^\*\*For Immediate Release\*\*",
        r"(?m)^[A-Z][A-Za-z .'-]+,\s+[A-Z]{2}\.?\s*–\s",
        r"(?m)^[A-Z][A-Za-z .'-]+,\s+[A-Z][a-z]+\s+–\s",
        r"(?m)^ALEXANDRIA,\s+Va\.\s*–",
    ):
        m = re.search(pat, trimmed)
        if m:
            start = m.start()
            break
    if start is not None and start > 0:
        trimmed = trimmed[start:].strip()
    for marker in (
        "\n## Related Content",
        "\n**Topic**",
        "\nInformation for Victims in Large Cases",
        "\nMain Menu",
        "\nWhy Justice ?",
        "\nSkip to main content",
        "\nAn official website of the United States government",
    ):
        j = trimmed.find(marker)
        if j > 200:
            trimmed = trimmed[:j].strip()
            break
    m = re.search(r"(?m)^Updated\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d", trimmed)
    if m and m.start() > 200:
        trimmed = trimmed[: m.start()].strip()
    return re.sub(r"\n{3,}", "\n\n", trimmed).strip()


def _trim_ncis_jina_body(body: str) -> str:
    """NCIS news articles: drop nav; keep quoted lede / dateline blocks."""
    if not (body or "").strip():
        return body
    trimmed = body
    for pat in (
        r'(?m)^_"',
        r"(?m)^[A-Z][a-z]+,\s+[A-Z]{2}\.\s*–",
        r"(?m)^\*\*[A-Z][a-z]+,\s+[A-Z]{2}\.\s*–",
        r"(?m)^[A-Z][a-z]+ \d{1,2}, \d{4}\s*$",
    ):
        m = re.search(pat, trimmed)
        if m and m.start() > 0:
            trimmed = trimmed[m.start() :].strip()
            break
    return re.sub(r"\n{3,}", "\n\n", trimmed).strip()


_CBP_NAV_MARKERS = re.compile(
    r"(?m)^(?:### Travel|Enter Search Term|Visa Waiver Program|Trusted Traveler|"
    r"Skip to main content|Countdown to America)",
    re.I,
)


def _cbp_release_body_score(text: str) -> int:
    """Prefer slices that look like a press release, not site chrome."""
    head = (text or "")[:900]
    if _CBP_NAV_MARKERS.search(head):
        return -10_000
    if "skip to main content" in head.lower():
        return -10_000
    score = min(len(text), 12_000)
    if re.search(r"child|sexual|predator|assault|csam|molest", text, re.I):
        score += 800
    if re.search(
        r"(?m)^[A-Z][A-Za-z .'-]+,\s+(?:[A-Z]{2}|[A-Za-z]+)\s*[-–—]",
        text,
    ):
        score += 400
    return score


def _cbp_slice_from_dateline(body: str, start: int) -> str:
    chunk = body[start:].strip()
    for marker in (
        "\nLast Modified:",
        "\nLast Updated:",
        "\n## Media Contacts",
        "\n### Media Contacts",
        "\nTopics",
        "\n### Media & Public",
        "\nSite Map",
        "\nCBP Seal",
        "\nEnter Search Term",
        "\n[Back to top]",
        "\nFollow the Director",
    ):
        j = chunk.find(marker)
        if j > 120:
            chunk = chunk[:j].strip()
            break
    return chunk


def _trim_cbp_jina_body(body: str) -> str:
    """CBP newsroom releases: pick best dateline block (nav often precedes article)."""
    if not (body or "").strip():
        return body
    candidates: list[str] = []
    for pat in (
        r"\*\*[A-Z][A-Za-z .'-]+,\s+[A-Za-z .'-]+\s*\*\*\s*[-–—]?\s*",
        r"\*\*[A-Z][A-Za-z .'-]{2,40}\*\*\s*[-–—]\s*",
        r"(?m)^\*\*[A-Z][A-Za-z .'-]+,\s+[A-Z]{2}\s*[-–—]\*\*",
        r"(?m)^[A-Z][A-Za-z .'-]+,\s+[A-Za-z .'-]+\s*[-–—]\s+",
        r"(?m)^[A-Z][A-Za-z .'-]+,\s+[A-Z]{2}\s*[-–—]\s+",
        r"(?m)^[A-Z][A-Z .'-]{3,40},\s+[A-Z]{2}\s*[-–—]\s+",
    ):
        for m in re.finditer(pat, body):
            candidates.append(_cbp_slice_from_dateline(body, m.start()))
    rel = re.search(
        r"(?m)^Release Date\s*\n+\w{3},\s+\d{1,2}/\d{1,2}/\d{4}\s*\n+",
        body,
    )
    if rel:
        candidates.append(_cbp_slice_from_dateline(body, rel.end()))
    if not candidates:
        m = re.search(
            r"(?m)^# [^\n]{12,}(?:child|sexual|predator|assault)[^\n]*\n+"
            r"(?:[^\n]*\n){0,8}?\*\*[A-Z]",
            body,
            re.I,
        )
        if m:
            tail = body[m.end() - 2 :]
            dm = re.search(
                r"\*\*[A-Z][A-Za-z .'-]+,\s+[A-Za-z .'-]+\s*\*\*\s*[-–—]?\s*",
                tail,
            )
            if dm:
                candidates.append(_cbp_slice_from_dateline(tail, dm.start()))
    if not candidates:
        return body
    best = max(candidates, key=_cbp_release_body_score)
    return re.sub(r"\n{3,}", "\n\n", best).strip()


def _cbp_body_ok(body: str) -> bool:
    if len((body or "").strip()) < MIN_BODY_CHARS:
        return False
    if _CBP_NAV_MARKERS.search(body[:1000]):
        return False
    if "skip to main content" in body[:500].lower():
        return False
    return bool(re.search(r"child|sexual|predator|assault|csam|molest", body, re.I))


_USMS_NAV_MARKERS = re.compile(
    r"(?m)^(?:## Office of Public Affairs|Usms\.mediadesk@|Skip to main content|"
    r"An official website of the United States government|Search Search\s*$)",
    re.I,
)


def _usms_slice_from_start(body: str, start: int) -> str:
    chunk = body[start:].strip()
    for marker in (
        "\n## Related",
        "\n### Related",
        "\nRelated Content",
        "\nMedia Contact",
        "\n## Media Contact",
        "\n[Back to top]",
        "\nAmerica's First Federal",
        "\nAn official website of the United States government",
        "\nusmarshals.gov is an official site",
    ):
        j = chunk.find(marker)
        if j > 120:
            chunk = chunk[:j].strip()
            break
    return chunk


def _usms_release_body_score(text: str) -> int:
    head = (text or "")[:900]
    if "skip to main content" in head.lower():
        return -10_000
    if re.search(r"(?m)^Search Search", head):
        return -10_000
    score = min(len(text), 10_000)
    if re.search(r"child|minor|kidnap|sexual|predator|exploitation|molest|abduct", text, re.I):
        score += 800
    if re.search(r"U\.?S\.? Marshals|Marshals Service", text, re.I):
        score += 200
    return score


def _trim_usmarshals_jina_body(body: str) -> str:
    """USMS press releases via Jina: keep dateline through body."""
    if not (body or "").strip():
        return body
    candidates: list[str] = []
    for pat in (
        r"\*\*[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}\*\*\s*[-–—]\s*",
        r"(?m)^FOR IMMEDIATE RELEASE\s*$",
        r"(?m)^## For immediate release\s*$",
        r"(?m)^[A-Z][a-z .'-]+,\s+[A-Z]{2}\s*[-–—]\s",
        r"(?m)^[A-Z][A-Z .'-]{4,60},\s+[A-Z]{2}\s*[-–—]\s",
    ):
        for m in re.finditer(pat, body, re.I):
            candidates.append(_usms_slice_from_start(body, m.start()))
    if not candidates:
        return _trim_usmarshals_postface(body)
    best = max(candidates, key=_usms_release_body_score)
    dm = re.search(r"\*\*[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}\*\*\s*[-–—]\s*", best)
    if not dm:
        dm = re.search(r"(?m)^[A-Z][a-z .'-]+,\s+[A-Z]{2}\s*[-–—]\s+", best)
    if dm:
        best = best[dm.start() :]
    return _trim_usmarshals_postface(re.sub(r"\n{3,}", "\n\n", best).strip())


def _trim_usmarshals_postface(body: str) -> str:
    """Drop USMS site footer, share row, and nav that Jina appends after release text."""
    if not (body or "").strip():
        return body
    end_markers = (
        r"(?m)^#{2,4}\s*$",
        r"(?m)^America['\u2019]s First Federal Law Enforcement Agency\s*$",
        r"(?m)^Email Facebook\b",
        r"(?m)^Back to top\s*$",
        r"(?m)^WHO WE ARE\s*$",
        r"(?m)^- \[x\]\s*$",
        r"(?m)^Search Search\s*$",
        r"(?m)^##\s+Related\b",
        r"(?m)^###\s+Related\b",
        r"(?m)^Related Content\s*$",
        r"(?m)^##\s+Media Contact\b",
        r"(?m)^Media Contact\s*$",
        r"(?m)^An official website of the United States government\b",
        r"(?m)^usmarshals\.gov is an official site\b",
        r"(?m)^\[Back to top\]",
    )
    end_at: int | None = None
    for marker in end_markers:
        m = re.search(marker, body)
        if m and m.start() > 200 and (end_at is None or m.start() < end_at):
            end_at = m.start()
    trimmed = body[:end_at].strip() if end_at is not None else body.strip()
    lines: list[str] = []
    for line in trimmed.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^[-*]\s*\[x\]\s*$", s):
            continue
        if s in {
            "Back to top",
            "WHO WE ARE",
            "About Us",
            "Leadership",
            "History",
            "Contact Us",
            "District Offices",
            "Headquarters",
            "Office of Professional Responsibility",
            "Business with U.S. Marshals",
        }:
            continue
        if re.match(r"^U\.?S\.? Marshals['\u2019]? Biographies$", s):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _usms_body_ok(body: str) -> bool:
    """Reject nav shells and empty Jina pages; URL lists are already topic-filtered."""
    if len((body or "").strip()) < MIN_BODY_CHARS:
        return False
    if "skip to main content" in body[:500].lower():
        return False
    if re.search(r"(?m)^Search Search", body[:600]):
        return False
    if _USMS_NAV_MARKERS.search(body[:1200]):
        return False
    return bool(re.search(r"U\.?S\.?\s*Marshals|Marshals Service", body, re.I))


def _trim_dod_news_jina_body(body: str) -> str:
    """Trim DOD/USG news article chrome (OSI, NCIS, Marshals, CBP via Jina)."""
    if not (body or "").strip():
        return body
    trimmed = body
    for pat in (
        r"(?m)^\*\*FOR IMMEDIATE RELEASE\*\*\s*$",
        r"(?m)^FOR IMMEDIATE RELEASE\s*$",
        r"(?m)^[A-Z][a-z]+ \d{1,2}, \d{4}\s*$",
        r"(?m)^[A-Z][A-Z\s,\.]{4,80} – ",
        r"(?m)^[A-Z][A-Z\s,\.]{4,80} - ",
        r"(?m)^[A-Z][a-z].{20,200}\n\n[A-Z]",
    ):
        m = re.search(pat, trimmed)
        if m and m.start() > 0 and m.start() < 8000:
            trimmed = trimmed[m.start() :].strip()
            break
    trimmed = re.sub(r"(?m)^#\s+[^|\n]{10,220}\|\s*[^\n]+\s*\n+", "", trimmed, count=1).strip()
    end_markers = (
        r"(?m)^###\s+Related",
        r"(?m)^##\s+Related",
        r"(?m)^Related Articles",
        r"(?m)^Media (?:Contact|Inquiries)",
        r"(?m)^Subscribe to",
        r"(?m)^Connect with",
        r"(?m)^\[Return to top\]",
        r"(?m)^## Footer",
        r"(?m)^An official website of the United States government",
        r"(?m)^\[Close menu\]",
        r"(?m)^Search Search\s*$",
    )
    end_at: int | None = None
    for marker in end_markers:
        m = re.search(marker, trimmed)
        if m and m.start() > 300 and (end_at is None or m.start() < end_at):
            end_at = m.start()
    if end_at is not None:
        trimmed = trimmed[:end_at].strip()
    lines: list[str] = []
    for line in trimmed.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^!\[", s) or re.match(r"^\[\]\(https?://", s):
            continue
        if s.startswith("*   [") or (s.startswith("+") and "[" in s):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _trim_ice_gov_html_container(soup: BeautifulSoup) -> BeautifulSoup | None:
    """Return a copy of the ICE release body node without breadcrumb/share chrome."""
    root = (
        soup.select_one(".nr-body")
        or soup.select_one(".views-field-nothing-3 .field-content")
        or soup.select_one(".field--name-body .field__item")
        or soup.select_one(".field--name-body")
        or soup.select_one("#main-content .node__content")
        or soup.select_one("#main-content")
    )
    if not root:
        return None
    fragment = BeautifulSoup(str(root), "html.parser")
    for sel in (
        ".breadcrumb",
        ".share",
        "nav",
        "aside",
        ".usa-breadcrumb",
        ".block-system-breadcrumb-block",
    ):
        for tag in fragment.select(sel):
            tag.decompose()
    return fragment


def _trim_lvmpd_jina_body(body: str) -> str:
    """lvmpd.com (Granicus) via Jina: global nav then press release under FOR IMMEDIATE RELEASE."""
    if not (body or "").strip():
        return body
    trimmed = body
    for pat in (
        r"(?m)^\*\*FOR IMMEDIATE RELEASE\*\*\s*$",
        r"(?m)^A multi-agency operation targeting child",
        r"(?m)^The Nevada Internet Crimes Against Children",
        r"(?m)^LAS VEGAS,?\s+Nevada",
    ):
        m = re.search(pat, trimmed)
        if m:
            trimmed = trimmed[m.start() :].strip()
            break
    for marker in (
        r"(?m)^Anyone who may have been a victim",
        r"(?m)^We would like to remind parents",
        r"(?m)^###\s+Stay Connected",
        r"(?m)^Created By Granicus",
        r"(?m)^Loading \.\.\.",
        r"(?m)^Office of Public Information\s*$",
        r"(?m)^Skip to Main Content",
        r"(?m)^\[Home\]\(",
        r"(?m)^Online Services\s*\+",
    ):
        m = re.search(marker, trimmed)
        if m and m.start() > 400:
            trimmed = trimmed[: m.start()].strip()
            break
    lines = []
    for line in trimmed.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^\[\]\(https?://", s):
            continue
        if re.match(r"^!\[", s):
            continue
        if s.startswith("*   [") or s.startswith("+") and "[" in s:
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _trim_cid_army_jina_body(body: str) -> str:
    """
    cid.army.mil via Jina returns DOD trust banner, global nav, sidebars, and footer.
    Keep the press-release lede through SHARE/related-stories markers.
    """
    if not (body or "").strip():
        return body
    trimmed = body
    # Drop duplicate breadcrumb H1 ("> Department of the Army Criminal Investigation Division > Article Display")
    trimmed = re.sub(
        r"(?m)^#\s+.+\>\s*Department of the Army Criminal Investigation Division\s*\>\s*Article Display\s*$",
        "",
        trimmed,
    )
    # Start at visible dateline or "News |" row above the article H1
    start = None
    for pat in (
        r"(?m)^News\s*\|\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
        r"(?m)^(?:QUANTICO|Quantico|KIRTLAND|Kirtland|FORT HOOD|Fort Hood)[^\n]{0,80}-\s+\S",
        r"(?m)^#\s+[A-Z][^\n]{12,120}$",
    ):
        m = re.search(pat, trimmed)
        if m and (start is None or m.start() < start):
            start = m.start()
    if start is not None and start > 0:
        trimmed = trimmed[start:].strip()
    # If nav chrome remains above dateline, cut from first release paragraph
    m = re.search(
        r"(?m)^(?:[A-Z][A-Za-z\s,\.'-]{2,50},\s*(?:Va\.|Texas|N\.M\.|Colo\.|Hawaii)\s*-\s+|\*\*Press Release\*\*\s*\n)",
        trimmed,
    )
    if m and m.start() > 200:
        trimmed = trimmed[m.start() :].strip()
    for marker in (
        r"(?m)^\s*SHARE\s*$",
        r"(?m)^\s*PRINT\s*$",
        r"(?m)^###\s+Stay Connected",
        r"(?m)^##\s+Related Stories",
        r"(?m)^##\s+Related Press Advisories",
        r"(?m)^Previous Story\s*$",
        r"(?m)^Next Story\s*$",
        r"(?m)^Department of War\s*$",
        r"(?m)^Thanks for sharing!",
        r"(?m)^AddToAny\s*$",
        r"(?m)^Hosted by Department of War",
        r"(?m)^An official website of the United States government",
        r"(?m)^Here's how you know",
        r"(?m)^Skip to main content",
        r"(?m)^Toggle navigation",
        r"(?m)^Search Army CID:",
    ):
        m = re.search(marker, trimmed)
        if m and m.start() > 300:
            trimmed = trimmed[: m.start()].strip()
            break
    # Drop markdown link-only lines and image alt stubs
    lines = []
    for line in trimmed.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^!\[[^\]]*\]\([^)]+\)\s*$", s):
            continue
        if re.match(r"^\[\]\(https?://www\.cid\.army\.mil", s):
            continue
        if s in (")", "Home", "About Us )", "Media Resources )", "Crime Prevention )", "Contact Us )"):
            continue
        if re.match(r"^[-\[\]()]+$", s):
            continue
        lines.append(line)
    trimmed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return trimmed


def _trim_dps_iowa_jina_body(body: str) -> str:
    """Iowa DPS (Drupal) via Jina often includes site nav, search, and footer; keep the release body."""
    if not (body or "").strip():
        return body
    lines = body.splitlines()
    start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if re.match(
            r"^(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
            s,
        ):
            start = i
            break
        if re.match(r"^DES MOINES,?\s+Iowa", s, re.I):
            start = i
            break
    trimmed = "\n".join(lines[start:]).strip()
    for marker in (
        "\n## Footer\n",
        "\n### Footer\n",
        "Oran Pape State Office Building",
        "\n## Connect with",
        "\n### Connect",
        "Share feedback with us",
        "© 20",
        "Google Translate",
    ):
        j = trimmed.find(marker)
        if j > 200:
            trimmed = trimmed[:j].strip()
            break
    return trimmed


def extract_from_jina_reader(markdown_blob: str, original_url: str) -> tuple[str, str, str, date | None] | None:
    """
    Parse r.jina.ai plain-text response (Title / URL Source / Published Time / Markdown Content).

    Host-specific cleanup trims full-page chrome for mass.gov and nmdoj.gov press pages before PDF layout.
    """
    blob = markdown_blob.lstrip()
    if not blob.startswith("Title:") or "Markdown Content:" not in blob:
        return None
    lines = markdown_blob.splitlines()
    title = ""
    pub: date | None = None
    body_start: int | None = None
    for i, line in enumerate(lines):
        if line.startswith("Title:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("Published Time:"):
            pub = _parse_jina_published_time(line.split(":", 1)[1])
        elif line.startswith("Markdown Content:"):
            body_start = i + 1
            break
    if body_start is None:
        return None
    body_raw = "\n\n".join(lines[body_start:]).strip()
    if "mass.gov" in (original_url or "").lower():
        body_raw = re.sub(r"^\s*#+\s*.+\|\s*Mass\.gov\s*$", "", body_raw, flags=re.MULTILINE)
    if "nmdoj.gov" in (original_url or "").lower():
        body_raw = re.sub(
            r"^\s*#+\s*.+\-\s*New Mexico Department of Justice\s*$",
            "",
            body_raw,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    body_raw = _strip_jina_embedded_images(body_raw)
    body = _unwrap_jina_markdown_links(body_raw)
    if "nmdoj.gov" in (original_url or "").lower():
        body = _trim_nmdoj_jina_preface(body)
    if "cbp.gov" in (original_url or "").lower():
        body = _trim_cbp_jina_body(body)
    if "usmarshals.gov" in (original_url or "").lower():
        body = _trim_usmarshals_jina_body(body)
    body = re.sub(r"\*\*([^*]+)\*\*", r"\1", body)
    body = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", body)
    if "mass.gov" in (original_url or "").lower():
        body = _trim_mass_gov_jina_preface(body)
        body = _trim_mass_gov_jina_postface(body)
    if "nmdoj.gov" in (original_url or "").lower():
        body = _trim_nmdoj_jina_postface(body)
    if "dps.iowa.gov" in (original_url or "").lower():
        body = _trim_dps_iowa_jina_body(body)
    if "sjpd.org" in (original_url or "").lower():
        body = _trim_sjpd_jina_body(body)
        if "|" in title:
            title = title.split("|", 1)[0].strip()
    if "lvmpd.com" in (original_url or "").lower():
        body = _trim_lvmpd_jina_body(body)
        if title.lower().endswith("| news list") or "| las vegas" in title.lower():
            title = title.split("|", 1)[0].strip()
    if "ice.gov" in (original_url or "").lower():
        body = _trim_ice_gov_jina_body(body)
        if "|" in title:
            title = title.split("|", 1)[0].strip()
    if "justice.gov" in (original_url or "").lower():
        body = _trim_justice_gov_jina_body(body)
        if "|" in title:
            title = title.split("|", 1)[0].strip()
    if "cbp.gov" in (original_url or "").lower():
        if not _cbp_body_ok(body):
            return None
        if "|" in title:
            title = title.split("|", 1)[0].strip()
    elif "usmarshals.gov" in (original_url or "").lower():
        if not _usms_body_ok(body):
            return None
        if "|" in title:
            title = title.split("|", 1)[0].strip()
    elif any(
        h in (original_url or "").lower()
        for h in ("osi.af.mil", "ncis.navy.mil")
    ):
        body = _trim_dod_news_jina_body(body)
        if "ncis.navy.mil" in (original_url or "").lower():
            body = _trim_ncis_jina_body(body)
        if "|" in title:
            title = title.split("|", 1)[0].strip()
    if "cid.army.mil" in (original_url or "").lower():
        body = _trim_cid_army_jina_body(body)
        if title.lower().startswith("404") or "article display" in title.lower():
            m = re.search(r"(?m)^#\s+(.+)$", body)
            if m:
                title = re.sub(r"\s*>.*$", "", m.group(1)).strip()
    if "news.delaware.gov" in (original_url or "").lower():
        body = _trim_news_delaware_duplicate_press_rail(body)
        body = _dedupe_news_delaware_paragraph_blocks(body)
    if len(body) < MIN_BODY_CHARS:
        return None
    byline = pub.strftime("%B %d, %Y") if pub else ""
    return title or "Untitled", byline, body, pub


def _meta_content(soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None) -> str:
    for sel, val in (("property", prop), ("name", name)):
        if not val:
            continue
        tag = soup.find("meta", attrs={sel: val})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def format_display_byline(pub_date: date | None, soup: BeautifulSoup | None) -> str:
    """Optional human date under the title (omit if we only have ISO publication line)."""
    if pub_date:
        return pub_date.strftime("%B %d, %Y")
    if soup is None:
        return ""
    raw = _meta_content(soup, prop="article:published_time") or _meta_content(
        soup, name="article:published_time"
    )
    raw = raw or _meta_content(soup, prop="og:published_time")
    if raw and len(raw) <= 120:
        return raw.strip()
    return ""


def _html_headline_title(soup: BeautifulSoup) -> str:
    """
    Prefer social meta (og/twitter): many WordPress/Avada pages repeat the site name in the
    first ``<h1>`` and put the article headline only in ``og:title`` / ``<title>``.

    If meta is missing, resolve ``<h1>``: when several leading ``h1``s share the same masthead
    text and the last ``h1`` differs (common on dojmt.gov), use the last one.
    """

    og = _meta_content(soup, prop="og:title") or _meta_content(soup, name="twitter:title")
    if og and len(og.strip()) >= 4:
        return og.strip()

    h1_texts = [h.get_text(" ", strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
    if h1_texts:
        if (
            len(h1_texts) >= 2
            and h1_texts[0]
            and all(h == h1_texts[0] for h in h1_texts[:-1])
            and h1_texts[-1] != h1_texts[0]
        ):
            return h1_texts[-1]
        return h1_texts[0]

    if soup.title:
        raw = soup.title.get_text(strip=True)
        head = raw.split("|", 1)[0].strip()
        for sep in (" \u2013 ", " \u2014 ", " - "):  # en dash, em dash, spaced hyphen
            if sep in head:
                left, right = head.split(sep, 1)
                if len(left.strip()) >= 8 and len(right.strip()) >= 8:
                    return left.strip()
        return head
    return ""


def extract(html: str, url: str) -> tuple[str, str, str, date | None] | None:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(
        ["script", "style", "noscript", "iframe", "nav", "footer", "aside", "form", "button"]
    ):
        tag.decompose()

    netloc = urlparse(url).netloc.lower()

    title = _html_headline_title(soup).strip()
    if netloc == "www.fresnosheriff.org" or netloc == "fresnosheriff.org":
        if title.lower() in ("media relations",) or len(title) < 25:
            h2 = soup.select_one(".item-page h2") or soup.select_one(".com-content-article h2")
            if h2:
                title = h2.get_text(" ", strip=True)
            elif soup.title:
                raw = soup.title.get_text(strip=True)
                if " - " in raw:
                    title = raw.rsplit(" - ", 1)[-1].strip()
    if not title:
        slug = url.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ").replace("_", " ").title()

    container = None
    if netloc == "news.delaware.gov":
        container = soup.select_one(".fusion-post-content") or soup.select_one(".post-content")
    elif netloc in ("www.fresnosheriff.org", "fresnosheriff.org"):
        container = (
            soup.select_one(".com-content-article.item-page")
            or soup.select_one(".item-page")
        )
    elif netloc in ("www.osceolasheriff.org", "osceolasheriff.org"):
        container = (
            soup.select_one(".l-main .entry-content")
            or soup.select_one(".entry-content")
            or soup.select_one(".l-main")
        )
    elif netloc == "dps.iowa.gov":
        container = (
            soup.select_one(".field--name-field-news__body .field__item")
            or soup.select_one(".field--name-field-news__body")
            or soup.select_one("div.node__content.news__inner.text-editor-content")
            or soup.select_one("div.node__content.news__inner")
        )
    elif netloc in ("www.lvmpd.com", "lvmpd.com"):
        container = (
            soup.select_one(".content.main-content")
            or soup.select_one("#pagebody")
            or soup.select_one("article")
            or soup.select_one(".fr-view")
        )
    elif netloc in ("www.sjpd.org", "sjpd.org"):
        container = (
            soup.select_one(".content.main-content")
            or soup.select_one("#pagebody")
            or soup.select_one("article")
            or soup.select_one(".fr-view")
        )
    elif netloc in ("riag.ri.gov", "www.riag.ri.gov"):
        container = (
            soup.select_one("article.press-release")
            or soup.select_one("article")
            or soup.select_one(".field--name-body")
            or soup.select_one("main")
        )
    elif netloc in ("www.myfloridalegal.com", "myfloridalegal.com"):
        container = (
            soup.select_one("article.node--type-news-release")
            or soup.select_one("article")
            or soup.select_one(".field--name-body")
            or soup.select_one("main")
        )
    elif netloc in ("www.secretservice.gov", "secretservice.gov"):
        h1 = soup.select_one("h1")
        if h1:
            h1_text = h1.get_text(" ", strip=True)
            if h1_text and h1_text.lower() not in ("search this site",):
                title = h1_text
        container = (
            soup.select_one("article")
            or soup.select_one("main")
            or soup.select_one('[role="main"]')
        )
    elif netloc in ("www.ice.gov", "ice.gov"):
        og = _meta_content(soup, prop="og:title") or _meta_content(soup, name="twitter:title")
        if og:
            title = og.split("|", 1)[0].strip()
        if not title or title.lower() in ("ice", "newsroom"):
            h1 = soup.select_one("#main-content h1") or soup.select_one("main h1")
            if h1:
                title = h1.get_text(" ", strip=True)
        ice_root = _trim_ice_gov_html_container(soup)
        container = ice_root if ice_root is not None else (
            soup.select_one(".nr-body")
            or soup.select_one(".field--name-body .field__item")
            or soup.select_one("#main-content")
        )
    elif netloc in ("www.osi.af.mil", "osi.af.mil"):
        container = (
            soup.select_one(".article-body")
            or soup.select_one(".body-text")
            or soup.select_one("article")
            or soup.select_one("main")
        )
    elif netloc in ("www.ncis.navy.mil", "ncis.navy.mil"):
        container = (
            soup.select_one(".article-text")
            or soup.select_one(".body-text")
            or soup.select_one("article")
            or soup.select_one("main")
        )
    elif netloc in ("www.usmarshals.gov", "usmarshals.gov"):
        container = (
            soup.select_one(".field--name-body")
            or soup.select_one("article")
            or soup.select_one("main")
        )
    elif netloc in ("www.cbp.gov", "cbp.gov"):
        container = (
            soup.select_one(".field--name-body .field__item")
            or soup.select_one(".field--name-body")
            or soup.select_one("article")
            or soup.select_one("main")
        )

    if container is None:
        container = (
            soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find(class_=re.compile(r"content|body|field-body|article-body|post-body", re.I))
            or soup.body
        )
    if not container:
        return None

    paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    paras = _collapse_consecutive_duplicate_paragraphs(paras)
    body = "\n\n".join(p for p in paras if len(p) > 30)
    if len(body) < MIN_BODY_CHARS:
        body = container.get_text("\n", strip=True)
    if len(body) < MIN_BODY_CHARS:
        return None

    if netloc == "news.delaware.gov":
        body = _trim_news_delaware_duplicate_press_rail(body)
        body = _dedupe_news_delaware_paragraph_blocks(body)

    if netloc in ("www.usmarshals.gov", "usmarshals.gov"):
        body = _trim_usmarshals_postface(body)

    pub_date = resolve_publication_date(soup, url, body)
    byline = format_display_byline(pub_date, soup)

    return title.strip(), byline.strip(), body.strip(), pub_date


def write_pdf(
    out_path: Path,
    title: str,
    byline: str,
    body: str,
    url: str,
    pub_date: date | None,
) -> bool:
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )
    story = [Paragraph(esc(title), _TITLE_S)]
    if byline:
        story.append(Paragraph(esc(byline), _META_S))
    if pub_date:
        story.append(
            Paragraph(esc(f"Publication date: {pub_date.isoformat()}"), _META_S)
        )
    story.append(Paragraph(f"Source: {esc(url)}", _SOURCE_S))
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.HexColor("#cccccc"),
            spaceAfter=8,
        )
    )
    for block in re.split(r"\n\s*\n+", body):
        block = block.strip()
        if block:
            story.append(Paragraph(esc(block), _BODY_S))
    try:
        doc.build(story)
        return True
    except Exception as e:
        print(f"    [pdf error] {e}", file=sys.stderr)
        return False


def merge(pdf_paths: list[Path], out_path: Path) -> bool:
    writer = PdfWriter()
    merged = 0
    for p in pdf_paths:
        try:
            for page in PdfReader(str(p)).pages:
                writer.add_page(page)
            merged += 1
        except Exception as e:
            print(f"  [merge warn] skip {p.name}: {e}", file=sys.stderr)
    if not merged:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)
    return True


def _per_url_cache_pdf(tmp_dir: Path, index: int, url: str) -> Path:
    """
    Per-URL cache filename under tmp_dir (index prefix keeps merge order).
    Avoids reusing slot ``0001.pdf`` from a different url-file (e.g. Anchorage vs Oregon).
    """
    h = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]
    return tmp_dir / f"{index:04d}_{h}.pdf"


def main():
    ap = argparse.ArgumentParser(
        description="Scrape HTML URLs from a list into one merged PDF.",
    )
    ap.add_argument("--url-file", type=Path, default=DEFAULT_URL_FILE)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--out-name", default=DEFAULT_OUT_NAME)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=REQUEST_DELAY)
    ap.add_argument(
        "--referer",
        default=None,
        help="HTTP Referer header (default: origin of each URL).",
    )
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (use only if the host has chain issues).",
    )
    ap.add_argument(
        "--jina-fallback",
        action="store_true",
        help="If direct HTML fetch fails (e.g. 403), retry via https://r.jina.ai/ reader markdown.",
    )
    args = ap.parse_args()

    verify_tls = not args.insecure
    if args.insecure:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass

    if not args.url_file.is_file():
        sys.exit(f"URL file not found: {args.url_file}")

    all_urls = load_urls(args.url_file)
    urls = all_urls[: args.limit] if args.limit else all_urls

    print(f"\n{'='*55}")
    print(f"  URL file  : {args.url_file}")
    print(f"  Total URLs: {len(all_urls)}  |  processing: {len(urls)}")
    print(f"  Output    : {args.out_dir / args.out_name}")
    print(f"{'='*55}\n")

    tmp_dir = args.out_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    successes: list[Path] = []
    failures: list[str] = []

    for i, url in enumerate(urls, start=1):
        slug = url.rstrip("/").split("/")[-1][:65]
        print(f"  [{i}/{len(urls)}] {slug}")

        out_pdf = _per_url_cache_pdf(tmp_dir, i, url)
        if out_pdf.exists() and out_pdf.stat().st_size > 500:
            print("    [cached]")
            successes.append(out_pdf)
            continue

        parsed = urlparse(url)
        ref = args.referer or f"{parsed.scheme}://{parsed.netloc}/"
        hdrs = _default_headers(referer=ref)
        path_lower = parsed.path.lower()
        if path_lower.endswith(".pdf"):
            raw = fetch_bytes(url, hdrs, verify=verify_tls)
            if not raw:
                failures.append(url)
                time.sleep(args.delay)
                continue
            result = extract_from_native_pdf(raw, url)
            if not result:
                print("    [FAILED] native PDF: body too thin")
                failures.append(url)
                time.sleep(args.delay)
                continue
            title, byline, body, pub_date = result
            ok = write_pdf(out_pdf, title, byline, body, url, pub_date)
            if ok:
                kb = out_pdf.stat().st_size // 1024
                print(f"    [ok pdf] {kb} KB - {title[:65]}")
                successes.append(out_pdf)
            else:
                failures.append(url)
            time.sleep(args.delay)
            continue

        use_jina_first = args.jina_fallback and (
            "cbp.gov" in url.lower() or "usmarshals.gov" in url.lower()
        )
        if use_jina_first:
            tag = "cbp" if "cbp.gov" in url.lower() else "usms"
            print(f"    [{tag}] r.jina.ai reader ...")
            html = fetch_via_jina_reader(url, verify=verify_tls)
        else:
            html = fetch(url, hdrs, verify=verify_tls)
            if not html and args.jina_fallback:
                print("    [fallback] r.jina.ai reader ...")
                html = fetch_via_jina_reader(url, verify=verify_tls)
        if not html:
            failures.append(url)
            time.sleep(args.delay)
            continue

        is_jina = html.lstrip().startswith("Title:") and "Markdown Content:" in html
        html_j: str | None = None
        if is_jina:
            result = extract_from_jina_reader(html, url)
        else:
            result = extract(html, url)
        if not result and args.jina_fallback:
            print("    [fallback] r.jina.ai reader (thin or empty extract) ...")
            html_j = fetch_via_jina_reader(url, verify=verify_tls)
            if html_j:
                is_j2 = html_j.lstrip().startswith("Title:") and "Markdown Content:" in html_j
                if is_j2:
                    result = extract_from_jina_reader(html_j, url)
                else:
                    result = extract(html_j, url)
        body_so_far = ((result[2] if result else "") or "").strip()
        doj_url = (
            _ncis_doj_follow_url(url, body_so_far, html, html_j)
            if args.jina_fallback
            else None
        )
        if doj_url:
            print(f"    [ncis] follow DOJ release …")
            doj_blob = fetch_via_jina_reader(doj_url, verify=verify_tls)
            if doj_blob:
                if doj_blob.lstrip().startswith("Title:"):
                    doj_result = extract_from_jina_reader(doj_blob, doj_url)
                else:
                    doj_result = extract(doj_blob, doj_url)
                if doj_result and (
                    not result or len(doj_result[2]) > len((result[2] if result else "") or "")
                ):
                    result = doj_result
        if not result:
            print("    [FAILED] extract: body too thin")
            failures.append(url)
            time.sleep(args.delay)
            continue

        title, byline, body, pub_date = result
        ok = write_pdf(out_pdf, title, byline, body, url, pub_date)

        if ok:
            kb = out_pdf.stat().st_size // 1024
            print(f"    [ok] {kb} KB - {title[:65]}")
            successes.append(out_pdf)
        else:
            failures.append(url)

        time.sleep(args.delay)

    print(f"\n  Succeeded: {len(successes)}  |  Failed: {len(failures)}")

    if not successes:
        sys.exit("No PDFs to merge.")

    out_pdf = args.out_dir / args.out_name
    print(f"\nMerging {len(successes)} PDFs -> {out_pdf} ...")
    if merge(successes, out_pdf):
        mb = out_pdf.stat().st_size / 1024 / 1024
        print(f"-> {out_pdf}  ({mb:.2f} MB)\n")
    else:
        sys.exit("Merge failed.")

    if failures:
        print(f"\nFailed URLs ({len(failures)}):")
        for u in failures:
            print(f"  {u}")


if __name__ == "__main__":
    main()
