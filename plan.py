"""RoomRacer's weekly batch spec, from its own data: which circuit, which stretch of the lap, which rig's livery.

    python plan.py [--week 2026-W47] [--posts 7] [--roomracer C:/dev/roomracer]

RoomRacer has no Company OS, so this deterministic planner stands in for the `social` loop: it never repeats a
circuit-and-stretch, rotates the rigs' liveries, and takes captions and titles from a pool of true lines, each used
once. When the pool runs low it says so; the next step is to have Claude write them on the Max plan, the way
RoomRacer's own scripts do. Every post goes to TikTok, Instagram and YouTube, each with its caption.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
NETWORKS = ["tiktok", "instagram", "youtube"]

# Stretches of each lap, in seconds from the start line; a lap is about 1:25 at Laguna Seca and 2:05 at Suzuka.
STRETCHES = {"laguna-seca": [2, 18, 34, 50, 66], "suzuka": [2, 22, 42, 62, 82, 102]}

HOOKS = {
    "laguna-seca": ["Laguna Seca, California", "Monterey's hills, onboard", "One stretch of Laguna Seca", "Laguna Seca at GT3 pace",
                    "Drawn from map data: Laguna Seca"],
    "suzuka": ["Suzuka, Japan", "Suzuka, onboard", "A stretch of the figure eight", "Suzuka at GT3 pace", "Drawn from map data: Suzuka",
               "Suzuka, from the driver's seat"],
}
CAPTIONS = {
    "laguna-seca": [
        "Laguna Seca, Monterey, California: 2.24 miles, rebuilt from OpenStreetMap and satellite elevation data. #simracing",
        "The Corkscrew at Laguna Seca drops about 59 feet. This is one stretch of the lap, at simulated GT3 pace. #lagunaseca #simracing",
        "Eleven turns and no camera: every frame of this lap is drawn in the browser. #simracing",
        "Laguna Seca at simulated GT3 pace. You can drive the same lap on a rig of your own at roomracer.com #simrig",
        "Onboard at Laguna Seca. The livery on the car comes from one of the rigs we built. #simracing #lagunaseca",
    ],
    "suzuka": [
        "Suzuka is a figure eight: the track crosses over itself. 3.6 miles, rebuilt from map data. #suzuka #simracing",
        "Suzuka at simulated GT3 pace, drawn in the browser from OpenStreetMap data. #simracing",
        "Suzuka has the Esses, Degner, Spoon and 130R. This is one stretch of it, onboard. #suzuka",
        "A circuit in Japan, driven on a rig that fits a spare room. #simrig #simracing",
        "Onboard at Suzuka. The livery comes from one of our rig builds. #suzuka #simracing",
        "Same rig, a different continent: Suzuka at GT3 pace. #simracing",
    ],
}
TITLES = {
    "laguna-seca": ["Laguna Seca onboard at GT3 pace", "Laguna Seca, the road to the Corkscrew", "A stretch of Laguna Seca, drawn from map data",
                    "Laguna Seca in 18 seconds", "Monterey from the driver's seat"],
    "suzuka": ["Suzuka onboard at GT3 pace", "Suzuka: a stretch of the figure eight", "Suzuka, drawn from map data", "Suzuka in 18 seconds",
               "Suzuka from the driver's seat", "A lap of Japan's figure eight, in part"],
}


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def monday(week: str) -> date:
    y, w = week.split("-W")
    return date.fromisocalendar(int(y), int(w), 1)


def rigs(roomracer: Path) -> list[dict]:
    out = []
    for f in sorted((roomracer / "data" / "rigs").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("status", "published") == "published":
            out.append({"id": r["id"], "name": r.get("name", r["id"])})
    return out


def used() -> dict:
    u = {"pairs": set(), "captions": set(), "titles": set(), "hooks": set(), "rigs": []}
    for f in sorted((HERE / "batches").glob("*.json")):
        for p in json.loads(f.read_text(encoding="utf-8")).get("posts", []):
            pr = p.get("prompts", {})
            u["pairs"].add((pr.get("track"), pr.get("skip")))
            u["captions"].add(p.get("caption"))
            u["titles"].add(p.get("title"))
            u["hooks"].add(pr.get("hook"))
            u["rigs"].append(pr.get("rig"))
    return u


def plan(week: str, posts: int, roomracer: Path) -> dict:
    u = used()
    rig_list = rigs(roomracer)
    rig_list.sort(key=lambda r: (u["rigs"].count(r["id"]), r["id"]))
    tracks = ["laguna-seca", "suzuka"]
    out, start = [], monday(week)
    for i in range(posts):
        track = tracks[i % 2]
        skip = next((s for s in STRETCHES[track] if (track, s) not in u["pairs"]), None)
        cap = next((c for c in CAPTIONS[track] if c not in u["captions"]), None)
        title = next((t for t in TITLES[track] if t not in u["titles"]), None)
        hook = next((h for h in HOOKS[track] if h not in u["hooks"]), None)
        if None in (skip, cap, title, hook):
            print(f"! {track}: the pool of stretches or lines ran out; {i} post(s) planned")
            break
        rig = rig_list[i % len(rig_list)]
        u["pairs"].add((track, skip))
        u["captions"].add(cap)
        u["titles"].add(title)
        u["hooks"].add(hook)
        out.append({
            "id": f"{week}-{track}-{skip:03d}",
            "format": "hotlap",
            "networks": NETWORKS,
            "caption": cap,
            "title": title,
            "earliest": datetime.combine(start, datetime.min.time(), timezone.utc).isoformat().replace("+00:00", "Z"),
            "script": f"Onboard, full screen, {track} from {skip}s into the lap, the livery of the {rig['name']} rig.",
            "prompts": {"track": track, "skip": skip, "seconds": 18, "rig": rig["id"], "hook": hook},
            "ai": {"generated": False, "realistic": False},
        })
    return {"week": week, "posts": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default=iso_week(date.today() + timedelta(days=1)))
    ap.add_argument("--posts", type=int, default=7)
    ap.add_argument("--roomracer", default="C:/dev/roomracer")
    a = ap.parse_args()
    target = HERE / "batches" / f"{a.week}.json"
    if target.exists():
        print(f"= {target.name} already planned")
        return
    b = plan(a.week, a.posts, Path(a.roomracer))
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(b, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"+ {target.name}: {len(b['posts'])} post(s)")


if __name__ == "__main__":
    main()
