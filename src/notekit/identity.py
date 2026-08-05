"""One canonical way to turn a person into a storage key.

Identity used to be whatever string the caller typed, matched exactly. "Ria
Butt", "ria butt" and "Ria  Butt" were three different people with three empty
histories, and uploads sanitised the name while courses stored it raw — so the
same person had two identities depending on which feature they used.

Everything that keys on a user goes through `normalize` now.
"""

from __future__ import annotations

import re

ANONYMOUS = "anonymous"

_SEPARATORS = re.compile(r"[\s._]+")
_DISALLOWED = re.compile(r"[^a-z0-9-]")
_RUNS = re.compile(r"-{2,}")


def normalize(user_id: str | None) -> str:
    """Fold a display name into a stable key.

    Case, spacing and punctuation stop mattering: "Ria Butt", "ria  butt" and
    "Ria.Butt" all resolve to "ria-butt". Empty input becomes `anonymous` rather
    than an empty string, so history always has somewhere to live.
    """
    if not user_id:
        return ANONYMOUS

    key = _SEPARATORS.sub("-", user_id.strip().lower())
    key = _DISALLOWED.sub("", key)
    key = _RUNS.sub("-", key).strip("-")
    return key or ANONYMOUS
