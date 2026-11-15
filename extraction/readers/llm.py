"""Optional local LLM, used narrowly.

Off unless `CASENOESIS_LLM=1`. It reads only the mentions the deterministic
readers left open, one sentence window each, never the document. It must
answer with a role from the field's own list and an exact quote from the
window that contains the mention. A reply that fails either check is dropped.
Its confidence is 0.6, under the 0.7 line, so it can confirm or veto another
family and can never store a value by itself.

The model runs on this machine through Ollama. No record text leaves it.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable

from extraction import fields, spans as sp
from extraction.readers import Doc, assertion

VERSION = "llm_window_1.0"
METHOD = "llm"
CONFIDENCE = 0.6
MAX_WINDOWS = 8
FIELDS = ("money", "sentence")
DEFAULT_MODEL = "qwen3:8b"
ENDPOINT = "http://127.0.0.1:11434/api/generate"

Transport = Callable[[str], str]


def enabled() -> bool:
    return os.environ.get("CASENOESIS_LLM") == "1"


def _ollama(prompt: str) -> str:
    body = json.dumps({
        "model": os.environ.get("CASENOESIS_LLM_MODEL", DEFAULT_MODEL),
        "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0},
    }).encode("utf-8")
    request = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed loopback address
        return str(json.loads(response.read().decode("utf-8")).get("response") or "")


def _prompt(field_name: str, roles: tuple[str, ...], window: str, mention: str) -> str:
    return (
        f"Sentence from a public court or press record:\n\n{window}\n\n"
        f"The {field_name} mention is: {mention}\n"
        f"Which one of these roles does that mention have? {', '.join(roles)}, or unknown.\n"
        'Answer as JSON: {"role": "<role>", "quote": "<exact words from the sentence that show it, including the mention>"}'
    )


def ask(doc: Doc, open_mentions: list[dict[str, Any]], transport: Transport | None = None) -> list[dict[str, Any]]:
    """`open_mentions`: `{"field", "span": [start, end]}` rows the vote left open."""
    send = transport or _ollama
    out: list[dict[str, Any]] = []
    for mention in [m for m in open_mentions if m["field"] in FIELDS][:MAX_WINDOWS]:
        spec = fields.get(mention["field"])
        start, end = mention["span"]
        ws, we = sp.sentence_at(doc.text, start, end)
        window = doc.text[ws:we]
        try:
            reply = json.loads(send(_prompt(spec.name, spec.roles, window, doc.text[start:end])))
        except (OSError, ValueError):
            continue  # a transport error or a truncated reply is not an answer
        role, quote = reply.get("role"), str(reply.get("quote") or "")
        if role not in spec.roles:
            continue
        located, why = sp.locate_quote_covering(window, quote, start - ws, end - ws)
        if located is None:
            continue
        out.append(assertion(
            spec.name, None, role, METHOD, VERSION, CONFIDENCE, start, end,
            quote_span=[ws + located[0], ws + located[1]],
            model=os.environ.get("CASENOESIS_LLM_MODEL", DEFAULT_MODEL),
        ))
    return out
