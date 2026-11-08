"""GitHub Release hosting — uploads videos/covers as release assets.

Instagram's Graph API only accepts a public HTTPS video URL, so every video
is first attached to a dated release on the (public) repo. Public release
asset URLs are direct, cache-friendly, and free.
"""

from __future__ import annotations

import os
import requests

API = "https://api.github.com"


def _auth() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set (Actions provides it).")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY is not set (Actions provides it).")
    return repo


def ensure_release(tag: str, title: str) -> dict:
    """Create (or fetch) the release for `tag`; returns release JSON."""
    headers = _auth()
    # fetch existing first (safe on re-runs of the same day)
    r = requests.get(f"{API}/repos/{_repo()}/releases/tags/{tag}",
                     headers=headers, timeout=30)
    if r.ok:
        return r.json()
    r = requests.post(
        f"{API}/repos/{_repo()}/releases",
        headers=headers,
        json={"tag_name": tag, "name": title, "prerelease": False},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def upload_asset(release: dict, path, asset_name: str) -> str:
    """Upload (replacing same-named) asset; returns its public URL."""
    headers = _auth()
    # delete a same-named asset from a previous partial run
    for asset in release.get("assets", []):
        if asset["name"] == asset_name:
            requests.delete(
                f"{API}/repos/{_repo()}/releases/assets/{asset['id']}",
                headers=headers, timeout=30,
            )

    upload_url = release["upload_url"].replace(
        "{?name,label}", f"?name={asset_name}"
    )
    with open(path, "rb") as fh:
        up = requests.post(
            upload_url,
            headers={**headers, "Content-Type": "video/mp4"},
            data=fh,
            timeout=600,
        )
    if not up.ok:  # cover jpg uses a different content type
        with open(path, "rb") as fh:
            up = requests.post(
                upload_url,
                headers={**headers, "Content-Type": "image/jpeg"},
                data=fh,
                timeout=600,
            )
    up.raise_for_status()
    return up.json()["browser_download_url"]


def publish_to_release(date: str, topic: str, video_path, cover_path) -> dict:
    """Host one episode; returns {tag, video_url, cover_url, release_url}."""
    tag = f"daily/{date}"
    release = ensure_release(tag, f"Daily videos — {date}")
    video_url = upload_asset(release, video_path, f"{topic}.mp4")
    cover_url = upload_asset(release, cover_path, f"{topic}-cover.jpg")
    return {
        "tag": tag,
        "release_url": release["html_url"],
        "video_url": video_url,
        "cover_url": cover_url,
    }
