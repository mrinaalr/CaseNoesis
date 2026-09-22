#!/usr/bin/env python3
"""Honest multi-source harvest into data/collected/{press_releases,recap}/bulk.

NHSR #8252. Public press pages and free RECAP only. Never purchases PACER.
Does not auto-ingest.

Phases:
  doj        DOJ News API (criminal-stage gate already in harvest_doj_press)
  agencies   CaseLinker source list: sitemaps, HTML search, search.usa.gov
  pdf        Merged press PDFs from kept JSONL (no second fetch)
  recap      Up to N free RECAP PDFs linked from harvested press bodies

Usage:
  python3 collector/run_source_bulk.py --phase doj
  python3 collector/run_source_bulk.py --phase agencies
  python3 collector/run_source_bulk.py --phase pdf
  python3 collector/run_source_bulk.py --phase recap --max-recap 250
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fetch_source_urls import (  # noqa: E402
    collect_from_html,
    collect_squarespace_general_search_urls,
    collect_usa_search_urls,
    collect_google_cse_search_pages,
    fetch as fetch_listing,
)
from harvest_doj_press import NOISE_RE, classify_stage  # noqa: E402

NHSR = "UMass HRPO NHSR #8252 (16 Sep 2026)"
BULK_PRESS = REPO / "data" / "collected" / "press_releases" / "bulk"
BULK_RECAP = REPO / "data" / "collected" / "recap" / "bulk"
MANIFESTS = REPO / "data" / "collected" / "manifests"
RECORDS = BULK_PRESS / "records"
URLS = BULK_PRESS / "urls"
PDFS = BULK_PRESS / "pdf"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

EXCLUDE_URL = [
    "/tag/",
    "/category/",
    "/feed",
    "/author/",
    "/wp-content",
    "/login",
    "/contact",
    "/careers",
    "/staff",
    "/privacy",
    "/accessibility",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
    "mailto:",
    ".jpg",
    ".png",
    ".css",
    ".js",
    "/search?",
    "/search/",
    "search_results",
]

CRIMINAL_RE = re.compile(
    r"\b(?:sentenc\w*|plead(?:s|ed|ing)?|guilty|convict\w*|indict\w*|"
    r"charg(?:ed|es|ing)|arrest(?:ed|s)?|criminal complaint)\b",
    re.I,
)
FORCED_RE = re.compile(
    r"forced labou?r|labor trafficking|labour trafficking|peonage|involuntary servitude",
    re.I,
)
TRAFFICK_RE = re.compile(
    r"human trafficking|sex trafficking|child sex trafficking|trafficking in persons|"
    r"labor trafficking|labour trafficking",
    re.I,
)
CYBER_RE = re.compile(
    r"ransomware|business email compromise|\bBEC\b|computer fraud|phishing|"
    r"pig butcher|cryptocurrency fraud|cyber[- ]enabled",
    re.I,
)
FRAUD_RE = re.compile(
    r"\b(?:wire fraud|mail fraud|bank fraud|elder fraud|romance scam|investment fraud|"
    r"lottery scam|grandparent scam|identity theft|money laundering|securities fraud|"
    r"scheme to defraud)\b|\bfraud\b|\bscam\b",
    re.I,
)
CIVIL_TITLE_RE = re.compile(
    r"\b(?:scam alert|consumer alert|how to avoid|awareness month|civil settlement|"
    r"assurance of voluntary|tips for (?:avoiding|spotting))\b",
    re.I,
)
DRUG_TITLE_RE = re.compile(
    r"\b(?:fentanyl|cocaine|heroin|methamphetamine|marijuana|narcotics?|"
    r"controlled substance|drug traffick\w*)\b",
    re.I,
)
PERSON_TITLE_RE = re.compile(
    r"human trafficking|sex trafficking|forced labou?r|elder|romance|"
    r"ransomware|business email|wire fraud|mail fraud|investment fraud|"
    r"labor trafficking|peonage|involuntary servitude",
    re.I,
)
SLUG_KEEP_RE = re.compile(
    r"human-traffick|sex-traffick|labor-traffick|child-sex-traffick|"
    r"forced-labor|forced-labour|servitude|peonage",
    re.I,
)
SLUG_DROP_RE = re.compile(
    r"drug-traffick|fentanyl|cocaine|heroin|methamphetamine|marijuana|"
    r"protect-yourself|how-to-|awareness|scam-alert|tips-|wildlife",
    re.I,
)
NAME_RE = re.compile(
    r"\b([A-Z][a-z]+(?:[ \-][A-Z][a-z]+){1,3}),\s+\d{2}\b"
)
SKIP_NAME_RE = re.compile(
    r"\b(?:United States|Attorney General|District Judge|Special Agent|"
    r"United States Attorney|Department of Justice|Secret Service)\b",
    re.I,
)

# CaseLinker visualization/sources.html entries retargeted off ICAC-only queries.
HTML_SOURCES: list[dict] = [
    {
        "id": "texas_ag",
        "name": "Texas Office of the Attorney General",
        "queries": [
            "https://www.texasattorneygeneral.gov/news/search?keys=human+trafficking",
            "https://www.texasattorneygeneral.gov/news/search?keys=forced+labor",
            "https://www.texasattorneygeneral.gov/news/search?keys=elder+fraud",
            "https://www.texasattorneygeneral.gov/news/search?keys=ransomware",
            "https://www.texasattorneygeneral.gov/news/categories/cyber-crimes",
        ],
    },
    {
        "id": "illinois_ag",
        "name": "Illinois Attorney General",
        "queries": [
            "https://illinoisattorneygeneral.gov/site-search-page/press-releases/index?q=trafficking",
            "https://illinoisattorneygeneral.gov/site-search-page/press-releases/index?q=forced+labor",
            "https://illinoisattorneygeneral.gov/site-search-page/press-releases/index?q=elder+fraud",
            "https://illinoisattorneygeneral.gov/site-search-page/press-releases/index?q=ransomware",
            "https://illinoisattorneygeneral.gov/site-search-page/press-releases/index?q=wire+fraud",
        ],
    },
    {
        "id": "nj_ag",
        "name": "New Jersey Office of the Attorney General",
        "queries": [
            "https://www.njoag.gov/?s=human+trafficking",
            "https://www.njoag.gov/?s=forced+labor",
            "https://www.njoag.gov/?s=elder+fraud",
            "https://www.njoag.gov/?s=ransomware",
            "https://www.njoag.gov/?s=wire+fraud",
        ],
    },
    {
        "id": "wa_ag",
        "name": "Washington State Office of the Attorney General",
        "queries": [
            "https://www.atg.wa.gov/news/search/trafficking",
            "https://www.atg.wa.gov/news/search/forced%20labor",
            "https://www.atg.wa.gov/news/search/elder%20fraud",
            "https://www.atg.wa.gov/news/search/ransomware",
            "https://www.atg.wa.gov/news/search/wire%20fraud",
        ],
    },
    {
        "id": "gbi",
        "name": "Georgia Bureau of Investigation",
        "queries": [
            "https://gbi.georgia.gov/search/results?query=trafficking",
            "https://gbi.georgia.gov/search/results?query=forced%20labor",
            "https://gbi.georgia.gov/search/results?query=elder%20fraud",
            "https://gbi.georgia.gov/search/results?query=ransomware",
            "https://gbi.georgia.gov/search/results?query=fraud",
        ],
    },
    {
        "id": "pa_ag",
        "name": "Pennsylvania Office of the Attorney General",
        "queries": [
            "https://www.attorneygeneral.gov/taking-action-search-results/?swpquery=trafficking",
            "https://www.attorneygeneral.gov/taking-action-search-results/?swpquery=forced%20labor",
            "https://www.attorneygeneral.gov/taking-action-search-results/?swpquery=elder%20fraud",
            "https://www.attorneygeneral.gov/taking-action-search-results/?swpquery=ransomware",
            "https://www.attorneygeneral.gov/taking-action-search-results/?swpquery=wire%20fraud",
        ],
    },
    {
        "id": "ohio_ag",
        "name": "Ohio Attorney General",
        "queries": [
            "https://www.ohioattorneygeneral.gov/Media/News-Releases/News-Releases-Search-Results?searchtext=trafficking&searchmode=anyword",
            "https://www.ohioattorneygeneral.gov/Media/News-Releases/News-Releases-Search-Results?searchtext=forced%20labor&searchmode=anyword",
            "https://www.ohioattorneygeneral.gov/Media/News-Releases/News-Releases-Search-Results?searchtext=elder%20fraud&searchmode=anyword",
            "https://www.ohioattorneygeneral.gov/Media/News-Releases/News-Releases-Search-Results?searchtext=ransomware&searchmode=anyword",
            "https://www.ohioattorneygeneral.gov/Media/News-Releases/News-Releases-Search-Results?searchtext=wire%20fraud&searchmode=anyword",
        ],
    },
    {
        "id": "florida_ag",
        "name": "Florida Office of the Attorney General",
        "queries": [
            "https://www.myfloridalegal.com/search/pages?keys=human+trafficking",
            "https://www.myfloridalegal.com/search/pages?keys=forced+labor",
            "https://www.myfloridalegal.com/search/pages?keys=elder+fraud",
            "https://www.myfloridalegal.com/search/pages?keys=ransomware",
            "https://www.myfloridalegal.com/search/pages?keys=wire+fraud",
        ],
        "jina": True,
    },
    {
        "id": "oregon_doj",
        "name": "Oregon Department of Justice",
        "queries": [
            "https://www.doj.state.or.us/?s=trafficking",
            "https://www.doj.state.or.us/?s=forced+labor",
            "https://www.doj.state.or.us/?s=elder+fraud",
            "https://www.doj.state.or.us/?s=ransomware",
            "https://www.doj.state.or.us/?s=wire+fraud",
        ],
    },
    {
        "id": "michigan_sp",
        "name": "Michigan State Police",
        "queries": [
            "https://www.michigan.gov/mspnewsroom/news-releases?q=trafficking",
            "https://www.michigan.gov/mspnewsroom/news-releases?q=fraud",
        ],
    },
    {
        "id": "tbi",
        "name": "Tennessee Bureau of Investigation",
        "queries": [
            "https://tbinewsroom.com/?s=trafficking",
            "https://tbinewsroom.com/?s=forced+labor",
            "https://tbinewsroom.com/?s=elder+fraud",
            "https://tbinewsroom.com/?s=ransomware",
            "https://tbinewsroom.com/?s=wire+fraud",
        ],
    },
    {
        "id": "louisiana_ag",
        "name": "Louisiana Office of the Attorney General",
        "queries": [
            "https://www.ag.state.la.us/News/Page/1",
        ],
    },
    {
        "id": "mississippi_ag",
        "name": "Mississippi Attorney General",
        "queries": [
            "https://attorneygenerallynnfitch.com/?s=trafficking",
            "https://attorneygenerallynnfitch.com/?s=forced+labor",
            "https://attorneygenerallynnfitch.com/?s=elder+fraud",
            "https://attorneygenerallynnfitch.com/?s=fraud",
        ],
    },
    {
        "id": "nm_ag",
        "name": "New Mexico Attorney General",
        "queries": [
            "https://nmdoj.gov/?s=trafficking",
            "https://nmdoj.gov/?s=forced+labor",
            "https://nmdoj.gov/?s=elder+fraud",
            "https://nmdoj.gov/?s=ransomware",
            "https://nmdoj.gov/?s=wire+fraud",
        ],
    },
    {
        "id": "utah_ag",
        "name": "Utah Attorney General",
        "queries": [
            "https://attorneygeneral.utah.gov/?s=trafficking",
            "https://attorneygeneral.utah.gov/?s=forced+labor",
            "https://attorneygeneral.utah.gov/?s=elder+fraud",
            "https://attorneygeneral.utah.gov/?s=ransomware",
            "https://attorneygeneral.utah.gov/?s=fraud",
        ],
    },
    {
        "id": "hawaii_ag",
        "name": "Hawaii Department of the Attorney General",
        "queries": [
            "https://ag.hawaii.gov/?s=trafficking",
            "https://ag.hawaii.gov/?s=forced+labor",
            "https://ag.hawaii.gov/?s=elder+fraud",
            "https://ag.hawaii.gov/?s=fraud",
        ],
    },
    {
        "id": "alea",
        "name": "Alabama Law Enforcement Agency",
        "queries": [
            "https://www.alea.gov/news?combine=trafficking",
            "https://www.alea.gov/news?combine=fraud",
            "https://www.alea.gov/news?combine=elder",
        ],
    },
    {
        "id": "kentucky_sp",
        "name": "Kentucky State Police",
        "queries": [
            "https://www.kentuckystatepolice.ky.gov/news?searchTerm=trafficking",
            "https://www.kentuckystatepolice.ky.gov/news?searchTerm=fraud",
            "https://www.kentuckystatepolice.ky.gov/news?searchTerm=elder",
        ],
    },
    {
        "id": "nebraska_sp",
        "name": "Nebraska State Patrol",
        "queries": [
            "https://statepatrol.nebraska.gov/search/node?keys=trafficking",
            "https://statepatrol.nebraska.gov/search/node?keys=forced%20labor",
            "https://statepatrol.nebraska.gov/search/node?keys=elder%20fraud",
            "https://statepatrol.nebraska.gov/search/node?keys=wire%20fraud",
        ],
    },
    {
        "id": "arkansas_dps",
        "name": "Arkansas Department of Public Safety",
        "queries": [
            "https://dps.arkansas.gov/?s=trafficking",
            "https://dps.arkansas.gov/?s=forced+labor",
            "https://dps.arkansas.gov/?s=elder+fraud",
            "https://dps.arkansas.gov/?s=fraud",
        ],
    },
    {
        "id": "montana_doj",
        "name": "Montana Department of Justice",
        "queries": [
            "https://dojmt.gov/category/press-release/?srch=trafficking",
            "https://dojmt.gov/category/press-release/?srch=fraud",
            "https://dojmt.gov/category/press-release/?srch=elder",
        ],
    },
    {
        "id": "sc_ag",
        "name": "South Carolina Attorney General",
        "queries": [
            "https://www.scag.gov/about-the-office/news/?s=trafficking",
            "https://www.scag.gov/about-the-office/news/?s=fraud",
            "https://www.scag.gov/about-the-office/news/?category=icac",
        ],
    },
    {
        "id": "idaho_ag",
        "name": "Idaho Office of Attorney General",
        "queries": [
            "https://www.ag.idaho.gov/?s=trafficking",
            "https://www.ag.idaho.gov/?s=forced+labor",
            "https://www.ag.idaho.gov/?s=elder+fraud",
            "https://www.ag.idaho.gov/?s=fraud",
        ],
    },
    {
        "id": "nc_sbi",
        "name": "North Carolina State Bureau of Investigation",
        "queries": [
            "https://www.ncsbi.gov/getdoc/ae19a2eb-38f4-4653-9390-9fc0016f7985/Search-Results.aspx?searchtext=trafficking&searchmode=anyword",
            "https://www.ncsbi.gov/getdoc/ae19a2eb-38f4-4653-9390-9fc0016f7985/Search-Results.aspx?searchtext=fraud&searchmode=anyword",
        ],
    },
    {
        "id": "ri_ag",
        "name": "Rhode Island Office of the Attorney General",
        "queries": [
            "https://riag.ri.gov/search?search_api_fulltext=trafficking",
            "https://riag.ri.gov/search?search_api_fulltext=forced%20labor",
            "https://riag.ri.gov/search?search_api_fulltext=elder%20fraud",
            "https://riag.ri.gov/search?search_api_fulltext=wire%20fraud",
        ],
    },
    {
        "id": "vt_ag",
        "name": "Vermont Office of the Attorney General",
        "queries": [
            "https://ago.vermont.gov/search/node?keys=trafficking",
            "https://ago.vermont.gov/search/node?keys=forced%20labor",
            "https://ago.vermont.gov/search/node?keys=elder%20fraud",
            "https://ago.vermont.gov/search/node?keys=wire%20fraud",
        ],
    },
    {
        "id": "nysp",
        "name": "New York State Police",
        "queries": [
            "https://troopers.ny.gov/nysp-newsroom?keyword=trafficking",
            "https://troopers.ny.gov/nysp-newsroom?keyword=fraud",
            "https://troopers.ny.gov/nysp-newsroom?keyword=elder",
        ],
        "jina": True,
    },
    {
        "id": "lapd",
        "name": "Los Angeles Police Department",
        "queries": [
            "https://www.lapdonline.org/?s=trafficking",
            "https://www.lapdonline.org/?s=forced+labor",
            "https://www.lapdonline.org/?s=elder+fraud",
            "https://www.lapdonline.org/?s=fraud",
        ],
    },
    {
        "id": "spd",
        "name": "Seattle Police Department",
        "queries": [
            "https://spdblotter.seattle.gov/?s=trafficking",
            "https://spdblotter.seattle.gov/?s=fraud",
            "https://spdblotter.seattle.gov/?s=elder",
        ],
    },
    {
        "id": "sd_ag",
        "name": "South Dakota Office of the Attorney General",
        "queries": [
            "https://atg.sd.gov/OurOffice/Media/pressreleases.aspx",
        ],
    },
    {
        "id": "wyoming_dci",
        "name": "Wyoming Division of Criminal Investigation",
        "queries": [
            "https://wyomingdci.wyo.gov/dci-homepage/news",
        ],
    },
    {
        "id": "cook_county",
        "name": "Cook County State's Attorney",
        "queries": [
            "https://www.cookcountystatesattorney.org/news",
        ],
    },
    {
        "id": "anchorage_pd",
        "name": "Anchorage Police Department",
        "mode": "squarespace",
        "queries": [
            "https://www.anchoragepolice.com/search?q=trafficking",
            "https://www.anchoragepolice.com/search?q=fraud",
            "https://www.anchoragepolice.com/search?q=elder",
        ],
    },
    {
        "id": "iowa_dci",
        "name": "Iowa Division of Criminal Investigation",
        "mode": "cse",
        "queries": [
            "https://dps.iowa.gov/search?q=trafficking#gsc.q=trafficking&gsc.page=1",
            "https://dps.iowa.gov/search?q=fraud#gsc.q=fraud&gsc.page=1",
            "https://dps.iowa.gov/search?q=elder#gsc.q=elder&gsc.page=1",
        ],
    },
    {
        "id": "lvmpd",
        "name": "Las Vegas Metropolitan Police Department",
        "queries": [
            "https://www.lvmpd.com/services/advanced-components/misc-pages/search?q=trafficking",
            "https://www.lvmpd.com/services/advanced-components/misc-pages/search?q=fraud",
        ],
    },
    {
        "id": "fresno_so",
        "name": "Fresno County Sheriff's Office",
        "queries": [
            "https://www.fresnosheriff.org/search.html?q=trafficking",
            "https://www.fresnosheriff.org/search.html?q=fraud",
        ],
    },
    {
        "id": "osceola_so",
        "name": "Osceola County Sheriff's Office",
        "queries": [
            "https://www.osceolasheriff.org/?s=trafficking",
            "https://www.osceolasheriff.org/?s=fraud",
        ],
    },
]

USA_SOURCES = [
    {
        "id": "usms",
        "name": "U.S. Marshals Service",
        "affiliate": "us-marshals-service",
        "host": "usmarshals.gov",
        "queries": ["human trafficking", "forced labor", "elder fraud", "wire fraud", "ransomware"],
    },
    {
        "id": "ncis",
        "name": "Naval Criminal Investigative Service",
        "affiliate": "navy_ncis",
        "host": "ncis.navy.mil",
        "queries": ["human trafficking", "forced labor", "fraud", "ransomware"],
    },
    {
        "id": "afosi",
        "name": "U.S. Air Force Office of Special Investigations",
        "affiliate": "afosi",
        "host": "osi.af.mil",
        "queries": ["trafficking", "fraud", "elder"],
    },
    {
        "id": "army_cid",
        "name": "U.S. Army Criminal Investigation Division",
        "affiliate": "army_cid",
        "host": "cid.army.mil",
        "queries": ["trafficking", "fraud", "forced labor"],
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(url: str) -> str:
    u = (url or "").strip().rstrip("/").lower()
    u = re.sub(r"^https?://(?:www\.)?", "https://www.", u)
    u = re.sub(r"\?.*$", "", u)
    u = re.sub(r"#.*$", "", u)
    return u


def _mkdirs() -> None:
    for p in (BULK_PRESS, BULK_RECAP, RECORDS, URLS, PDFS, BULK_RECAP / "manifests"):
        p.mkdir(parents=True, exist_ok=True)


def _write_status(name: str, payload: dict) -> None:
    path = BULK_PRESS / name
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def collected_urls() -> set[str]:
    urls: set[str] = set()
    if MANIFESTS.is_dir():
        for path in MANIFESTS.rglob("*.json"):
            if path.name in {"COLLECTION.json", "MANIFEST.json"}:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            _collect_urls(data, urls)
    if RECORDS.is_dir():
        for path in RECORDS.glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("source_url"):
                    urls.add(_norm(rec["source_url"]))
    return urls


def _collect_urls(obj: object, urls: set[str]) -> None:
    if isinstance(obj, dict):
        if obj.get("kind") == "court":
            return
        raw = obj.get("source_url") or (obj.get("record") or {}).get("source_url")
        if isinstance(raw, str) and raw.startswith("http"):
            urls.add(_norm(raw))
        for v in obj.values():
            if isinstance(v, (dict, list)):
                _collect_urls(v, urls)
    elif isinstance(obj, list):
        for item in obj:
            _collect_urls(item, urls)


def label_domain(title: str, body: str) -> str | None:
    """Criminal exploitation case, or None when the page is noise / off-mission."""
    title = title or ""
    body = body or ""
    if len(body.strip()) < 80:
        return None
    if CIVIL_TITLE_RE.search(title) or NOISE_RE.search(title):
        return None
    stage_blob = title if classify_stage(title) != "other" else f"{title}\n{body[:1800]}"
    if not CRIMINAL_RE.search(stage_blob):
        return None
    if DRUG_TITLE_RE.search(title) and not PERSON_TITLE_RE.search(title):
        return None
    blob = f"{title}\n{body[:4000]}"
    if FORCED_RE.search(blob):
        return "forced_labor"
    if TRAFFICK_RE.search(blob):
        return "trafficking"
    return None


def _articleish(url: str) -> bool:
    path = urlparse(url).path
    if path.count("/") < 1:
        return False
    slug = path.rstrip("/").split("/")[-1].lower()
    if slug in {"index", "search", "news", "newsroom", "press", "media", "home", "page"}:
        return False
    if len(slug) < 8 and not slug.isdigit():
        return False
    low = url.lower()
    if any(ex in low for ex in EXCLUDE_URL):
        return False
    return True


def _sitemap_locs(url: str, *, timeout: int = 60) -> list[str]:
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
    except requests.RequestException as exc:
        print(f"  sitemap fail {url}: {exc}", file=sys.stderr)
        return []
    if r.status_code != 200:
        print(f"  sitemap HTTP {r.status_code} {url}", file=sys.stderr)
        return []
    return re.findall(r"<loc>([^<]+)</loc>", r.text)


def ice_release_urls() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for page in range(1, 6):
        locs = _sitemap_locs(f"https://www.ice.gov/sitemap.xml?page={page}")
        for u in locs:
            if "/news/releases/" not in u:
                continue
            slug = u.rstrip("/").split("/")[-1]
            if SLUG_DROP_RE.search(slug) or not SLUG_KEEP_RE.search(slug):
                continue
            # bare "traffick" without human/sex/labor/forced is mostly drug cases
            low = slug.lower()
            if "traffick" in low and not any(
                k in low for k in ("human", "sex", "labor", "labour", "forced", "child")
            ):
                continue
            n = _norm(u)
            if n not in seen:
                seen.add(n)
                out.append(u.split("?")[0])
        time.sleep(0.3)
    return out


def usss_release_urls() -> list[str]:
    locs = _sitemap_locs("https://www.secretservice.gov/sitemap.xml")
    out: list[str] = []
    seen: set[str] = set()
    for u in locs:
        if "/newsroom/releases/" not in u:
            continue
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        if SLUG_DROP_RE.search(slug) or not SLUG_KEEP_RE.search(slug):
            continue
        n = _norm(u)
        if n not in seen:
            seen.add(n)
            out.append(u.split("?")[0])
    return out


def cbp_release_urls() -> list[str]:
    index = _sitemap_locs("https://www.cbp.gov/sitemap.xml")
    pages = [u for u in index if "sitemap.xml" in u] or ["https://www.cbp.gov/sitemap.xml"]
    out: list[str] = []
    seen: set[str] = set()
    for page in pages:
        locs = _sitemap_locs(page)
        for u in locs:
            low = u.lower()
            if not any(k in low for k in ("/newsroom/", "/news/", "/press", "/media")):
                continue
            slug = u.rstrip("/").split("/")[-1]
            if SLUG_DROP_RE.search(slug) or not SLUG_KEEP_RE.search(slug):
                continue
            if "traffick" in slug.lower() and not any(
                k in slug.lower() for k in ("human", "sex", "labor", "labour", "forced", "child")
            ):
                continue
            n = _norm(u)
            if n not in seen:
                seen.add(n)
                out.append(u.split("?")[0])
        time.sleep(0.3)
    return out


def _listing_links(page_url: str, *, jina: bool) -> list[str]:
    body, status = fetch_listing(page_url, 40, verify=True)
    html = body or ""
    links = collect_from_html(
        html,
        page_url,
        same_host=True,
        extra_hosts=None,
        path_prefix=None,
        exclude_substrings=EXCLUDE_URL,
        require_any_substrings=[],
        https_only=True,
    ) if html else []
    links = [u for u in links if _articleish(u)]
    if len(links) >= 3 and status == 200:
        return links
    if jina or status in (0, 403, 401) or len(links) < 3:
        jbody, jstatus = fetch_listing("https://r.jina.ai/" + page_url, 70, verify=True)
        if jbody and jstatus in (200, 0):
            found = re.findall(r"https://[^\s)>\"]+", jbody)
            host = urlparse(page_url).netloc.lower().lstrip("www.")
            extra = []
            for raw in found:
                raw = raw.rstrip(".,);]")
                if host not in raw.lower():
                    continue
                if _articleish(raw):
                    extra.append(raw.split("#")[0])
            # preserve order, dedupe
            seen = set(links)
            for u in extra:
                if u not in seen:
                    seen.add(u)
                    links.append(u)
    return links


def _follow_next(page_url: str, html: str) -> str | None:
    # cheap rel=next without a second parser dependency beyond bs4 already imported via fetch module
    m = re.search(r'rel=["\']next["\'][^>]*href=["\']([^"\']+)', html, re.I)
    if not m:
        m = re.search(r'href=["\']([^"\']+)["\'][^>]*rel=["\']next["\']', html, re.I)
    if not m:
        return None
    return urljoin(page_url, m.group(1))


def _exploitation_listing(url: str) -> bool:
    """Keep trafficking and forced-labor listings. Skip fraud, elder, and cyber searches."""
    low = url.lower()
    if any(k in low for k in ("fraud", "elder", "ransomware", "scam", "cyber", "phishing")):
        return any(k in low for k in ("traffick", "forced", "servitude", "peonage"))
    return True


def discover_html_source(src: dict) -> list[str]:
    mode = src.get("mode") or "html"
    found: list[str] = []
    seen: set[str] = set()
    src = dict(src)
    src["queries"] = [q for q in src["queries"] if _exploitation_listing(q)]
    if mode == "squarespace":
        for q in src["queries"]:
            try:
                batch = collect_squarespace_general_search_urls(
                    q,
                    timeout=40,
                    verify=True,
                    delay=1.0,
                    path_prefix=None,
                    exclude_substrings=EXCLUDE_URL,
                    require_any_substrings=[],
                    https_only=True,
                )
            except Exception as exc:
                print(f"  [{src['id']}] squarespace fail {exc}", file=sys.stderr)
                batch = []
            for u in batch:
                if _articleish(u) and u not in seen:
                    seen.add(u)
                    found.append(u)
        return found
    if mode == "cse":
        for q in src["queries"]:
            try:
                batch = collect_google_cse_search_pages(
                    q,
                    range(1, 3),
                    timeout=50,
                    verify=True,
                    delay=1.2,
                    path_prefix=None,
                    exclude_substrings=EXCLUDE_URL,
                    require_any_substrings=[],
                    https_only=True,
                    sitemap_url=None,
                    max_results=40,
                )
            except Exception as exc:
                print(f"  [{src['id']}] cse fail {exc}", file=sys.stderr)
                batch = []
            for u in batch:
                if u not in seen:
                    seen.add(u)
                    found.append(u)
        return found
    for q in src["queries"]:
        page_url = q
        pages = 0
        while page_url and pages < 4:
            pages += 1
            body, status = fetch_listing(page_url, 40, verify=True)
            links = _listing_links(page_url, jina=bool(src.get("jina")))
            added = 0
            for u in links:
                if u not in seen:
                    seen.add(u)
                    found.append(u)
                    added += 1
            print(
                f"  [{src['id']}] {status} +{added} (total {len(found)}) {page_url[:90]}",
                file=sys.stderr,
            )
            nxt = _follow_next(page_url, body or "") if body else None
            if not nxt or nxt == page_url or added == 0:
                break
            page_url = nxt
            time.sleep(0.8)
    return found


def discover_usa(src: dict) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    queries = [q for q in src["queries"] if _exploitation_listing(q)]
    for query in queries:
        try:
            batch = collect_usa_search_urls(
                src["affiliate"],
                query,
                range(1, 4),
                host=src["host"],
                timeout=50,
                verify=True,
                delay=1.2,
                path_prefix=None,
                exclude_substrings=EXCLUDE_URL,
                require_any_substrings=[],
                sitemap_releases=None,
            )
        except Exception as exc:
            print(f"  [{src['id']}] usa fail {query}: {exc}", file=sys.stderr)
            batch = []
        for u in batch:
            if u not in seen:
                seen.add(u)
                found.append(u)
        print(f"  [{src['id']}] {query!r} -> {len(batch)} (total {len(found)})", file=sys.stderr)
    return found


def _append_jsonl(path: Path, rec: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _record_from_parts(
    *,
    source_id: str,
    source_name: str,
    url: str,
    title: str,
    body: str,
    pub_date: str | None,
    byline: str,
) -> dict | None:
    domain = label_domain(title, body)
    if not domain:
        return None
    return {
        "nhsr": NHSR,
        "observed": True,
        "inferred": False,
        "cost": "free",
        "pacer_purchases": 0,
        "kind": "press",
        "domain": domain,
        "source_id": source_id,
        "agency": source_name,
        "title": title,
        "byline": byline,
        "pub_date": pub_date,
        "source_url": url,
        "body": body,
        "mode": "resolved",
        "stage": classify_stage(title),
    }


def ingest_resolved_list(source_id: str, source_name: str, records: list[dict], seen: set[str]) -> Counter:
    stats: Counter = Counter()
    path = RECORDS / f"{source_id}.jsonl"
    for rec in records:
        url = rec.get("source_url") or ""
        n = _norm(url)
        if not n or n in seen:
            stats["dup"] += 1
            continue
        kept = _record_from_parts(
            source_id=source_id,
            source_name=rec.get("agency") or source_name,
            url=url,
            title=rec.get("title") or "",
            body=rec.get("body") or "",
            pub_date=rec.get("pub_date"),
            byline=rec.get("byline") or "",
        )
        seen.add(n)
        if not kept:
            stats["drop_gate"] += 1
            continue
        _append_jsonl(path, kept)
        stats["kept"] += 1
        stats[kept["domain"]] += 1
    return stats


def extract_urls(source_id: str, source_name: str, urls: list[str], seen: set[str], *, delay: float) -> Counter:
    import build_press_pdf

    stats: Counter = Counter()
    path = RECORDS / f"{source_id}.jsonl"
    ns = argparse.Namespace(referer=None, jina_fallback=True)
    for i, url in enumerate(urls, start=1):
        n = _norm(url)
        if n in seen:
            stats["dup"] += 1
            continue
        try:
            resolved = build_press_pdf.resolve_url_content(url, ns, True)
        except Exception as exc:
            print(f"    [{source_id} {i}] extract error {exc}", file=sys.stderr)
            stats["error"] += 1
            time.sleep(delay)
            continue
        seen.add(n)
        if not resolved:
            stats["thin"] += 1
            time.sleep(delay)
            continue
        (title, byline, body, pub_date), _fetch = resolved
        kept = _record_from_parts(
            source_id=source_id,
            source_name=source_name,
            url=url,
            title=title,
            body=body,
            pub_date=pub_date.isoformat() if pub_date else None,
            byline=byline or "",
        )
        if not kept:
            stats["drop_gate"] += 1
        else:
            _append_jsonl(path, kept)
            stats["kept"] += 1
            stats[kept["domain"]] += 1
        if i % 25 == 0:
            print(
                f"    [{source_id}] {i}/{len(urls)} kept {stats['kept']} drop {stats['drop_gate']}",
                file=sys.stderr,
            )
        time.sleep(delay)
    return stats


def _write_url_file(source_id: str, urls: list[str]) -> None:
    path = URLS / f"{source_id}.txt"
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")


def phase_doj() -> None:
    _mkdirs()
    seen = collected_urls()
    skip_path = BULK_PRESS / "_skip_urls.txt"
    skip_path.write_text("\n".join(sorted(seen)) + "\n", encoding="utf-8")
    print(f"skip file {len(seen)} urls", file=sys.stderr)
    profiles = [
        ("forced_labor", "DOJ forced labor"),
        ("trafficking", "DOJ trafficking"),
        ("fraud", "DOJ criminal fraud"),
        ("cyber", "DOJ cyber"),
    ]
    summary = {"started": _now(), "profiles": {}}
    out_dir = BULK_PRESS / "doj_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    for profile, label in profiles:
        print(f"\n===== DOJ {profile} =====", file=sys.stderr)
        cmd = [
            sys.executable,
            str(HERE / "harvest_doj_press.py"),
            "--profile",
            profile,
            "--max-keep",
            "0",
            "--skip-cac",
            "--keep-early",
            "--out-dir",
            str(out_dir),
            "--slug",
            profile,
            "--skip-url-file",
            str(skip_path),
        ]
        proc = subprocess.run(cmd, cwd=str(HERE), text=True)
        resolved = out_dir / f"{profile}_resolved.json"
        records: list[dict] = []
        if resolved.is_file():
            try:
                records = json.loads(resolved.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                records = []
        stats = ingest_resolved_list(f"doj_{profile}", label, records, seen)
        # grow skip file so the next profile does not repeat a URL
        skip_path.write_text("\n".join(sorted(seen)) + "\n", encoding="utf-8")
        summary["profiles"][profile] = {
            "exit": proc.returncode,
            "api_kept": len(records),
            "gate": dict(stats),
        }
        print(f"DOJ {profile} api={len(records)} gate={dict(stats)}", file=sys.stderr)
        _write_status("status_doj.json", summary)
    summary["finished"] = _now()
    _write_status("status_doj.json", summary)


def _save_and_extract(source_id: str, source_name: str, urls: list[str], seen: set[str], *, delay: float) -> dict:
    _write_url_file(source_id, urls)
    fresh = [u for u in urls if _norm(u) not in seen]
    print(f"[{source_id}] candidates {len(urls)} new {len(fresh)}", file=sys.stderr)
    stats = extract_urls(source_id, source_name, fresh, seen, delay=delay)
    print(f"[{source_id}] {dict(stats)}", file=sys.stderr)
    return {"candidates": len(urls), "new": len(fresh), "gate": dict(stats)}


def phase_agencies() -> None:
    _mkdirs()
    seen = collected_urls()
    summary: dict = {"started": _now(), "sources": {}}
    sitemap_jobs = [
        ("ice", "U.S. Immigration and Customs Enforcement", ice_release_urls, 0.65),
        ("usss", "U.S. Secret Service", usss_release_urls, 0.7),
        ("cbp", "U.S. Customs and Border Protection", cbp_release_urls, 0.7),
    ]
    for sid, name, fn, delay in sitemap_jobs:
        print(f"\n===== sitemap {sid} =====", file=sys.stderr)
        try:
            urls = fn()
        except (Exception, SystemExit) as exc:
            print(f"[{sid}] discover failed {exc}", file=sys.stderr)
            summary["sources"][sid] = {"error": str(exc)}
            continue
        summary["sources"][sid] = _save_and_extract(sid, name, urls, seen, delay=delay)
        summary["sources"][sid]["name"] = name
        _write_status("status_agencies.json", summary)

    for src in USA_SOURCES:
        print(f"\n===== usa {src['id']} =====", file=sys.stderr)
        try:
            urls = discover_usa(src)
        except (Exception, SystemExit) as exc:
            summary["sources"][src["id"]] = {"error": str(exc), "name": src["name"]}
            continue
        summary["sources"][src["id"]] = _save_and_extract(
            src["id"], src["name"], urls, seen, delay=1.1
        )
        summary["sources"][src["id"]]["name"] = src["name"]
        _write_status("status_agencies.json", summary)

    for src in HTML_SOURCES:
        print(f"\n===== html {src['id']} =====", file=sys.stderr)
        try:
            urls = discover_html_source(src)
        except (Exception, SystemExit) as exc:
            print(f"[{src['id']}] discover failed {exc}", file=sys.stderr)
            summary["sources"][src["id"]] = {"error": str(exc), "name": src["name"]}
            _write_status("status_agencies.json", summary)
            continue
        summary["sources"][src["id"]] = _save_and_extract(
            src["id"], src["name"], urls, seen, delay=0.9
        )
        summary["sources"][src["id"]]["name"] = src["name"]
        _write_status("status_agencies.json", summary)

    summary["finished"] = _now()
    summary["distinct_urls_seen"] = len(seen)
    _write_status("status_agencies.json", summary)


def _load_kept() -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    if not RECORDS.is_dir():
        return rows
    for path in sorted(RECORDS.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            n = _norm(rec.get("source_url") or "")
            if not n or n in seen:
                continue
            seen.add(n)
            rows.append(rec)
    return rows


def phase_pdf() -> None:
    _mkdirs()
    from runtime import python_with_pypdf

    rows = _load_kept()
    print(f"pdf input {len(rows)} distinct records", file=sys.stderr)
    py = python_with_pypdf() or sys.executable
    by_domain: dict[str, list[dict]] = {}
    for rec in rows:
        by_domain.setdefault(rec.get("domain") or "mixed", []).append(rec)
    written = []
    for domain, group in sorted(by_domain.items()):
        domain_dir = PDFS / domain
        domain_dir.mkdir(parents=True, exist_ok=True)
        for i in range(0, len(group), 400):
            chunk = group[i : i + 400]
            part = i // 400 + 1
            raw = domain_dir / f"_{domain}_{part:03d}.json"
            raw.write_text(json.dumps(chunk), encoding="utf-8")
            out_name = f"{domain}_{part:03d}.pdf"
            cmd = [
                py,
                str(HERE / "build_press_pdf.py"),
                "--doj-file",
                str(raw),
                "--out-dir",
                str(domain_dir),
                "--out-name",
                out_name,
            ]
            print("+", " ".join(cmd[-6:]), file=sys.stderr)
            proc = subprocess.run(cmd, cwd=str(HERE), text=True)
            pdf = domain_dir / out_name
            written.append(
                {
                    "domain": domain,
                    "part": part,
                    "records": len(chunk),
                    "pdf": str(pdf) if pdf.is_file() else None,
                    "bytes": pdf.stat().st_size if pdf.is_file() else 0,
                    "exit": proc.returncode,
                }
            )
            _write_status("status_pdf.json", {"finished_partial": _now(), "files": written})
    _write_status(
        "status_pdf.json",
        {"finished": _now(), "records": len(rows), "files": written},
    )


def _press_bodies() -> list[dict]:
    rows = []
    if MANIFESTS.is_dir():
        for path in MANIFESTS.rglob("*.json"):
            if "resolved" in path.name or path.name in {"COLLECTION.json", "MANIFEST.json"}:
                continue
            if path.name.startswith("court_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get("kind") == "court":
                continue
            rec = data.get("record") if isinstance(data.get("record"), dict) else data
            title = data.get("title") or rec.get("title") or ""
            body = rec.get("body") or ""
            url = data.get("source_url") or rec.get("source_url") or ""
            domain = data.get("domain") or rec.get("domain") or ""
            if title and body and domain in {"fraud", "trafficking", "cyber", "forced_labor", "csea"}:
                rows.append({"title": title, "body": body, "source_url": url, "domain": domain})
    rows.extend(_load_kept())
    return rows


def _names_from_body(body: str) -> list[str]:
    out = []
    for m in NAME_RE.finditer(body[:6000]):
        name = m.group(1).strip()
        if SKIP_NAME_RE.search(name):
            continue
        parts = name.split()
        if len(parts) < 2 or len(parts[-1]) < 3:
            continue
        out.append(name)
    # unique, preserve order
    seen = set()
    uniq = []
    for n in out:
        k = n.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(n)
    return uniq[:3]


WARRANT_CAPTION_RE = re.compile(
    r"apple id|icloud|@|email account|facebook account|cellphone|cell phone|gmail|"
    r"search warrant|subpoena",
    re.I,
)
FEDERAL_CAPTION_RE = re.compile(r"\b(?:united states|u\.s\.|usa)\s+v\.?\b", re.I)
EXPLOIT_RE = re.compile(
    r"traffick|forced labou?r|involuntary servitude|\bpeonage\b",
    re.I,
)
GENERIC_FRAUD_RE = re.compile(
    r"\b(?:mail fraud|wire fraud|bank fraud|securities fraud|tax fraud|honest services fraud)\b",
    re.I,
)
RICH_DOC_RE = re.compile(
    r"indictment|criminal complaint|\bcomplaint\b|plea agreement|factual (?:basis|proffer|statement)|"
    r"sentencing memorandum|affidavit|information\b",
    re.I,
)
THIN_DOC_RE = re.compile(
    r"minute|scheduling|notice of|waiver|appearance|summons|cover sheet|"
    r"arrest warrant|search warrant|subpoena|pro hac|motion to continue|"
    r"order granting|order denying|text order",
    re.I,
)
# Federal criminal exploitation only. No bare mail/wire/bank fraud queries.
EXPLOIT_QUERIES = (
    '"forced labor" indictment',
    '"labor trafficking" indictment',
    '"sex trafficking" indictment',
    '"human trafficking" indictment',
    '"involuntary servitude" indictment',
    "peonage indictment",
    '"forced labor" "plea agreement"',
    '"sex trafficking" "plea agreement"',
    '"labor trafficking" complaint',
    '"human trafficking" complaint',
    '"forced labor" "sentencing memorandum"',
    '"sex trafficking" affidavit',
)


def _page_count(item: dict) -> int:
    for key in ("page_count", "pageCount"):
        raw = item.get(key)
        if raw in (None, ""):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return 0


def _doc_description(item: dict) -> str:
    return str(item.get("description") or item.get("short_description") or "")


WRAPPER_RE = re.compile(
    r"^\s*(acknowledgment|motion|order|notice|minute|waiver|summons|response|reply|"
    r"letter|stipulation|judgment|memorandum in|amicus)\b",
    re.I,
)
CHARGING_RE = re.compile(
    r"^\s*(?:\(\s*[A-Za-z0-9]+\s*\)\s*)?"
    r"(?:sealed\s+|redacted\s+|first\s+|second\s+|third\s+|fourth\s+|superseding\s+)*"
    r"(indictment|criminal complaint|plea agreement|sentencing memorandum|factual basis|affidavit)\b",
    re.I,
)


def _federal_recap(item: dict) -> bool:
    blob = f"{item.get('filepath_local') or ''} {item.get('absolute_url') or ''}".lower()
    return "gov.uscourts." in blob


def _rich_filing(item: dict) -> bool:
    """Charging instrument, plea, or sentencing memo. Not a motion or a 2-page acknowledgment."""
    desc = _doc_description(item)
    if WRAPPER_RE.search(desc):
        return False
    if CHARGING_RE.search(desc):
        return True
    return False


def _exploitation_caption(caption: str, desc: str) -> bool:
    if not FEDERAL_CAPTION_RE.search(caption):
        return False
    if WARRANT_CAPTION_RE.search(caption):
        return False
    blob = f"{caption}\n{desc}"
    if GENERIC_FRAUD_RE.search(blob) and not EXPLOIT_RE.search(blob):
        return False
    return True


def _wait_for_user_quota(court_records) -> float:
    """Sleep until the documented user quota has room. Return seconds to pause between calls.

    This account is 10/minute, 100/hour, and 250/day (above the public default of
    5/minute, 50/hour, 125/day). A 429's Retry-After is the reset time. Storage
    PDF downloads are not API calls and do not spend this quota.
    """
    import requests
    from datetime import datetime, timezone

    url = "https://www.courtlistener.com/api/rest/v4/api-usage/"
    headers = court_records._headers()
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    rows = [
        row
        for row in (resp.json().get("current_usage") or [])
        if row.get("scope") == "user"
    ]
    now = datetime.now(timezone.utc)
    for row in rows:
        remaining = int(row.get("remaining") or 0)
        reset_raw = row.get("reset_at")
        if remaining == 0 and reset_raw:
            reset = datetime.fromisoformat(reset_raw)
            wait = (reset - now).total_seconds() + 3
            if wait > 0:
                print(
                    f"  quota {row.get('rate')} is empty; waiting {int(wait)}s until {reset_raw}",
                    file=sys.stderr,
                )
                time.sleep(min(wait, 3700))
                return _wait_for_user_quota(court_records)
    minute = next((row for row in rows if str(row.get("rate") or "").endswith("/min")), None)
    per_min = int(minute["limit"]) if minute else 5
    return max(6.5, (60.0 / max(per_min, 1)) + 0.4)


def _throttle_pause(resp) -> float:
    """Seconds to wait after a 429. The body says when the rolling window frees a slot."""
    detail = ""
    try:
        detail = str((resp.json() or {}).get("detail") or "")
    except ValueError:
        detail = resp.text[:180]
    match = re.search(r"Expected available in (\d+)", detail)
    if match:
        return float(match.group(1)) + 2
    retry = resp.headers.get("Retry-After")
    try:
        return float(retry) + 2 if retry else 60.0
    except ValueError:
        return 60.0


def _cl_get(court_records, url: str, params: dict | None, gap: float):
    """One CourtListener API GET. A 429 waits out the rolling window, then retries.

    These calls are the free search API. They do not purchase PACER documents.
    """
    import requests

    headers = court_records._headers()
    time.sleep(gap)
    for _attempt in range(8):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=45)
        except requests.RequestException as exc:
            print(f"  [courtlistener] request failed: {exc}", file=sys.stderr)
            time.sleep(30)
            continue
        if resp.status_code == 429:
            pause = _throttle_pause(resp)
            print(f"  [courtlistener] 429; waiting {int(pause)}s (free throttle, no charge)", file=sys.stderr)
            time.sleep(pause)
            continue
        if resp.status_code >= 400:
            print(f"  [courtlistener] HTTP {resp.status_code}", file=sys.stderr)
            return None
        return resp
    print("  [courtlistener] still limited after waits", file=sys.stderr)
    return None


def phase_recap(max_recap: int) -> None:
    """500 federal criminal-exploitation RECAP filings.

    Queries are trafficking, forced labor, servitude, peonage, and elder fraud.
    Generic mail, wire, and bank fraud are not searched. Each kept file is an
    indictment, complaint, plea, or other long narrative filing.
    """
    _mkdirs()
    import court_records
    from court_records import COURTLISTENER_SEARCH, download_free_pdf, load_token_from_env_files

    court_records.MIN_DELAY = 3.5
    load_token_from_env_files([REPO / ".env", REPO.parent / "CaseLinker" / ".env"])
    dest = BULK_RECAP
    log_path = BULK_RECAP / "manifests" / "recap_links.jsonl"
    seen_cases: set[str] = set()
    if log_path.is_file():
        kept_lines = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            caption = rec.get("case_name") or ""
            blob = f"{caption} {rec.get('press_title') or ''} {rec.get('query') or ''} {rec.get('document_description') or ''}"
            drop = WARRANT_CAPTION_RE.search(caption) or (
                GENERIC_FRAUD_RE.search(blob) and not EXPLOIT_RE.search(blob)
            )
            if not drop and not EXPLOIT_RE.search(blob) and rec.get("press_domain") not in {
                "trafficking",
                "forced_labor",
            }:
                drop = True
            if drop:
                pdf = rec.get("pdf")
                if pdf:
                    Path(pdf).unlink(missing_ok=True)
                continue
            kept_lines.append(line)
            seen_cases.add(caption.strip().lower())
        log_path.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")
    kept = len(seen_cases)
    print(f"recap exploitation cases already kept {kept}/{max_recap}", file=sys.stderr)
    gap = _wait_for_user_quota(court_records)
    print(f"CourtListener spacing {gap:.1f}s between API calls", file=sys.stderr)
    tried = 0
    for query in EXPLOIT_QUERIES:
        if kept >= max_recap:
            break
        url = COURTLISTENER_SEARCH
        params: dict | None = {"q": query, "type": "rd", "order_by": "score desc"}
        pages = 0
        while url and kept < max_recap and pages < 40:
            pages += 1
            resp = _cl_get(court_records, url, params, gap)
            params = None
            if resp is None:
                print(f"  stop query after cooldown failures: {query}", file=sys.stderr)
                break
            try:
                payload = resp.json()
            except ValueError:
                break
            results = payload.get("results") or []
            print(
                f"  [{query}] page {pages} hits {len(results)} kept {kept}/{max_recap}",
                file=sys.stderr,
            )
            if not results:
                break
            for item in results:
                if kept >= max_recap:
                    break
                if not isinstance(item, dict):
                    continue
                tried += 1
                desc = _doc_description(item)
                if not item.get("is_available") or not item.get("filepath_local"):
                    continue
                if not _federal_recap(item):
                    continue
                if not _rich_filing(item):
                    continue
                docket_id = str(item.get("docket_id") or "")
                key = f"docket:{docket_id}" if docket_id else f"doc:{item.get('id')}"
                if key in seen_cases:
                    continue
                caption = desc[:180]
                fp = item.get("filepath_local")
                download_url = f"https://storage.courtlistener.com/{str(fp).lstrip('/')}"
                doc_id = item.get("id") or item.get("document_id") or kept + 1
                pdf_path = dest / f"{doc_id}.pdf"
                if pdf_path.is_file() and pdf_path.stat().st_size > 1000:
                    seen_cases.add(key)
                    kept += 1
                    continue
                result = download_free_pdf(download_url, pdf_path)
                if not result.get("ok"):
                    continue
                # Prefer substance. Drop tiny PDFs that slipped the description gate.
                if int(result.get("bytes") or 0) < 8000 and not RICH_DOC_RE.search(desc):
                    pdf_path.unlink(missing_ok=True)
                    continue
                seen_cases.add(key)
                kept += 1
                abs_url = item.get("absolute_url") or ""
                if abs_url and not str(abs_url).startswith("http"):
                    abs_url = f"https://www.courtlistener.com{abs_url}"
                link = {
                    "nhsr": NHSR,
                    "observed": True,
                    "inferred": False,
                    "cost": "free",
                    "pacer_purchases": 0,
                    "query": query,
                    "case_name": caption,
                    "court": item.get("court") or item.get("court_id"),
                    "docket_number": item.get("docketNumber") or item.get("docket_number"),
                    "document_description": desc,
                    "page_count": _page_count(item),
                    "absolute_url": abs_url,
                    "pdf": result.get("path"),
                    "bytes": result.get("bytes"),
                    "exploitation": True,
                }
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(link, ensure_ascii=False) + "\n")
                print(
                    f"  recap {kept}/{max_recap} p.{_page_count(item) or '?'} {desc[:40]} | {caption[:70]}",
                    file=sys.stderr,
                )
            url = payload.get("next") or ""
            if tried and tried % 40 == 0:
                _write_status(
                    "status_recap.json",
                    {"updated": _now(), "kept": kept, "tried": tried, "target": max_recap, "query": query},
                )
    _write_status(
        "status_recap.json",
        {"finished": _now(), "kept": kept, "target": max_recap, "tried": tried},
    )
    print(f"recap kept {kept} target {max_recap}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="CaseNoesis multi-source bulk harvest (NHSR #8252).")
    ap.add_argument("--phase", required=True, choices=["doj", "agencies", "pdf", "recap"])
    ap.add_argument("--max-recap", type=int, default=500)
    args = ap.parse_args()
    if args.phase == "doj":
        phase_doj()
    elif args.phase == "agencies":
        phase_agencies()
    elif args.phase == "pdf":
        phase_pdf()
    elif args.phase == "recap":
        phase_recap(args.max_recap)


if __name__ == "__main__":
    main()
