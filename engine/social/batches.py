"""The week's batch comes to the social repo by itself: the pipe pulls it from the company repo.

The company's `social` loop writes `company/social/batches/<yyyy-Www>.json` in its own (often private) repo. This repo
runs the publisher, so it reads those files with COS_EVENT_TOKEN, the fine-grained token it already holds for alarms
(Contents on the company repo), and writes them to `batches/`, where `social-render.yml` renders the formats that need
no GPU. Nothing waits for the founder's PC (RoomRacer's first approved batch sat a day in the company repo, waiting for
a Sunday task on a PC, 2026-11-14).

Only approved formats pass. A batch with a post whose format has no folder here, or whose `format.json` has no
`approved`, is refused whole, with the reason: the founder approves a format once, whoever installs it records the gate
there, and a rejected format can never ride in on a batch. Past weeks are ignored.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .http import Request, Transport

API = "https://api.github.com"
NAME = re.compile(r"^(\d{4})-W(\d{2})\.json$")
FORMAT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")
FOLDER = "company/social/batches"


def blob_sha(data: bytes) -> str:
    """The sha git gives a file, which is what the contents API lists: equal means unchanged, with no download."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def approved(root: Path, fmt: str) -> bool:
    if not FORMAT.match(fmt or ""):
        return False
    try:
        return bool(json.loads((root / "formats" / fmt / "format.json").read_text(encoding="utf-8")).get("approved"))
    except (OSError, ValueError):
        return False


def problems(root: Path, raw: bytes) -> list[str]:
    try:
        batch = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ["not valid JSON"]
    posts = batch.get("posts") if isinstance(batch, dict) else None
    if not isinstance(posts, list) or not posts:
        return ["no posts"]
    formats = sorted({str(p.get("format", "")) if isinstance(p, dict) else "" for p in posts})
    return [f"format {f or '(none)'} is not approved here (formats/{f}/format.json has no \"approved\")" for f in formats
            if not approved(root, f)]


def pull(root: Path, company_repo: str, env: Mapping[str, str], transport: Transport, now: datetime) -> dict:
    token = (env.get("COS_EVENT_TOKEN") or "").strip()
    if not token or not company_repo:
        return {"skipped": "COS_EVENT_TOKEN or company_repo is missing", "new": [], "unchanged": 0, "refused": []}
    head = {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
    listing = transport.send(Request("GET", f"{API}/repos/{company_repo}/contents/{FOLDER}",
                                     headers={**head, "Accept": "application/vnd.github+json"}))
    if listing.status == 404:
        return {"skipped": f"{company_repo} has no {FOLDER} yet", "new": [], "unchanged": 0, "refused": []}
    if not listing.ok:
        raise RuntimeError(f"batches: {company_repo} answered {listing.status}")
    y, w, _ = now.isocalendar()
    report: dict = {"new": [], "unchanged": 0, "refused": []}
    for entry in sorted(listing.json(), key=lambda e: str(e.get("name"))):
        m = NAME.match(str(entry.get("name", "")))
        if entry.get("type") != "file" or not m or (int(m[1]), int(m[2])) < (y, w):
            continue
        local = root / "batches" / entry["name"]
        if local.is_file() and blob_sha(local.read_bytes()) == entry.get("sha"):
            report["unchanged"] += 1
            continue
        got = transport.send(Request("GET", f"{API}/repos/{company_repo}/contents/{FOLDER}/{entry['name']}",
                                     headers={**head, "Accept": "application/vnd.github.raw+json"}))
        if not got.ok:
            report["refused"].append({"file": entry["name"], "why": [f"could not be read ({got.status})"]})
            continue
        why = problems(root, got.body)
        if why:
            report["refused"].append({"file": entry["name"], "why": why})
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(got.body)
        report["new"].append(f"batches/{entry['name']}")
    return report
