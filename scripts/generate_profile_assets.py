#!/usr/bin/env python3
"""Regenerate the dynamic parts of the DANISH.OS profile from profile-data.yml.

What it does, in order:
  1. README.md   — rewrites the CURRENT-BUILD / CURRENT-LEARN / CURRENT-FOCUS
                   inline markers, the BLOG block (latest Medium posts), the
                   NOTE block (one engineering note, rotated by ISO week) and
                   the REFRESH block (version + date stamp).
  2. SVG assets  — rewrites marked <tspan id="..."> text:
                   assets/live-console.svg       dyn-focus, dyn-status
                   assets/repository-galaxy.svg  proj-1..4, projsub-1..4

Safety properties:
  * All injected text is XML-escaped, so YAML content can never break an SVG.
  * Values that would overflow their layout raise a clear error instead of
    silently rendering broken art.
  * The Medium fetch fails soft: on any network/feed error the previous BLOG
    content is preserved untouched.
  * Files are only written when their content actually changed, so the
    workflow never produces noisy no-op commits.

Dependencies: PyYAML (pinned in the workflow). Standard library otherwise.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DATA = ROOT / "profile-data.yml"
CONSOLE_SVG = ROOT / "assets" / "live-console.svg"
GALAXY_SVG = ROOT / "assets" / "repository-galaxy.svg"

USER_AGENT = "danish-os-profile-bot/1.1 (+https://github.com/danish-kv)"
FEED_TIMEOUT = 15  # seconds
MAX_POSTS = 3

# Layout budgets (characters) for injected SVG text. Overflowing these would
# push text outside its panel, so we fail loudly instead.
LIMITS = {
    "dyn-focus": 84,
    "dyn-status": 60,
    "proj": 16,
    "projsub": 24,
    "current-inline": 110,
}


class GenerationError(RuntimeError):
    """A clear, user-facing generation failure."""


def check_len(value: str, limit: int, what: str) -> str:
    if len(value) > limit:
        raise GenerationError(
            f"{what} is {len(value)} chars; the layout fits {limit}. "
            f"Shorten it in profile-data.yml: {value!r}"
        )
    return value


# ---------------------------------------------------------------- README ---

def replace_block(text: str, name: str, body: str) -> str:
    """Swap content between <!-- NAME:START --> and <!-- NAME:END -->."""
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise GenerationError(f"README marker {name}:START/{name}:END not found")
    return pattern.sub(f"{start}\n{body}\n{end}", text)


def replace_inline(text: str, name: str, value: str) -> str:
    """Swap content between <!-- NAME --> and <!-- /NAME --> on one line."""
    start, end = f"<!-- {name} -->", f"<!-- /{name} -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end))
    if not pattern.search(text):
        raise GenerationError(f"README inline marker {name} not found")
    return pattern.sub(f"{start}{value}{end}", text)


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
        if title and link and link.startswith("https://"):
            # sanitize: strip tracking params and markdown-hostile brackets
            title = title.replace("[", "(").replace("]", ")")
            posts.append((title, link.split("?")[0]))
        if len(posts) >= MAX_POSTS:
            break
    return posts


def pick_note(notes: list[str]) -> str:
    if not notes:
        return "> _No engineering note loaded._"
    week = dt.date.today().isocalendar()[1]
    return f"> {notes[week % len(notes)]}"


def update_readme(data: dict) -> bool:
    original = README.read_text(encoding="utf-8")
    text = original

    for marker, key in (
        ("CURRENT-BUILD", "current_project"),
        ("CURRENT-LEARN", "current_learning"),
        ("CURRENT-FOCUS", "current_focus"),
    ):
        value = str(data.get(key, "")).strip()
        if value:
            check_len(value, LIMITS["current-inline"], f"{key}")
            text = replace_inline(text, marker, value)

    # Blog — fail soft on purpose: a flaky feed must never break the profile.
    try:
        posts = fetch_posts(str(data.get("medium_feed", "")))
        if posts:
            body = "\n".join(f"- [{t}]({l})" for t, l in posts)
            text = replace_block(text, "BLOG", body)
        else:
            print("blog: feed empty, keeping previous content", file=sys.stderr)
    except GenerationError:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"blog: refresh skipped, keeping previous content ({exc})", file=sys.stderr)

    text = replace_block(text, "NOTE", pick_note(list(data.get("notes", []))))

    today = dt.date.today().isoformat()
    version = str(data.get("version", "1.0.0"))
    text = replace_block(text, "REFRESH", f"`DANISH.OS v{version} · last refresh {today}`")

    if text != original:
        README.write_text(text, encoding="utf-8")
        return True
    return False


# ------------------------------------------------------------------ SVGs ---

def inject_tspan(svg: str, tspan_id: str, value: str) -> str:
    """Replace the text content of <tspan id="..."> with an escaped value."""
    pattern = re.compile(
        r'(<tspan[^>]*\bid="' + re.escape(tspan_id) + r'"[^>]*>).*?(</tspan>)',
        re.DOTALL,
    )
    if not pattern.search(svg):
        raise GenerationError(f'tspan id="{tspan_id}" not found in SVG')
    return pattern.sub(lambda m: m.group(1) + escape(value) + m.group(2), svg)


def update_console(data: dict) -> bool:
    svg = CONSOLE_SVG.read_text(encoding="utf-8")
    out = svg
    focus = str(data.get("current_focus", "")).strip()
    status = str(data.get("status_text", "")).strip()
    if focus:
        out = inject_tspan(out, "dyn-focus", check_len(focus, LIMITS["dyn-focus"], "current_focus"))
    if status:
        out = inject_tspan(out, "dyn-status", check_len(status, LIMITS["dyn-status"], "status_text"))
    if out != svg:
        CONSOLE_SVG.write_text(out, encoding="utf-8")
        return True
    return False


def update_galaxy(data: dict) -> bool:
    projects = list(data.get("featured_projects", []))[:4]
    if not projects:
        return False
    svg = GALAXY_SVG.read_text(encoding="utf-8")
    out = svg
    for i, project in enumerate(projects, start=1):
        name = str(project.get("name", "")).strip()
        note = str(project.get("note", "")).strip()
        if name:
            out = inject_tspan(out, f"proj-{i}", check_len(name, LIMITS["proj"], f"featured_projects[{i}].name"))
        if note:
            out = inject_tspan(out, f"projsub-{i}", check_len(note, LIMITS["projsub"], f"featured_projects[{i}].note"))
    if out != svg:
        GALAXY_SVG.write_text(out, encoding="utf-8")
        return True
    return False


# ------------------------------------------------------------------ main ---

def main() -> int:
    missing = [p.name for p in (README, DATA, CONSOLE_SVG, GALAXY_SVG) if not p.exists()]
    if missing:
        print(f"error: missing required files: {', '.join(missing)}", file=sys.stderr)
        return 1

    data = yaml.safe_load(DATA.read_text(encoding="utf-8")) or {}

    try:
        changed = []
        if update_readme(data):
            changed.append("README.md")
        if update_console(data):
            changed.append("assets/live-console.svg")
        if update_galaxy(data):
            changed.append("assets/repository-galaxy.svg")
    except GenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"updated: {', '.join(changed)}" if changed else "no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
