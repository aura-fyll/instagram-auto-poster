"""
render_video.py
---------------
Renders ONE video episode per day and uploads it (+ cover image) to a dated
GitHub Release for public URL hosting.

Video topics alternate daily:
  - Odd days: web-design
  - Even days: github-freelancing

Episode rotation: day-of-year modulo library size (31 web-design / 30 GitHub
episodes), so the queue never repeats within a month.

Output:
  - content/<date>-video.json manifest with video_url, cover_url, caption,
    topic, episode_number, etc. — consumed by publish_video.py

Usage:
  python scripts/render_video.py [--date YYYY-MM-DD] [--topic web-design|github-freelancing]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

# Add repo root to path so we can import video_engine + publish
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from video_engine import config as C
from video_engine.content import caption_for, episode_for_today
from video_engine.render import render_episode
from publish import release


def pick_topic(date: dt.date, override: str | None = None) -> str:
    """Alternate topics daily. Odd day-of-year -> web-design, even -> github."""
    if override:
        return override
    day_of_year = date.timetuple().tm_yday
    return "web-design" if day_of_year % 2 == 1 else "github-freelancing"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render daily video + upload to GitHub Release.")
    parser.add_argument("--date", help="Override date as YYYY-MM-DD (defaults to today UTC).")
    parser.add_argument("--topic", choices=["web-design", "github-freelancing"],
                        help="Override topic (default: alternates daily).")
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

    print(f"[INFO] Rendering video for {date_str} (topic: {topic})")

    # Pick today's episode
    ep = episode_for_today(topic, day=date_str)
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
    manifest = {
        "id": f"{date_str}-video",
        "date": date_str,
        "slot": "video",
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
    }

    # Add portfolio link for Pinterest
    manifest["portfolio_link"] = "https://professional-x.github.io/visualhk-designs/"

    # Write manifest
    out_dir_path = Path(args.out_dir).resolve()
    out_dir_path.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir_path / f"{date_str}-video.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(f"[INFO] Manifest written: {manifest_path}")
    print(f"[INFO] Caption preview:\n{caption[:200]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
