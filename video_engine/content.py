"""Content loading + daily rotation.

Episode index = days since 1970-01-01 modulo library size, so the queue
never repeats within a month and needs no state file (no extra commits,
no extra Actions minutes).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config as C


def load_library(topic: str) -> dict:
    path = C.CONTENT_DIR / C.TOPICS[topic]["content_file"]
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def episode_for_today(topic: str, day: str | None = None) -> dict:
    """day: 'YYYY-MM-DD' (defaults to today UTC). Honours CONTENT_INDEX env
    for testing / manual re-runs."""
    lib = load_library(topic)
    episodes = lib["episodes"]

    if os.environ.get("CONTENT_INDEX", "").strip().isdigit():
        idx = int(os.environ["CONTENT_INDEX"]) % len(episodes)
    else:
        d = datetime.strptime(day or _today(), "%Y-%m-%d")
        idx = d.toordinal() % len(episodes)

    ep = episodes[idx]
    ep.setdefault("n", idx + 1)
    ep.setdefault("total", len(episodes))
    ep.setdefault("voice", lib.get("voice", C.DEFAULT_VOICE))
    ep.setdefault("handle", lib.get("handle", "@yourhandle"))
    return ep


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def caption_for(topic: str, ep: dict) -> str:
    """Caption + hashtags used for BOTH Instagram and Pinterest."""
    lines = [ep["hook"]["text"], ""]
    for i, tip in enumerate(ep["tips"], 1):
        lines.append(f"{i}. {tip['title']} — {tip['body']}")
    lines += ["", ep["cta"]["text"]]
    tags = " ".join("#" + t.lstrip("#") for t in ep.get("hashtags", []))
    lines += ["", tags]
    return "\n".join(lines)
