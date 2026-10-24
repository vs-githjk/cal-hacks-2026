"""Offline access to Lane C's hosted SIM pages (data/liar_pages/site): the claim check reads these files
instead of fetching http://127.0.0.1:8765, so the demo needs no server and no network."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from demo.common import PAGE_BASE, SITE


def read_page(name: str) -> str:
    return (SITE / Path(name).name).read_text(encoding="utf-8")


def page_listing(name: str) -> dict:
    """The page's own facts: its <script id="listing"> JSON (what the claim check reads)."""
    m = re.search(r'<script type="application/json" id="listing">(.*?)</script>', read_page(name), re.S)
    if not m:
        raise ValueError(f"{name} has no listing JSON")
    return json.loads(m.group(1))


def fixture_fetch(url: str) -> bytes:
    """Serve hosted-page URLs from disk; refuse everything else, like a machine with no network."""
    if url.startswith(PAGE_BASE):
        path = Path(urlsplit(url).path).name
        if (SITE / path).is_file():
            return (SITE / path).read_bytes()
    raise OSError(f"offline demo: not fetching {url}")
