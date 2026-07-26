#!/usr/bin/env python3
"""Refresh the dynamic sections of the DANISH.OS profile README.

What it does, in order:
  1. Reads profile-data.yml (version, Medium feed URL, engineering notes).
  2. Pulls the latest Medium posts and rewrites the BLOG block.
  3. Rotates one engineering note per ISO week and rewrites the NOTE block.
  4. Stamps the current date into the REFRESH block.

Everything fails soft: if the network or the feed is unavailable, or a marker
is missing, the existing README content is left untouched rather than wiped.
The workflow only commits when the file actually changed.

Dependencies: PyYAML (pinned in the workflow). Standard library otherwise.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DATA = ROOT / "profile-data.yml"

USER_AGENT = "danish-os-profile-bot/1.0 (+https://github.com/danish-kv)"
FEED_TIMEOUT = 15  # seconds
MAX_POSTS = 3


def replace_block(text: str, name: str, body: str) -> str:
    """Swap the content between <!-- NAME:START --> and <!-- NAME:END -->."""
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        print(f"marker {name} not found; leaving README unchanged", file=sys.stderr)
        return text
    return pattern.sub(f"{start}\n{body}\n{end}", text)


def fetch_posts(feed_url: str) -> list[tuple[str, str]]:
    """Return up to MAX_POSTS (title, link) pairs from an RSS feed."""
    if not feed_url:
        return []
    req = urllib.request.Request(feed_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FEED_TIMEOUT) as resp:  # noqa: S310
        raw = resp.read()
    root = ET.fromstring(raw)
    posts: list[tuple[str, str]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title and link:
            posts.append((title, link.split("?")[0]))
        if len(posts) >= MAX_POSTS:
            break
    return posts


def render_posts(posts: list[tuple[str, str]]) -> str:
    if not posts:
        return "- _Latest posts will appear here once the feed is reachable._"
    return "\n".join(f"- [{title}]({link})" for title, link in posts)


def pick_note(notes: list[str]) -> str:
    if not notes:
        return "> _No engineering note loaded._"
    week = dt.date.today().isocalendar()[1]
    return f"> {notes[week % len(notes)]}"


def main() -> int:
    if not README.exists() or not DATA.exists():
        print("README.md or profile-data.yml missing", file=sys.stderr)
        return 1

    data = yaml.safe_load(DATA.read_text(encoding="utf-8")) or {}
    original = README.read_text(encoding="utf-8")
    text = original

    # Blog — broad except on purpose so a flaky feed never breaks the profile.
    try:
        posts = fetch_posts(data.get("medium_feed", ""))
        text = replace_block(text, "BLOG", render_posts(posts))
    except Exception as exc:  # noqa: BLE001
        print(f"blog refresh skipped: {exc}", file=sys.stderr)

    text = replace_block(text, "NOTE", pick_note(data.get("notes", [])))

    today = dt.date.today().isoformat()
    version = str(data.get("version", "1.0.0"))
    text = replace_block(
        text, "REFRESH", f"`DANISH.OS v{version} · last refresh {today}`"
    )

    if text != original:
        README.write_text(text, encoding="utf-8")
        print("README updated")
    else:
        print("no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
