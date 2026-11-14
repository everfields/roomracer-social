"""The week's batch comes to the social repo by itself, on the bus the alarms already use: the company repo's issues.

The company's `social` loop writes `company/social/batches/<yyyy-Www>.json` in its own (often private) repo, and its
engine posts each file, gzipped, on one issue labelled `cos:social-batch` (`cos social outbox`, every pulse). This repo
is public, so its token (COS_EVENT_TOKEN) may touch only that repo's issues, never its files: it reads the open batch
issues and writes each batch to `batches/`, where `social-render.yml` renders the formats that need no GPU. Nothing waits
for the founder's PC (RoomRacer's first approved batch sat a day in the company repo, waiting for a Sunday task on a PC,
2026-11-14).

What is trusted: only someone who can write to the company repo can add a label, and the payload must match the sha256
in the engine's marker. Only approved formats pass: a batch with a post whose format has no folder here, or whose
`format.json` has no `approved`, is refused whole, with the reason. The founder approves a format once, whoever installs
it records the gate there, and a rejected format can never ride in on a batch. Past weeks are ignored.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .http import Request, Transport

API = "https://api.github.com"
LABEL = "cos:social-batch"
WEEK = re.compile(r"^\d{4}-W\d{2}$")
FORMAT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")
MARK = re.compile(r"<!-- cos-social-batch:(\{[^>]*\}) -->")
BLOCK = re.compile(r"```cos-social-batch\s+([A-Za-z0-9+/=\s]+?)\s*```")
MAX_BYTES = 2_000_000


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


def unpack(body: str) -> tuple[str, bytes]:
    """The week and the batch file an issue carries. Raises ValueError when it is not one the engine wrote, whole."""
    mark, block = MARK.search(body or ""), BLOCK.search(body or "")
    if not mark or not block:
        raise ValueError("no batch in it")
    meta = json.loads(mark[1])
    week = str(meta.get("week", ""))
    if not WEEK.match(week):
        raise ValueError("no week in its marker")
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode("".join(block[1].split()), validate=True))) as z:
        raw = z.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("too large")
    if hashlib.sha256(raw).hexdigest() != meta.get("sha"):
        raise ValueError("its content does not match the engine's checksum")
    return week, raw


def pull(root: Path, company_repo: str, env: Mapping[str, str], transport: Transport, now: datetime) -> dict:
    token = (env.get("COS_EVENT_TOKEN") or "").strip()
    report: dict = {"new": [], "unchanged": 0, "refused": []}
    if not token or not company_repo:
        return {**report, "skipped": "COS_EVENT_TOKEN or company_repo is missing"}
    resp = transport.send(Request("GET", f"{API}/repos/{company_repo}/issues",
                                  headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                           "X-GitHub-Api-Version": "2022-11-28"},
                                  params={"labels": LABEL, "state": "open", "per_page": "50"}))
    if not resp.ok:
        raise RuntimeError(f"batches: {company_repo} answered {resp.status} (COS_EVENT_TOKEN needs Issues: read on it)")
    y, w, _ = now.isocalendar()
    current = f"{y}-W{w:02d}"
    for issue in sorted(resp.json(), key=lambda i: int(i.get("number", 0))):
        where = f"#{issue.get('number')}"
        try:
            week, raw = unpack(str(issue.get("body") or ""))
        except (ValueError, OSError, EOFError) as e:
            report["refused"].append({"file": where, "why": [str(e) or "could not be read"]})
            continue
        if week < current:
            continue
        local = root / "batches" / f"{week}.json"
        if local.is_file() and local.read_bytes() == raw:
            report["unchanged"] += 1
            continue
        why = problems(root, raw)
        if why:
            report["refused"].append({"file": f"{week}.json ({where})", "why": why})
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(raw)
        report["new"].append(f"batches/{week}.json")
    return report
