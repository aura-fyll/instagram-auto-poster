"""
render_video.py
---------------
Renders ONE video episode per day and uploads it (+ cover image) to a dated
GitHub Release for public URL hosting.

Video topics alternate daily:
  - Odd days: web-design
  - Even days: github-freelancing

NEVER-REPEAT SYSTEM (same as the image pipeline):
  1. Pick today's episode by day-of-year modulo library size (31/30 episodes)
  2. Check history.json: has this (topic, episode_number) been used before?
     - If NO: use the static episode from the JSON file
     - If YES (pool cycled): ask Groq to generate a FRESH episode in the
       exact same JSON structure, passing the last 30 used hooks as
       "avoid these" context. This gives INFINITE unique video content.
  3. Render the episode (static or Groq-generated) identically — the video
     engine doesn't care where the episode dict came from.

Output:
  - content/<date>-video.json manifest with video_url, cover_url, caption,
    topic, episode_number, etc. — consumed by publish_video.py

Usage:
  python scripts/render_video.py [--date YYYY-MM-DD] [--topic web-design|github-freelancing]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

# Add repo root to path so we can import video_engine + publish
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from video_engine import config as C
from video_engine.content import caption_for, load_library
from video_engine.render import render_episode
from publish import release


def pick_topic(date: dt.date, override: str | None = None) -> str:
    """Alternate topics daily. Odd day-of-year -> web-design, even -> github."""
    if override:
        return override
    day_of_year = date.timetuple().tm_yday
    return "web-design" if day_of_year % 2 == 1 else "github-freelancing"


# ---------------------------------------------------------------------------
# Never-repeat tracking (reads history.json)
# ---------------------------------------------------------------------------

def _load_history(out_dir: Path) -> dict:
    """Load history.json from the content directory."""
    history_path = out_dir / "history.json"
    if not history_path.exists():
        return {"publications": []}
    try:
        with history_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "publications" not in data:
            return {"publications": []}
        return data
    except (json.JSONDecodeError, OSError):
        return {"publications": []}


def _used_video_episodes(history: dict, topic: str) -> set[int]:
    """Return set of episode_numbers already published for this topic."""
    used = set()
    for entry in history.get("publications", []):
        if entry.get("type") == "video" and entry.get("topic") == topic:
            ep_n = entry.get("episode_number")
            if ep_n is not None:
                used.add(int(ep_n))
    return used


def _used_video_hooks(history: dict, topic: str, limit: int = 30) -> list[str]:
    """Return the most recent N hook texts for this topic (for 'avoid these' context)."""
    hooks = []
    for entry in reversed(history.get("publications", [])):
        if entry.get("type") == "video" and entry.get("topic") == topic:
            hook = entry.get("hook_text", "")
            if hook:
                hooks.append(hook)
                if len(hooks) >= limit:
                    break
    return hooks


# ---------------------------------------------------------------------------
# Groq fresh-episode generator (infinite variety)
# ---------------------------------------------------------------------------

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_TIMEOUT_SECONDS = 45

# Topic-specific prompts for Groq
TOPIC_PROMPTS = {
    "web-design": {
        "system": (
            "You write video scripts for a freelance web designer's Instagram Reels + Pinterest. "
            "Each video is a 20-30 second tip with 3 quick points. The audience is small business "
            "owners and aspiring developers. Tone: punchy, practical, no jargon. The 'saying' fields "
            "are what the voiceover will read aloud — make them natural spoken English."
        ),
        "user_topic": "a web design / CSS / UI / frontend tip",
    },
    "github-freelancing": {
        "system": (
            "You write video scripts for a freelance web designer's Instagram Reels + Pinterest. "
            "Each video is a 20-30 second tip about using GitHub Actions / automation to run a "
            "freelance web design business. The audience is freelance developers and small agency "
            "owners. Tone: punchy, practical, no jargon. The 'saying' fields are what the voiceover "
            "will read aloud — make them natural spoken English."
        ),
        "user_topic": "a GitHub Actions / automation tip for freelance web designers",
    },
}


def generate_fresh_episode_with_groq(topic: str, used_hooks: list[str],
                                       episode_n: int) -> dict | None:
    """Ask Groq to generate a FRESH video episode in the exact JSON structure.

    Returns an episode dict (same shape as the static episodes in content/*.json)
    or None on any failure.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or not api_key.strip():
        return None
    model = os.environ.get("GROQ_MODEL") or GROQ_DEFAULT_MODEL

    prompts = TOPIC_PROMPTS.get(topic, TOPIC_PROMPTS["web-design"])

    used_block = ""
    if used_hooks:
        used_block = "\n\nALREADY-USED HOOKS (do NOT repeat these or any close paraphrase):\n"
        used_block += "\n".join(f"- {h}" for h in used_hooks[:20])
        used_block += "\n"

    user_prompt = f"""Generate ONE fresh video episode about {prompts['user_topic']}.{used_block}

Return STRICT JSON with this exact structure (and no other keys):

{{
  "hook": {{
    "text": "A punchy 6-10 word headline shown on screen",
    "saying": "One sentence the voiceover reads. Natural spoken English. 10-20 words."
  }},
  "tips": [
    {{
      "title": "2-4 word tip title",
      "body": "5-10 word description shown on screen",
      "chip": "A short code snippet or command (under 60 chars). Use real syntax.",
      "saying": "Start with 'One.' Then 15-30 words explaining the tip in natural spoken English."
    }},
    {{
      "title": "...",
      "body": "...",
      "chip": "...",
      "saying": "Start with 'Two.' Then 15-30 words..."
    }},
    {{
      "title": "...",
      "body": "...",
      "chip": "...",
      "saying": "Start with 'Three.' Then 15-30 words..."
    }}
  ],
  "cta": {{
    "text": "Short call to action (5-10 words)",
    "saying": "One sentence CTA the voiceover reads. 8-15 words."
  }},
  "hashtags": ["5 relevant hashtags without the # symbol, lowercase"]
}}

Rules:
- The hook must be DIFFERENT from all already-used hooks (listed above).
- Each tip's 'saying' must start with 'One.' / 'Two.' / 'Three.' respectively.
- The 'chip' must be real code/syntax (e.g. 'font-size: clamp(1rem, 2vw, 1.25rem);' or 'on: push: branches: [main]').
- The 'saying' fields are READ ALOUD — make them natural, not robotic.
- NO emojis, NO markdown, NO explanation. Pure JSON only."""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 1500,
        "temperature": 0.9,  # high temp for max variety
    }

    print(f"[INFO] Calling Groq for FRESH {topic} video episode (avoiding {len(used_hooks)} used)...")
    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=body, timeout=GROQ_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"[WARN] Groq network error: {exc}. Using static episode.")
        return None

    if resp.status_code != 200:
        print(f"[WARN] Groq returned HTTP {resp.status_code}. Using static episode.")
        return None

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        print(f"[WARN] Groq response unparseable: {exc}. Using static episode.")
        return None

    # Strip reasoning blocks + markdown fences
    content = content.strip()
    content = re.sub(r"<reasoning>.*?</reasoning>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<reasoning>.*$", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines).strip()
    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        content = content[first_brace : last_brace + 1]

    try:
        ep = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"[WARN] Groq returned non-JSON: {exc}. Using static episode.")
        return None

    # Validate structure
    required = {"hook", "tips", "cta", "hashtags"}
    if not required.issubset(ep.keys()):
        print(f"[WARN] Groq episode missing keys. Got: {list(ep.keys())}. Using static.")
        return None
    if not isinstance(ep["tips"], list) or len(ep["tips"]) != 3:
        print(f"[WARN] Groq episode needs exactly 3 tips, got {len(ep.get('tips', []))}. Using static.")
        return None
    for i, tip in enumerate(ep["tips"]):
        if not all(k in tip for k in ("title", "body", "chip", "saying")):
            print(f"[WARN] Groq tip {i+1} missing keys. Using static.")
            return None

    # Add metadata fields the video engine expects
    ep["n"] = episode_n
    lib = load_library(topic)
    ep["total"] = len(lib["episodes"]) + 1  # +1 to indicate this is beyond the static pool
    ep["voice"] = lib.get("voice", C.DEFAULT_VOICE)
    ep["handle"] = lib.get("handle", "@visualhookdesign")

    print(f"[INFO] Fresh episode generated: '{ep['hook']['text'][:60]}...'")
    return ep


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Render daily video + upload to GitHub Release.")
    parser.add_argument("--date", help="Override date as YYYY-MM-DD (defaults to today UTC).")
    parser.add_argument("--topic", choices=["web-design", "github-freelancing"],
                        help="Override topic (default: alternates daily).")
    parser.add_argument("--slot", default="video", help="Slot identifier for content ID (e.g. 1, 3, video).")
    parser.add_argument("--out-dir", default="content", help="Output directory for manifest.")
    args = parser.parse_args()

    if args.date:
        try:
            date = dt.date.fromisoformat(args.date)
        except ValueError as exc:
            print(f"[ERROR] Invalid --date: {exc}", file=sys.stderr)
            return 2
    else:
        date = dt.date.today()

    topic = pick_topic(date, args.topic)
    date_str = date.isoformat()
    slot = args.slot

    print(f"[INFO] Rendering video for {date_str} (topic: {topic}, slot: {slot})")

    # Load history to check for never-repeat
    out_dir_path = Path(args.out_dir).resolve()
    history = _load_history(out_dir_path)
    used_episodes = _used_video_episodes(history, topic)

    # Pick today's episode (day-of-year rotation)
    lib = load_library(topic)
    episodes = lib["episodes"]
    day_of_year = date.timetuple().tm_yday
    static_idx = day_of_year % len(episodes)
    static_episode_n = static_idx + 1  # episodes are 1-indexed

    # Check if this episode would repeat
    if static_episode_n in used_episodes:
        print(f"[INFO] Static episode #{static_episode_n} already used for '{topic}'. "
              f"Generating fresh episode via Groq...")
        used_hooks = _used_video_hooks(history, topic, limit=30)
        fresh_ep = generate_fresh_episode_with_groq(topic, used_hooks, episode_n=static_episode_n)
        if fresh_ep:
            ep = fresh_ep
            print(f"[INFO] Using FRESH Groq-generated episode: {ep['hook']['text'][:60]}...")
        else:
            # Groq failed — fall back to the static episode (better than no video)
            ep = episodes[static_idx]
            ep.setdefault("n", static_episode_n)
            ep.setdefault("total", len(episodes))
            ep.setdefault("voice", lib.get("voice", C.DEFAULT_VOICE))
            ep.setdefault("handle", lib.get("handle", "@visualhookdesign"))
            print(f"[INFO] Groq failed. Using static episode #{static_episode_n} (repeat).")
    else:
        # Static episode hasn't been used yet — use it
        ep = episodes[static_idx]
        ep.setdefault("n", static_episode_n)
        ep.setdefault("total", len(episodes))
        ep.setdefault("voice", lib.get("voice", C.DEFAULT_VOICE))
        ep.setdefault("handle", lib.get("handle", "@visualhookdesign"))
        print(f"[INFO] Episode #{ep['n']} of {ep['total']}: {ep['hook']['text'][:60]}...")

    # Render the video
    out_dir = C.OUTPUTS / date_str
    print(f"[INFO] Rendering video to {out_dir}...")
    meta = render_episode(ep, C.TOPICS[topic]["pill"], out_dir)
    print(f"[INFO] Video rendered: {meta['video']} ({meta['duration']}s, {meta['size_mb']}MB)")

    # Upload to GitHub Release for public URLs (Instagram needs a public video_url)
    print(f"[INFO] Uploading video + cover to GitHub Release...")
    caption = caption_for(topic, ep)
    try:
        rel = release.publish_to_release(date_str, topic, meta["video"], meta["cover"])
        video_url = rel["video_url"]
        cover_url = rel["cover_url"]
        release_url = rel["release_url"]
        print(f"[INFO] Video URL: {video_url}")
        print(f"[INFO] Cover URL: {cover_url}")
        print(f"[INFO] Release URL: {release_url}")
    except Exception as exc:
        print(f"[ERROR] Failed to upload to GitHub Release: {exc}", file=sys.stderr)
        return 1

    # Build the manifest
    content_id = f"{date_str}-{slot}-video"
    manifest = {
        "id": content_id,
        "date": date_str,
        "slot": slot,
        "type": "video",
        "topic": topic,
        "topic_pill": C.TOPICS[topic]["pill"],
        "episode_number": ep["n"],
        "episode_total": ep["total"],
        "hook_text": ep["hook"]["text"],
        "caption": caption,
        "hashtags": ep.get("hashtags", []),
        "cta_text": ep["cta"]["text"],
        "video_url": video_url,
        "cover_url": cover_url,
        "release_url": release_url,
        "duration": meta["duration"],
        "size_mb": meta["size_mb"],
        "handle": ep.get("handle", "@visualhookdesign"),
        "fresh_episode": ep["n"] == static_episode_n and static_episode_n in used_episodes,
    }

    # Add portfolio link for Pinterest
    manifest["portfolio_link"] = "https://professional-x.github.io/visualhk-designs/"

    # Write manifest
    out_dir_path.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir_path / f"{content_id}.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(f"[INFO] Manifest written: {manifest_path}")
    print(f"[INFO] Caption preview:\n{caption[:200]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
