"""The nightly batch runner, on the PC: pull the week's spec, make the posts, mark them, hand them to the social repo.

    python render.py --repo <social repo> --folder C:/dev/social-pc [--batch file.json | --week 2026-W46] [--upload] [--only id]

Runs in the PC folder's venv. For each post in the spec it calls `formats/<format>/make.py`, marks anything AI-made with
C2PA (last, so nothing strips it), and writes one queue row per network, each with its own caption. With `--upload` it
puts the media on the release `media`, pushes the rows and the heartbeat, and the social repo's intake takes over. It holds
no platform secret: it uses Carlos's own `gh` login. Not a self-hosted runner: the repo is public and a fork's pull
request could otherwise run code here; this only runs what is on main.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import socket
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit import Kit  # noqa: E402
from mark import mark, read  # noqa: E402

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,100}$")
RELEASE = "media"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sh(*cmd: str, cwd: Path | None = None) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} {cmd[1] if len(cmd) > 1 else ''}: {(r.stderr or r.stdout)[:600]}")
    return r.stdout.strip()


def this_week() -> str:
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


def batch_from_company(company_repo: str, week: str) -> dict | None:
    r = subprocess.run(["gh", "api", f"repos/{company_repo}/contents/company/social/batches/{week}.json", "-H",
                        "Accept: application/vnd.github.raw+json"], capture_output=True, text=True, encoding="utf-8")
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def load_format(repo: Path, name: str):
    if not NAME.match(name):
        raise ValueError(f"bad format name {name!r}")
    path = repo / "formats" / name / "make.py"
    if not path.is_file():
        raise FileNotFoundError(f"formats/{name}/make.py is missing")
    spec = importlib.util.spec_from_file_location(f"format_{name.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rows_for(post: dict, file: str, digest: str, ai: dict, week: str) -> list[dict]:
    out = []
    for net in post["networks"]:
        caption = (post.get("captions") or {}).get(net, post.get("caption", ""))
        out.append({
            "id": f"{post['id']}-{net}", "network": net, "format": post["format"], "batch": week,
            "media": {"file": file, "sha256": digest, "kind": "video", **({"cover_s": post["cover_s"]} if "cover_s" in post else {})},
            "caption": caption, "title": post.get("title", ""), "language": post.get("language", "en"),
            "tags": post.get("tags", []), "ai": ai, "trial": bool(post.get("trial")) and net == "instagram",
            **({"earliest": post["earliest"]} if post.get("earliest") else {}),
            **({"latest": post["latest"]} if post.get("latest") else {}),
            **({"options": dict(post["options"])} if post.get("options") else {}),  # publish.py reads them (long_form, category)
        })
    return out


def render(repo: Path, folder: Path, batch: dict, out: Path, *, only: str | None = None, on_made=None) -> list[dict]:
    week = batch["week"]
    kit = Kit(folder, out / "work")
    made: list[dict] = []
    try:
        for post in batch["posts"]:
            if only and post["id"] != only:
                continue
            if not ID.match(str(post.get("id", ""))):
                raise ValueError(f"bad post id {post.get('id')!r}")
            if any((repo / "queue" / n / f"{post['id']}-{n}.json").exists() or (repo / "archive" / n / f"{post['id']}-{n}.json").exists()
                   for n in post["networks"]):
                print(f"= {post['id']}: already made", flush=True)
                continue
            ready = out / "media" / f"{post['id']}.mp4"
            if ready.is_file():  # a render from a run that stopped before the upload: never paid for twice
                ai = {"generated": bool(post["ai"]["generated"]), "realistic": bool(post["ai"].get("realistic"))}
                made.append({"post": post, "file": ready, "ai": ai, "sha256": sha256(ready), "week": week})
                print(f"= {post['id']}: reusing the render", flush=True)
                if on_made:
                    on_made(made[-1])
                continue
            work = out / "work" / post["id"]
            work.mkdir(parents=True, exist_ok=True)
            kit.seed = int(hashlib.sha256(post["id"].encode()).hexdigest()[:8], 16)
            result = load_format(repo, post["format"]).make(post, work, kit)
            src = Path(result["file"])
            ai = {"generated": bool(result["ai"]["generated"]), "realistic": bool(result["ai"].get("realistic"))}
            final = out / "media" / f"{post['id']}.mp4"
            final.parent.mkdir(parents=True, exist_ok=True)
            if ai["generated"]:
                mark(folder, src, final, composite=bool(result["ai"].get("composite")), title=post["id"], software=f"social engine, {post['format']}")
                if "trainedalgorithmicmedia" not in read(folder, final).lower():
                    raise RuntimeError(f"{post['id']}: the C2PA manifest did not verify")
            else:
                shutil.copy(src, final)
            made.append({"post": post, "file": final, "ai": ai, "sha256": sha256(final), "week": week})
            print(f"+ {post['id']}: {final} ({final.stat().st_size / 1048576:.1f} MB, ai={ai['generated']})", flush=True)
            if on_made:
                on_made(made[-1])
    finally:
        kit.done_with_models()
    return made


def push(repo: Path, paths: list[str], message: str) -> None:
    sh("git", "add", *paths, cwd=repo)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode != 0:
        sh("git", "commit", "-m", message, cwd=repo)
        sh("git", "pull", "--rebase", "--autostash", "origin", "main", cwd=repo)
        sh("git", "push", "origin", "HEAD:main", cwd=repo)


def ship(repo: Path, m: dict) -> None:
    # Each post goes out as soon as it is made, so a run that stops (a runner's time limit, the PC switched off) loses
    # only the post it was on, and the next run skips what is already queued (W49 lost 26 renders at 60 min, 2026-11-25).
    have = subprocess.run(["gh", "release", "view", RELEASE], cwd=repo, capture_output=True, text=True)
    if have.returncode != 0:
        sh("gh", "release", "create", RELEASE, "--title", "media", "--notes", "Rendered posts. The Pages runway serves them.", "--latest=false", cwd=repo)
    sh("gh", "release", "upload", RELEASE, str(m["file"]), "--clobber", cwd=repo)
    for row in rows_for(m["post"], m["file"].name, m["sha256"], m["ai"], m["week"]):
        p = repo / "queue" / row["network"] / f"{row['id']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    push(repo, ["queue"], f"post: {m['post']['id']}")


def publish(repo: Path, made: list[dict], folder: Path, week: str = "") -> None:
    hb = repo / "pc" / "heartbeat.json"
    hb.parent.mkdir(exist_ok=True)
    try:
        prev = str(json.loads(hb.read_text(encoding="utf-8")).get("week", ""))
    except (OSError, ValueError):
        prev = ""
    # The week is the newest batch rendered whole, even when every post was already made: the watch alarms only for a
    # batch in batches/ newer than it, so it never goes backwards and never blanks.
    done = max(prev, week or (made[0]["week"] if made else ""))
    hb.write_text(json.dumps({"at": now(), "host": socket.gethostname(), "rendered": len(made), "week": done},
                             indent=2) + "\n", encoding="utf-8")
    push(repo, ["queue", "pc/heartbeat.json"], f"batch: {len(made)} post(s), heartbeat {now()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--batch")
    ap.add_argument("--week")
    ap.add_argument("--out")
    ap.add_argument("--only")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    repo, folder = Path(a.repo).resolve(), Path(a.folder).resolve()
    out = Path(a.out or folder / "runs" / (a.week or this_week())).resolve()
    if a.upload:
        sh("git", "pull", "--rebase", "--autostash", "origin", "main", cwd=repo)
    if a.batch:
        batch = json.loads(Path(a.batch).read_text(encoding="utf-8-sig"))
    else:
        cfg = json.loads((repo / "social.json").read_text(encoding="utf-8-sig"))
        batch = batch_from_company(cfg["company_repo"], a.week or this_week())
    made = render(repo, folder, batch, out, only=a.only, on_made=(lambda m: ship(repo, m)) if a.upload else None) if batch else []
    if not batch:
        print(f"no batch spec for {a.week or this_week()}: heartbeat only")
    if a.upload:
        publish(repo, made, folder, week=str(batch.get("week", "")) if batch and not a.only else "")
    print(json.dumps({"made": [str(m["file"]) for m in made]}, indent=2))


if __name__ == "__main__":
    main()
