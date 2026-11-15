"""Domain profiles: the vocabularies a record is read against.

The core engine knows fields and votes. It knows nothing about fraud or
trafficking. A profile supplies the labels and the cue for each label, for the
three tag fields that differ by offense domain:

    scheme     how the offense was carried out
    channel    the technology or medium used to reach people
    platform   a named service or product

`common` applies to every record. A record also gets the profile for its
collector domain. A record whose domain has no profile of its own (the mixed
`bulk` and `transcripts` court folders) is read against all of them.

To add a domain, add a module with a `PROFILE` and list it in `_MODULES`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import import_module

PROFILE_VERSION = "profiles_2026_11b"


@dataclass(frozen=True)
class Profile:
    name: str
    domains: tuple[str, ...]
    scheme: dict[str, str] = field(default_factory=dict)
    channel: dict[str, str] = field(default_factory=dict)
    platform: dict[str, str] = field(default_factory=dict)
    # Collector bucket -> scheme label, where the bucket names a scheme.
    buckets: dict[str, str] = field(default_factory=dict)


_MODULES = ("common", "fraud", "trafficking", "forced_labor", "cyber", "csea")

# A cue inside one of these sentences describes where to report or learn more,
# not what happened in the case.
BOILERPLATE = re.compile(
    r"\b(?:hotline|tip\s*line|submit\s+a\s+tip|report\s+(?:it|fraud|suspected|suspicious|the|any|a\s+tip)|"
    r"to\s+report|for\s+more\s+information|learn\s+more|if\s+you\s+(?:or\s+someone|believe|think|have\s+information)|"
    r"anyone\s+with\s+information|is\s+available\s+(?:at|on)|can\s+be\s+found\s+(?:at|on)|visit\s+(?:www|the|https?)|"
    r"follow\s+us|ic3\.gov|ftc\.gov|reportfraud|tips\.fbi\.gov|press\s+release|public\s+is\s+reminded|"
    r"presumed\s+innocent|toll[-\s]free|1-8\d\d-|\(8\d\d\)|contact\s+the\s+(?:FBI|office|national)|"
    r"was\s+created\s+(?:to|by)|initiative\s+(?:to|that)|launched\s+(?:in|the)|protect\s+yourself|"
    r"tips\s+(?:to|for)\s+(?:avoid|protect)|be\s+(?:wary|cautious|suspicious)\s+of|never\s+(?:give|send|share))\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _all() -> dict[str, Profile]:
    return {name: import_module(f"extraction.profiles.{name}").PROFILE for name in _MODULES}


def profiles_for(domain: str | None) -> list[Profile]:
    """`common`, then the profile for this domain, or every profile when the
    domain has none."""
    profiles = _all()
    matched = [p for p in profiles.values() if domain in p.domains]
    if not matched:
        matched = [p for name, p in profiles.items() if name != "common"]
    return [profiles["common"], *matched]


@lru_cache(maxsize=32)
def vocabulary(domain: str | None, field_name: str) -> dict[str, re.Pattern[str]]:
    """`{label: compiled cue}` for one tag field under a domain. A label two
    profiles both define keeps both cues."""
    merged: dict[str, list[str]] = {}
    for profile in profiles_for(domain):
        for label, cue in getattr(profile, field_name).items():
            merged.setdefault(label, []).append(cue)
    return {
        label: re.compile(r"\b(?:" + "|".join(cues) + r")\b", re.IGNORECASE)
        for label, cues in merged.items()
    }


def bucket_label(domain: str | None, bucket: str | None) -> str | None:
    if not bucket:
        return None
    for profile in profiles_for(domain):
        if bucket in profile.buckets:
            return profile.buckets[bucket]
    return None


def labels(field_name: str) -> tuple[str, ...]:
    """Every label any profile defines for a tag field."""
    return tuple(sorted({label for profile in _all().values() for label in getattr(profile, field_name)}))
