"""Download paper PDF and extract plain text into scripts/verify/paper/."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

PAPER_URL = (
    "https://mrinaalr.github.io/website/"
    "Affordance%2C%20Misuse%2C%20Harm%2C%20Kill%20Chain.pdf"
)
PDF_NAME = "Affordance_Misuse_Harm_Kill_Chain.pdf"
TEXT_NAME = "paper.txt"


def verify_dir() -> Path:
    d = Path(__file__).resolve().parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_pdf(dest: Path) -> Path:
    if dest.is_file() and dest.stat().st_size > 10_000:
        return dest
    req = urllib.request.Request(PAPER_URL, headers={"User-Agent": "CaseLinker-verify_paper/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())
    return dest


def extract_text(pdf_path: Path, text_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber required: pip install pdfplumber") from exc

    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    raw = "\n\n".join(pages)
    # Normalize whitespace for substring checks
    text = re.sub(r"[ \t]+", " ", raw)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text_path.write_text(text, encoding="utf-8")
    return text


def load_or_build_paper_text(*, refresh: bool = False) -> tuple[str, Path]:
    out_dir = verify_dir()
    pdf_path = out_dir / PDF_NAME
    text_path = out_dir / TEXT_NAME
    if refresh or not text_path.is_file():
        fetch_pdf(pdf_path)
        extract_text(pdf_path, text_path)
    return text_path.read_text(encoding="utf-8"), text_path
