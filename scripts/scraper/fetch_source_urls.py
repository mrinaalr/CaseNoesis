#!/usr/bin/env python3
"""
Collect http(s) links from one or more HTML pages.

Give a page URL (or a paginated URL template), resolve all anchor hrefs to
absolute URLs, optionally filter by host/path/substrings, and write a
deduplicated list for scrape_pdf.py.

Examples
--------
Single listing page::

    python3 fetch_source_urls.py --url https://example.org/reports \\
        --same-host --path-prefix /cases/ -o cases.txt

Drupal-style search (e.g. Vermont AG), stop when no results text appears::

    python3 fetch_source_urls.py \\
        --url-template 'https://ago.vermont.gov/search/node?keys=child&page={page}' \\
        --page-range 0:40 \\
        --same-host --path-prefix /blog/ \\
        --require-any-from patterns/vermont_icac_require.txt \\
        --exclude-from patterns/vermont_icac_exclude.txt \\
        --stop-if-text 'your search yielded no results' \\
        -o vermont_icac_urls.txt

deps: pip install requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("pip install requests beautifulsoup4")

DEFAULT_DELAY = 1.2
DEFAULT_TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


def _read_patterns(path: str | None) -> list[str]:
    if not path:
        return []
    lines: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                lines.append(s)
    return lines


def fetch(url: str, timeout: int, *, verify: bool = True) -> tuple[str | None, int]:
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
            verify=verify,
        )
        return r.text, r.status_code
    except Exception as e:
        print(f"  [error] {url}: {e}", file=sys.stderr)
        return None, 0


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def _path(url: str) -> str:
    return urlparse(url).path or "/"


def collect_from_html(
    html: str,
    page_url: str,
    *,
    same_host: bool,
    extra_hosts: frozenset[str] | None,
    path_prefix: str | None,
    exclude_substrings: list[str],
    require_any_substrings: list[str],
    https_only: bool,
) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = _host(page_url)
    allowed: frozenset[str] | None = None
    if same_host:
        allowed = frozenset({base_host, *(extra_hosts or ())})
    path_prefix_l = path_prefix.lower() if path_prefix else None
    exclude_l = [p.lower() for p in exclude_substrings]
    require_l = [p.lower() for p in require_any_substrings]

    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        raw = a["href"].strip()
        if not raw or raw.startswith(("#", "mailto:", "javascript:")):
            continue
        abs_url = urljoin(page_url, raw)
        p = urlparse(abs_url)
        if https_only:
            if p.scheme != "https":
                continue
        elif p.scheme not in ("http", "https"):
            continue

        abs_url = abs_url.split("#", 1)[0]
        host = _host(abs_url)
        if allowed is not None and host not in allowed:
            continue
        if path_prefix_l and not _path(abs_url).lower().startswith(path_prefix_l):
            continue
        lower = abs_url.lower()
        if any(ex in lower for ex in exclude_l):
            continue
        if require_l and not any(req in lower for req in require_l):
            continue
        if abs_url not in seen:
            seen.add(abs_url)
            out.append(abs_url)
    return out


def _normalize_regex_extracted_url(raw: str) -> str | None:
    """Trim JSON/HTML junk from a URL substring (e.g. Search.gov embedded links)."""
    s = raw.strip()
    for sep in ("&quot;", "&quot", "\\u0026quot;", "%22", "\\", '"', "'", "<", ">"):
        if sep in s:
            s = s.split(sep)[0]
    s = s.strip().rstrip(".,);]}")
    if not s.startswith("http"):
        return None
    s = s.split("#", 1)[0]
    if len(s) > 500:
        s = s[:500]
    return s or None


def collect_from_regex(
    html: str,
    pattern: re.Pattern[str],
    *,
    path_prefix: str | None,
    exclude_substrings: list[str],
    require_any_substrings: list[str],
    https_only: bool,
) -> list[str]:
    """Find URL-shaped strings in raw HTML (e.g. JSON-LD / Search.gov results)."""
    path_prefix_l = path_prefix.lower() if path_prefix else None
    exclude_l = [p.lower() for p in exclude_substrings]
    require_l = [p.lower() for p in require_any_substrings]
    out: list[str] = []
    seen: set[str] = set()
    for m in pattern.finditer(html or ""):
        raw = m.group(0)
        abs_url = _normalize_regex_extracted_url(raw)
        if not abs_url:
            continue
        p = urlparse(abs_url)
        if https_only and p.scheme != "https":
            continue
        if not https_only and p.scheme not in ("http", "https"):
            continue
        if path_prefix_l and not _path(abs_url).lower().startswith(path_prefix_l):
            continue
        lower = abs_url.lower()
        if any(ex in lower for ex in exclude_l):
            continue
        if require_l and not any(req in lower for req in require_l):
            continue
        if abs_url not in seen:
            seen.add(abs_url)
            out.append(abs_url)
    return out


def parse_page_range(spec: str) -> range:
    """'0:29' -> inclusive 0..29."""
    if ":" not in spec:
        raise argparse.ArgumentTypeError("page-range must look like START:END (e.g. 0:29)")
    a, b = spec.split(":", 1)
    start, end = int(a.strip()), int(b.strip())
    if end < start:
        raise argparse.ArgumentTypeError("END must be >= START")
    return range(start, end + 1)


def iter_page_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    for u in args.url or []:
        urls.append(u)
    if args.url_template:
        for n in args.page_range:
            urls.append(args.url_template.format(page=n, n=n))
    if not urls:
        raise SystemExit("Provide --url and/or --url-template with --page-range.")
    return urls


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Collect links from HTML pages (optionally paginated)."
    )
    ap.add_argument("--url", action="append", default=[], help="A page to fetch (repeatable).")
    ap.add_argument(
        "--url-template",
        metavar="TEMPLATE",
        help="URL with {page} or {n} for pagination (use with --page-range).",
    )
    ap.add_argument(
        "--page-range",
        type=parse_page_range,
        metavar="START:END",
        help="Inclusive page numbers substituted into --url-template.",
    )
    ap.add_argument("-o", "--out", default="source_urls.txt", help="Output text file.")
    ap.add_argument("--same-host", action="store_true", help="Keep only links on the seed page's host.")
    ap.add_argument(
        "--also-host",
        action="append",
        default=[],
        metavar="HOST",
        help="Allow this host in addition to the page host (implies --same-host).",
    )
    ap.add_argument(
        "--path-prefix",
        metavar="PREFIX",
        help="Keep only URLs whose path starts with this (e.g. /blog/).",
    )
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SUBSTR",
        help="Drop URLs containing this substring (case-insensitive). Repeatable.",
    )
    ap.add_argument(
        "--exclude-from",
        metavar="FILE",
        help="File with one exclude substring per line.",
    )
    ap.add_argument(
        "--require-any",
        action="append",
        default=[],
        metavar="SUBSTR",
        help="Keep only URLs that contain at least one of these (case-insensitive). "
        "If none given, no 'must match' filter.",
    )
    ap.add_argument(
        "--require-any-from",
        metavar="FILE",
        help="File with one required substring per line (any match keeps URL).",
    )
    ap.add_argument(
        "--stop-if-text",
        action="append",
        default=[],
        metavar="TEXT",
        help="If page HTML contains this (case-insensitive), stop pagination after this page.",
    )
    ap.add_argument(
        "--allow-http",
        action="store_true",
        help="Allow http:// links (default: https only).",
    )
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (use only if the host has chain issues).",
    )
    ap.add_argument(
        "--max-consecutive-empty",
        type=int,
        default=2,
        metavar="N",
        help="Stop pagination after N pages in a row with no new URLs.",
    )
    ap.add_argument(
        "--raw-url-regex",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Python regex scanned against raw HTML for URLs (e.g. Search.gov JSON). "
        "Repeatable. Use a pattern that matches full https URLs.",
    )
    args = ap.parse_args()

    if args.url_template and args.page_range is None:
        ap.error("--url-template requires --page-range START:END")

    compiled_regexes: list[re.Pattern[str]] = []
    for pat in args.raw_url_regex or []:
        try:
            compiled_regexes.append(re.compile(pat))
        except re.error as e:
            ap.error(f"Invalid --raw-url-regex: {e}")

    exclude = list(args.exclude) + _read_patterns(args.exclude_from)
    require_any = list(args.require_any) + _read_patterns(args.require_any_from)
    https_only = not args.allow_http

    same_host = args.same_host or bool(args.also_host)
    extra_hosts: frozenset[str] | None = None
    if args.also_host:
        extra_hosts = frozenset(h.lower().lstrip(".") for h in args.also_host)

    page_urls = iter_page_urls(args)
    all_urls: list[str] = []
    seen_global: set[str] = set()
    consecutive_empty = 0
    stop_texts = [t.lower() for t in args.stop_if_text]

    verify_tls = not args.insecure
    if args.insecure:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass

    for i, page_url in enumerate(page_urls):
        print(f"  [{i + 1}/{len(page_urls)}] {page_url}", file=sys.stderr)
        html, status = fetch(page_url, args.timeout, verify=verify_tls)
        if status == 404 or not html:
            print(f"  [stop] HTTP {status}", file=sys.stderr)
            break
        lower_html = html.lower()
        if stop_texts and any(t in lower_html for t in stop_texts):
            print("  [stop] stop-if-text matched", file=sys.stderr)
            # still collect from this page first
            batch = collect_from_html(
                html,
                page_url,
                same_host=same_host,
                extra_hosts=extra_hosts,
                path_prefix=args.path_prefix,
                exclude_substrings=exclude,
                require_any_substrings=require_any,
                https_only=https_only,
            )
            for rx in compiled_regexes:
                batch.extend(
                    collect_from_regex(
                        html,
                        rx,
                        path_prefix=args.path_prefix,
                        exclude_substrings=exclude,
                        require_any_substrings=require_any,
                        https_only=https_only,
                    )
                )
            seen_b2: set[str] = set()
            batch = [u for u in batch if not (u in seen_b2 or seen_b2.add(u))]
            new = [u for u in batch if u not in seen_global]
            for u in new:
                seen_global.add(u)
            all_urls.extend(new)
            print(f"    -> {len(new)} new (total {len(all_urls)})", file=sys.stderr)
            break

        batch = collect_from_html(
            html,
            page_url,
            same_host=same_host,
            extra_hosts=extra_hosts,
            path_prefix=args.path_prefix,
            exclude_substrings=exclude,
            require_any_substrings=require_any,
            https_only=https_only,
        )
        for rx in compiled_regexes:
            batch.extend(
                collect_from_regex(
                    html,
                    rx,
                    path_prefix=args.path_prefix,
                    exclude_substrings=exclude,
                    require_any_substrings=require_any,
                    https_only=https_only,
                )
            )
        seen_batch: list[str] = []
        seen_b: set[str] = set()
        for u in batch:
            if u not in seen_b:
                seen_b.add(u)
                seen_batch.append(u)
        batch = seen_batch
        new = [u for u in batch if u not in seen_global]
        for u in new:
            seen_global.add(u)
        all_urls.extend(new)
        print(f"    -> {len(new)} new (total {len(all_urls)})", file=sys.stderr)

        if len(new) == 0:
            consecutive_empty += 1
            if consecutive_empty >= args.max_consecutive_empty:
                print(
                    f"  [stop] {args.max_consecutive_empty} consecutive pages with no new URLs",
                    file=sys.stderr,
                )
                break
        else:
            consecutive_empty = 0

        time.sleep(args.delay)

    with open(args.out, "w", encoding="utf-8") as f:
        for u in all_urls:
            f.write(u + "\n")

    print(f"\nTotal URLs: {len(all_urls)}", file=sys.stderr)
    print(f"Saved -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
