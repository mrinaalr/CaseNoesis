"""Run-level limits for transcript pulls. No network on import.

A pull stops when --max-records or --max-spend is reached, whichever comes first.
Paid rows need a known page count. A POST that fails still counts as spent.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from pacer_cost import estimate_transcript_pacer_cost

STORAGE_HOST = "storage.courtlistener.com"
LEDGER_FIELDS = [
    "docket_number",
    "docket_id",
    "recap_document_id",
    "pages",
    "estimate_usd",
    "actual_usd",
    "outcome",
    "running_spent_usd",
    "running_records",
]


class PullBudget:
    def __init__(self, max_spend: Optional[float], max_records: Optional[int]) -> None:
        self.max_spend = max_spend
        self.max_records = max_records
        self.spent = 0.0
        self.records = 0
        self.stop = False
        self.reason = ""

    def _hit_records(self) -> bool:
        return self.max_records is not None and self.records >= self.max_records

    def can_take_free(self) -> bool:
        if self.stop or self._hit_records():
            self.stop = True
            self.reason = self.reason or "max_records"
            return False
        return True

    def can_buy(self, estimate: Optional[float]) -> bool:
        if self.stop or self._hit_records():
            self.stop = True
            self.reason = self.reason or "max_records"
            return False
        if estimate is None or self.max_spend is None:
            self.stop = True
            self.reason = "no_cap" if self.max_spend is None else "unknown_pages"
            return False
        if self.spent + float(estimate) > float(self.max_spend) + 1e-9:
            self.stop = True
            self.reason = "max_spend"
            return False
        return True

    def commit(self, amount: float, *, record: bool) -> None:
        self.spent = round(self.spent + float(amount), 2)
        if record:
            self.records += 1
        if self._hit_records():
            self.stop = True
            self.reason = self.reason or "max_records"
        if self.max_spend is not None and self.spent >= float(self.max_spend) - 1e-9 and amount > 0:
            self.stop = True
            self.reason = self.reason or "max_spend"


def storage_url(filepath_local: str) -> str:
    text = (filepath_local or "").strip()
    if not text or "://" in text or text.startswith("//") or text.startswith("/") or "\\" in text:
        raise ValueError("relative storage path required")
    if any(part == ".." for part in text.split("/")):
        raise ValueError("path traversal refused")
    url = f"https://{STORAGE_HOST}/{text.lstrip('/')}"
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != STORAGE_HOST:
        raise ValueError("host refused")
    return url


def local_pdf_ok(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(8).startswith(b"%PDF")
    except OSError:
        return False


def read_storage_pdf(get: Callable[..., Any], filepath_local: str) -> bytes:
    """GET one storage.courtlistener.com object. Redirects are refused."""
    url = storage_url(filepath_local)
    resp = get(url, allow_redirects=False, timeout=180)
    status = getattr(resp, "status_code", None)
    if status in {301, 302, 303, 307, 308} or getattr(resp, "is_redirect", False):
        raise ValueError("redirect refused")
    if status != 200:
        raise ValueError(f"storage status {status}")
    data = getattr(resp, "content", b"") or b""
    if not data.startswith(b"%PDF"):
        raise ValueError("not a pdf")
    return data


def append_ledger(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def _cap_usd(row: Dict[str, Any]) -> Optional[float]:
    text = str(row.get("row_spend_cap_usd") or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pages(row: Dict[str, Any]) -> Optional[int]:
    text = str(row.get("page_count") or "").strip()
    if text.isdigit():
        return int(text)
    return None


def excluded_row_reason(row: Dict[str, Any]) -> str:
    """Duplicate filings and non-criminal dockets are never pulled, free or paid."""
    status = (row.get("status") or "").strip()
    kind = (row.get("case_kind") or "").strip()
    if status == "NON_CRIMINAL" or kind == "non_criminal":
        return "NON_CRIMINAL"
    if (row.get("duplicate_of") or "").strip() or status.startswith("DUPLICATE_OF"):
        return "DUPLICATE"
    return ""


def refuse_reason(row: Dict[str, Any]) -> str:
    status = (row.get("status") or "").strip()
    hearing = (row.get("hearing_type") or "").strip()
    excluded = excluded_row_reason(row)
    if excluded:
        return excluded
    if status in {"SEALED", "RESTRICTED", "UNCLEAR"}:
        return status
    if hearing == "trial":
        return "trial"
    if status == "COLLECTED":
        return "collected"
    if not row.get("recap_document_id"):
        return "no_document"
    if status == "BUYABLE_LATER" and _pages(row) is None and _cap_usd(row) is None:
        return "unknown_pages"
    if status not in {"FREE_NOW", "BUYABLE_LATER"}:
        return status or "status"
    return ""


def plan_transcript_pull(
    rows: List[Dict[str, Any]],
    *,
    approval_tag: str,
    max_spend: Optional[float],
    max_records: Optional[int],
) -> Dict[str, Any]:
    """FREE_NOW first, then cheapest known page count. Stops at the first limit."""
    tag = (approval_tag or "").strip().lower()
    matched = [row for row in rows if (row.get("approved") or "").strip().lower() == tag]
    refused: List[Dict[str, str]] = []
    free: List[Dict[str, Any]] = []
    buy: List[Dict[str, Any]] = []
    for row in matched:
        reason = refuse_reason(row)
        if reason:
            refused.append({"recap_document_id": str(row.get("recap_document_id") or ""), "reason": reason})
            continue
        if row.get("status") == "FREE_NOW":
            free.append(row)
        else:
            buy.append(row)
    def _plan_cost(row: Dict[str, Any]) -> float:
        pages = _pages(row)
        if pages is not None:
            return float(estimate_transcript_pacer_cost(pages) or 0)
        return float(_cap_usd(row) or 0)

    buy.sort(key=_plan_cost)
    budget = PullBudget(max_spend, max_records)
    planned: List[Dict[str, Any]] = []
    for row in free:
        if not budget.can_take_free():
            break
        planned.append({**row, "_mode": "free", "_cost": 0.0, "_pages": _pages(row)})
        budget.records += 1
    for row in buy:
        if budget.stop:
            break
        pages = _pages(row)
        cost = estimate_transcript_pacer_cost(pages)
        if cost is None:
            cost = _cap_usd(row)
        if not budget.can_buy(cost):
            break
        planned.append({**row, "_mode": "buy", "_cost": cost, "_pages": pages})
        budget.spent = round(budget.spent + float(cost or 0), 2)
        budget.records += 1
        if budget.max_records is not None and budget.records >= budget.max_records:
            budget.stop = True
            budget.reason = "max_records"
        if budget.max_spend is not None and budget.spent >= float(budget.max_spend) - 1e-9:
            budget.stop = True
            budget.reason = budget.reason or "max_spend"
    return {"planned": planned, "refused": refused, "budget": budget}


def run_transcript_pull(
    planned: List[Dict[str, Any]],
    *,
    client: Any,
    budget: PullBudget,
    ledger_path: Path,
    dest_for: Callable[[Dict[str, Any]], Path],
    pacer_username: str = "",
    pacer_password: str = "",
) -> List[Dict[str, Any]]:
    """Execute a plan. The budget starts at zero and is the hard ceiling."""
    done: List[Dict[str, Any]] = []
    for row in planned:
        if budget.stop:
            break
        dest = dest_for(row)
        doc_id = int(row["recap_document_id"])
        estimate = float(row.get("_cost") or 0)
        if local_pdf_ok(dest):
            _finish_local(row, budget, ledger_path, estimate)
            done.append(row)
            continue
        fresh = client.get_recap_document(doc_id)
        if fresh.get("is_available") and fresh.get("filepath_local"):
            if not budget.can_take_free():
                break
            content = read_storage_pdf(client.session_get, fresh["filepath_local"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            budget.commit(0.0, record=True)
            row["status"] = "COLLECTED"
            append_ledger(
                ledger_path,
                _ledger_row(row, pages=fresh.get("page_count"), estimate=0.0, actual=0.0, outcome="available", budget=budget),
            )
            done.append(row)
            continue
        if row.get("_mode") != "buy":
            append_ledger(
                ledger_path,
                _ledger_row(row, pages=row.get("_pages"), estimate=0.0, actual=0.0, outcome="failed", budget=budget),
            )
            continue
        if not budget.can_buy(estimate):
            break
        try:
            client.fetch_missing_pdf(doc_id, pacer_username=pacer_username, pacer_password=pacer_password)
        except Exception:
            budget.commit(estimate, record=False)
            append_ledger(
                ledger_path,
                _ledger_row(row, pages=row.get("_pages"), estimate=estimate, actual=estimate, outcome="failed", budget=budget),
            )
            budget.stop = True
            budget.reason = "post_failed"
            break
        try:
            fresh = client.wait_for_recap_document(doc_id)
        except Exception:
            budget.commit(estimate, record=False)
            append_ledger(
                ledger_path,
                _ledger_row(row, pages=row.get("_pages"), estimate=estimate, actual=estimate, outcome="failed", budget=budget),
            )
            budget.stop = True
            budget.reason = "post_failed"
            break
        pages = fresh.get("page_count")
        actual = estimate_transcript_pacer_cost(int(pages)) if str(pages or "").isdigit() or isinstance(pages, int) else None
        if actual is None:
            actual = estimate
        budget.commit(float(actual), record=True)
        outcome = "posted"
        if fresh.get("is_available") and fresh.get("filepath_local"):
            content = read_storage_pdf(client.session_get, fresh["filepath_local"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        row["status"] = "COLLECTED"
        row["page_count"] = pages or row.get("page_count")
        append_ledger(
            ledger_path,
            _ledger_row(row, pages=pages, estimate=estimate, actual=actual, outcome=outcome, budget=budget),
        )
        if budget.max_spend is not None and budget.spent > float(budget.max_spend) + 1e-9:
            budget.stop = True
            budget.reason = "max_spend"
        done.append(row)
    return done


def _finish_local(row: Dict[str, Any], budget: PullBudget, ledger_path: Path, estimate: float) -> None:
    if row.get("_mode") == "free":
        if not budget.can_take_free():
            return
    elif budget._hit_records():
        budget.stop = True
        return
    budget.commit(0.0, record=True)
    row["status"] = "COLLECTED"
    append_ledger(
        ledger_path,
        _ledger_row(row, pages=row.get("_pages"), estimate=estimate, actual=0.0, outcome="available", budget=budget),
    )


def _ledger_row(
    row: Dict[str, Any],
    *,
    pages: Any,
    estimate: float,
    actual: float,
    outcome: str,
    budget: PullBudget,
) -> Dict[str, Any]:
    return {
        "docket_number": row.get("docket_number") or "",
        "docket_id": row.get("docket_id") or "",
        "recap_document_id": row.get("recap_document_id") or "",
        "pages": pages if pages is not None else "",
        "estimate_usd": f"{float(estimate):.2f}",
        "actual_usd": f"{float(actual):.2f}",
        "outcome": outcome,
        "running_spent_usd": f"{budget.spent:.2f}",
        "running_records": budget.records,
    }
