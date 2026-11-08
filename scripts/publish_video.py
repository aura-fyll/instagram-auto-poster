"""
publish_video.py
----------------
Publishes a video manifest to Instagram (as a Reel) + Pinterest (cover image
pin with link to the full video on GitHub Release).

Instagram:
  - Composio INSTAGRAM_CREATE_MEDIA_CONTAINER with media_type=REELS,
    video_url, cover_url, caption
  - Poll INSTAGRAM_GET_POST_STATUS until FINISHED (video processing takes longer)
  - Composio INSTAGRAM_CREATE_POST

Pinterest:
  - Composio does NOT expose a Pinterest media upload action, so we can't
    upload the video file directly. Instead:
    - Post the video COVER IMAGE as a Pinterest pin (via PINTEREST_CREATE_PIN)
    - Set the pin link to the GitHub Release video URL (so Pinterest users
      can click through to watch the full video)
    - Pin title + description include the tips + email CTA + portfolio link

Idempotency: history.json records video_media_id (IG) + video_pin_id (Pinterest).
Re-running for the same content ID is a no-op.

Usage:
  python scripts/publish_video.py --manifest content/<date>-video.json
                                    --history content/history.json
                                    [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_instagram import (  # noqa: E402
    ComposioError,
    ComposioConfigError,
    call_composio,
    load_config,
    verify_connected_account,
    load_history,
    record_publication,
)
from publish_pinterest import (  # noqa: E402
    PORTFOLIO_LINK,
    find_or_create_board,
    create_pin,
    load_pinterest_config,
)


# Instagram Reels need longer processing time than images
VIDEO_READINESS_POLL_INTERVAL_SECONDS = 5
VIDEO_READINESS_MAX_WAIT_SECONDS = 300  # 5 minutes — videos take longer to process

ACTION_CREATE_CONTAINER = "INSTAGRAM_CREATE_MEDIA_CONTAINER"
ACTION_CREATE_POST = "INSTAGRAM_CREATE_POST"
ACTION_GET_POST_STATUS = "INSTAGRAM_GET_POST_STATUS"

READY_STATUS = "FINISHED"
ERROR_STATUSES = {"ERROR", "EXPIRED"}


def wait_until_video_ready(creation_id: str, config: dict[str, str]) -> None:
    """Poll INSTAGRAM_GET_POST_STATUS until video is FINISHED.
    Videos take longer than images (Instagram downloads + transcodes the video).
    """
    deadline = time.monotonic() + VIDEO_READINESS_MAX_WAIT_SECONDS
    attempt = 0
    last_status = None
    while time.monotonic() < deadline:
        attempt += 1
        data = call_composio(
            ACTION_GET_POST_STATUS,
            arguments={"creation_id": str(creation_id)},
            config=config,
        )
        status = (
            data.get("status_code")
            or data.get("status")
            or (data.get("data") or {}).get("status_code")
            or "UNKNOWN"
        )
        last_status = status
        print(f"[INFO] Video container {creation_id} status (attempt {attempt}): {status}")
        if status == READY_STATUS:
            print(f"[INFO] Video ready after ~{attempt * VIDEO_READINESS_POLL_INTERVAL_SECONDS}s")
            return
        if status in ERROR_STATUSES:
            raise ComposioError(
                f"Instagram video container {creation_id} entered {status} state.",
                action=ACTION_GET_POST_STATUS,
            )
        time.sleep(VIDEO_READINESS_POLL_INTERVAL_SECONDS)
    raise ComposioError(
        f"Timed out after {VIDEO_READINESS_MAX_WAIT_SECONDS}s waiting for video "
        f"{creation_id} to become FINISHED (last status: {last_status})",
        action=ACTION_GET_POST_STATUS,
    )


def publish_instagram_reel(manifest: dict[str, Any], config: dict[str, str]) -> str:
    """Publish video as Instagram Reel via Composio. Returns the media ID."""
    video_url = manifest.get("video_url")
    cover_url = manifest.get("cover_url")
    caption = manifest.get("caption", "")
    ig_user_id = config["INSTAGRAM_USER_ID"]

    if not video_url:
        raise ComposioError("Manifest is missing video_url.")

    print(f"[INFO] Creating Instagram Reel container...")
    print(f"[INFO] Video URL: {video_url}")
    print(f"[INFO] Cover URL: {cover_url}")
    print(f"[INFO] Caption length: {len(caption)} chars")

    # Step 1: create REELS container
    arguments = {
        "ig_user_id": ig_user_id,
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:2200],  # IG max 2200 chars
    }
    if cover_url:
        arguments["cover_url"] = cover_url

    container_data = call_composio(ACTION_CREATE_CONTAINER, arguments, config)
    creation_id = container_data.get("id") or container_data.get("container_id")
    if not creation_id:
        raise ComposioError(
            f"INSTAGRAM_CREATE_MEDIA_CONTAINER (REELS) did not return an id. "
            f"Response keys: {list(container_data.keys())}"
        )
    print(f"[INFO] Reel container created: {creation_id}")

    # Step 2: wait for video processing (longer than images)
    print("[INFO] Waiting for Instagram to process the video (may take 1-3 min)...")
    wait_until_video_ready(str(creation_id), config)

    # Step 3: publish
    publish_data = call_composio(
        ACTION_CREATE_POST,
        arguments={
            "ig_user_id": ig_user_id,
            "creation_id": str(creation_id),
        },
        config=config,
    )
    media_id = publish_data.get("id") or publish_data.get("media_id")
    if not media_id:
        raise ComposioError(
            f"INSTAGRAM_CREATE_POST did not return an id. "
            f"Response keys: {list(publish_data.keys())}"
        )
    print(f"[INFO] Reel published! Media ID: {media_id}")
    return str(media_id)


def publish_pinterest_video_pin(manifest: dict[str, Any], config: dict[str, str]) -> str:
    """Publish video cover image as a Pinterest pin with link to the full video.

    Composio doesn't expose a Pinterest video upload action, so we post the
    cover image instead. The pin link points to the GitHub Release video URL
    so Pinterest users can click through to watch the full video.
    """
    cover_url = manifest.get("cover_url")
    video_url = manifest.get("video_url")
    hook_text = manifest.get("hook_text", "Web Design Tip")
    caption = manifest.get("caption", "")
    topic = manifest.get("topic", "web-design")

    if not cover_url:
        raise ComposioError("Manifest is missing cover_url for Pinterest pin.")

    # Build Pinterest-optimized title + description
    if topic == "github-freelancing":
        pin_title = f"GitHub Automation for Freelancers: {hook_text[:60]}"[:100]
    else:
        pin_title = f"Web Design Tip: {hook_text[:70]}"[:100]

    # Description: hook + tips summary + CTA with email + link to watch full video
    pin_description = (
        f"{caption[:400]}\n\n"
        f"Watch the full video: {video_url}\n\n"
        f"Need a website for your business? Email visualhookdesign@gmail.com "
        f"or visit {PORTFOLIO_LINK}"
    )[:800]

    print(f"[INFO] Pinterest pin title: {pin_title}")
    print(f"[INFO] Pinterest pin link: {video_url}")

    # Find or create the board
    board_id = find_or_create_board(
        config,
        "Web Design Tips for Small Business",
        "Practical web design + GitHub automation tips for small business owners. "
        "Freelance web designer — email visualhookdesign@gmail.com"
    )

    # Create the pin with cover image + link to full video
    pin_id = create_pin(
        board_id=board_id,
        image_url=cover_url,
        title=pin_title,
        description=pin_description,
        alt_text=pin_title,
        link=video_url,  # link to the full video on GitHub Release
        config=config,
    )
    print(f"[INFO] Pinterest pin published! Pin ID: {pin_id}")
    return str(pin_id)


def is_already_published(history_path: Path, content_id: str) -> bool:
    """Check if this video was already published to both platforms."""
    history = load_history(history_path)
    for entry in history.get("publications", []):
        if entry.get("id") == content_id and entry.get("status") == "published":
            if entry.get("media_id") and entry.get("pinterest_pin_id"):
                return True
    return False


def update_history_with_video(history_path: Path, manifest: dict[str, Any],
                                ig_media_id: str | None, pin_id: str | None) -> None:
    """Record video publication in history.json."""
    history = load_history(history_path)
    entry = {
        "id": manifest["id"],
        "date": manifest["date"],
        "slot": "video",
        "type": "video",
        "topic": manifest.get("topic", ""),
        "topic_pill": manifest.get("topic_pill", ""),
        "episode_number": manifest.get("episode_number"),
        "hook_text": manifest.get("hook_text", ""),
        "image_headline": manifest.get("hook_text", ""),  # for compatibility
        "seed_fact": "",  # videos don't use seed facts
        "image_style": "video_reel",
        "status": "published",
        "media_id": ig_media_id,
        "pinterest_pin_id": pin_id,
        "video_url": manifest.get("video_url"),
        "cover_url": manifest.get("cover_url"),
        "release_url": manifest.get("release_url"),
        "duration": manifest.get("duration"),
        "size_mb": manifest.get("size_mb"),
        "detail": f"Video Reel (IG) + cover pin (Pinterest). Topic: {manifest.get('topic','?')}",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    history.setdefault("publications", []).append(entry)
    with history_path.open("w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2, ensure_ascii=False)
    print(f"[INFO] History updated: video published (IG={ig_media_id}, Pinterest={pin_id})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish video manifest to Instagram Reels + Pinterest.")
    parser.add_argument("--manifest", required=True, help="Path to the video manifest JSON.")
    parser.add_argument("--history", default="content/history.json", help="Path to history.json.")
    parser.add_argument("--dry-run", action="store_true", help="Skip actual publish calls.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        print(f"[ERROR] Manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    print(f"[INFO] Loaded video manifest: {manifest_path}")
    print(f"[INFO] Content ID: {manifest.get('id')}")
    print(f"[INFO] Topic: {manifest.get('topic')}")
    print(f"[INFO] Episode: #{manifest.get('episode_number')}")

    history_path = Path(args.history).resolve()

    # Idempotency check
    if is_already_published(history_path, manifest["id"]):
        print(f"[INFO] Video {manifest['id']} was already published. Skipping (idempotency).")
        return 0

    if args.dry_run:
        print("[INFO] Dry-run mode: skipping publish calls.")
        print(f"[INFO] Video URL: {manifest.get('video_url')}")
        print(f"[INFO] Cover URL: {manifest.get('cover_url')}")
        return 0

    # Load IG config
    try:
        ig_config = load_config()
    except ComposioConfigError as exc:
        print(f"[ERROR] IG config: {exc}", file=sys.stderr)
        return 1
    verify_connected_account(ig_config)

    # Load Pinterest config
    try:
        pin_config = load_pinterest_config()
    except ComposioConfigError as exc:
        print(f"[ERROR] Pinterest config: {exc}", file=sys.stderr)
        return 1

    # Publish to Instagram Reels
    ig_media_id = None
    try:
        ig_media_id = publish_instagram_reel(manifest, ig_config)
    except ComposioError as exc:
        print(f"[ERROR] Instagram Reel publish failed: {exc}", file=sys.stderr)

    # Publish to Pinterest (cover image pin with video link)
    pin_id = None
    try:
        pin_id = publish_pinterest_video_pin(manifest, pin_config)
    except ComposioError as exc:
        print(f"[ERROR] Pinterest pin publish failed: {exc}", file=sys.stderr)

    # Record in history
    if ig_media_id or pin_id:
        update_history_with_video(history_path, manifest, ig_media_id, pin_id)
        print("[INFO] Done.")
        return 0
    else:
        print("[ERROR] Both IG and Pinterest publish failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
