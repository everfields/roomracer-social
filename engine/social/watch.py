"""The conditions that raise an alarm without a post failing: the runway, a batch left unrendered, a post with no outcome.

Run after intake, after metrics and at the end of each publisher run. An alarm clears itself once its condition does.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .alarms import Alarms
from .config import Config
from .intake import runway
from .state import PostLog, parse_iso


def check(root: Path, state_dir: Path, cfg: Config, alarms: Alarms, now: datetime) -> dict:
    log = PostLog(state_dir / "posts.csv")
    report: dict = {"runway": runway(root, cfg, log.used_ids(), now)}
    live = [n for n in cfg.enabled() if cfg.is_live(n.name)]
    for net in live:
        r = report["runway"][net.name]
        key = f"runway-{net.name}"
        if r["days"] < cfg.runway_alarm_days:
            alarms.raise_(key, f"{net.name}: {r['days']} days of posts left",
                          f"{r['posts']} checked posts wait for {net.name}, at {r['per_day']} a day: under "
                          f"{cfg.runway_alarm_days} days. Did the last render run? Did intake quarantine the batch? An empty "
                          f"queue goes quiet; it never reposts.")
        else:
            alarms.clear(key, f"{r['days']} days of runway")
    hb_file = root / "pc" / "heartbeat.json"
    hb = json.loads(hb_file.read_text(encoding="utf-8")) if hb_file.is_file() else {}
    at = parse_iso(str(hb.get("at", "")))
    report["heartbeat"] = hb.get("at", "")
    # The heartbeat moves only when a batch renders, so its age says nothing while every batch is rendered (a full
    # queue needs no new batch; the runway alarm covers a queue running out). It alarms only when a batch newer than
    # the last rendered week has waited past heartbeat_alarm_hours, or nothing ever rendered (Every Little Room's
    # false alarm fired three times, 2026-11-17 to 11-22, each costing an incident run).
    batch_dir = root / "batches"
    done_week = str(hb.get("week", ""))
    waiting = sorted(b.stem for b in batch_dir.glob("*.json") if b.stem > done_week) if batch_dir.is_dir() else []
    report["unrendered"] = waiting
    if live:
        age_h = (now - at).total_seconds() / 3600 if at else None
        if age_h is None or (waiting and age_h > cfg.heartbeat_alarm_hours):
            alarms.raise_("heartbeat", "a batch is waiting to render",
                          f"The last render was {hb.get('at') or 'never'} "
                          f"({'never' if age_h is None else f'{age_h:.0f} h ago'}, week {done_week or 'none'}) and "
                          f"{', '.join(waiting) or 'no batch'} is not rendered yet. Check the latest social-render run. "
                          f"Publishing carries on from the queue.")
        else:
            alarms.clear("heartbeat", f"heartbeat {hb.get('at')}, nothing waiting to render")
    stuck = log.unresolved()
    report["unresolved"] = [f"{r['network']}/{r['id']}" for r in stuck]
    for r in stuck:
        alarms.raise_(f"unresolved-{r['network']}-{r['id']}", f"{r['network']}: a post has no outcome",
                      f"{r['id']} was being posted at {r['at']} and the run stopped before the answer. Check "
                      f"{r['network']}: if it is there, log it with `social resolve {r['network']} {r['id']} --url <link>`; "
                      f"if not, `--failed`. {r['network']} posts nothing until then.", "high")
    return report
