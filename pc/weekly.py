"""The PC's two Windows tasks for RoomRacer's social repo. Run with the PC folder's pythonw.exe, so no window opens.

    pythonw weekly.py          Sundays 12:00 (or as soon as the PC is on): plan next week, render it, upload it
    pythonw weekly.py --tick   every 15 minutes: wake the publisher (GitHub drops scheduled runs)

Logs go to C:/dev/social-pc/logs. A stopgap that lives on this PC because the renders need its GPU; the plan to move
the rest to the cloud is in RoomRacer's docs/coo-thread.md (2026-11-11).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FOLDER = Path("C:/dev/social-pc")
PY = FOLDER / "venv" / "Scripts" / "python.exe"
LOGS = FOLDER / "logs"
NO_WINDOW = 0x08000000


def run(cmd: list[str], log, cwd: Path = REPO) -> None:
    log.write(f"$ {' '.join(map(str, cmd))}\n")
    log.flush()
    r = subprocess.run(list(map(str, cmd)), cwd=cwd, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        raise SystemExit(f"failed ({r.returncode}): {' '.join(map(str, cmd))}")


def tick() -> None:
    subprocess.run(["gh", "api", "repos/everfields/roomracer-social/dispatches", "-f", "event_type=social-tick"],
                   capture_output=True, creationflags=NO_WINDOW, timeout=60)


def weekly() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    y, w, _ = (date.today() + timedelta(days=1)).isocalendar()
    week = f"{y}-W{w:02d}"
    with (LOGS / f"roomracer-weekly-{datetime.now():%Y%m%d-%H%M}.log").open("w", encoding="utf-8") as log:
        run(["git", "pull", "--rebase", "origin", "main"], log)
        # the Company OS `social` loop writes the batch (company/social/batches/); plan.py only fills a week it left empty
        spec = subprocess.run(["gh", "api", f"repos/everfields/roomracer/contents/company/social/batches/{week}.json", "-H",
                               "Accept: application/vnd.github.raw+json"], capture_output=True, text=True, encoding="utf-8",
                              creationflags=NO_WINDOW)
        if spec.returncode == 0 and spec.stdout.strip().startswith("{"):
            (REPO / "batches").mkdir(exist_ok=True)
            (REPO / "batches" / f"{week}.json").write_text(spec.stdout, encoding="utf-8")
            log.write(f"batch {week} from the social loop\n")
        else:
            run([PY, "plan.py", "--week", week, "--posts", "7", "--roomracer", "C:/dev/roomracer"], log)
        run(["git", "add", "batches"], log)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO, creationflags=NO_WINDOW).returncode != 0:
            run(["git", "commit", "-m", f"plan {week}"], log)
        run([PY, "engine/pc/render.py", "--repo", REPO, "--folder", FOLDER, "--batch", f"batches/{week}.json",
             "--out", FOLDER / "runs" / f"roomracer-{week}", "--upload"], log)
        log.write(f"done {datetime.now():%Y-%m-%d %H:%M}\n")


if __name__ == "__main__":
    tick() if "--tick" in sys.argv else weekly()
