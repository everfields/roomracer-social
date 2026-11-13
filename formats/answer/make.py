"""answer: one real buyer's question, answered in 15-25 seconds with the store's own data, ending at the page that has the list.

What a parent or a first-rig buyer asks before ordering (what to order, will it work with the PS5, will it fit, how loud,
what more money buys), answered with real parts, our estimated prices, real floor space and real compatibility from
roomracer.com. Type, layout and a to-scale floor plan are drawn by code in the site's own look (scene.html, rendered frame
by frame in a headless Chrome); the voice is Kokoro's stock voice, read from the same lines. No GPU model, no LLM, no
image from outside: product names are written, never a brand's photo or logo. Nothing here is AI-generated imagery; the
voice is synthetic and the caption says so where a network asks.

post["prompts"]: {"spec": {...}, "voice": "af_heart", "speed": 1.05}. spec = {"tag", "fine", "scenes": [...]}, each scene
one of:
  hook     {title, kicker?, sub?, say}
  list     {title, items: [{label, name, price | 0 + free, say}], totalLabel?, note?, outro}
  facts    {title, items: [{k, v, tone?, say}]}
  compare  {title, items: [{price, name, line, sound, tone?, say}], note?, outro?}
  plan     {title, room: {w, d (inches), label?, fixed: [rects]}, items: [{caption, detail?, tone, rects, say}]}
  end      {title, sub?, cta?, site?, say}
rects are {x, y, w, d, label?, dashed?} in inches inside the room. tone: green | yellow | purple | red. Every number must
be the one roomracer.com shows on the linked page that day: prices are our estimates of typical US prices, never a store's.
"""

import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAD = 0.35   # breath after each line
TAIL = 1.2   # the end card stays a moment after its line


def _say(kit, text, out, p):
    return kit.voice(text, out, voice=p.get("voice", "af_heart"), speed=float(p.get("speed", 1.05)))


def make(post, out_dir, kit):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = post["prompts"]
    spec = json.loads(json.dumps(p["spec"]))
    clips: list[tuple[Path, float]] = []  # (wav, seconds of timeline it occupies)
    t = 0.0
    n = 0

    def line(text: str) -> float:
        nonlocal n
        wav, secs = _say(kit, text, out_dir / f"say{n:02d}.wav", p)
        n += 1
        clips.append((wav, secs + PAD))
        return secs + PAD

    def hold(secs: float) -> float:
        clips.append((None, secs))
        return secs

    for s in spec["scenes"]:
        s["start"] = t
        local = 0.0
        if s.get("say"):
            local += line(s["say"])
        if s["type"] == "hook" and s.get("sub") and "subAt" not in s:
            s["subAt"] = max(0.5, local * 0.45)
        for it in s.get("items", []):
            it["at"] = local
            local += line(it["say"]) if it.get("say") else hold(0.6)
        if s.get("outro"):
            s["outroAt"] = local
            local += line(s["outro"])
        if s["type"] == "end":
            s["ctaAt"] = 0.4
            local += hold(TAIL)
        if local < 1.5:
            local += hold(1.5 - local)
        s["dur"] = local
        t += local
    total = t

    # the voice track: each line at its place in the timeline
    parts = []
    for i, (wav, secs) in enumerate(clips):
        seg = out_dir / f"seg{i:02d}.wav"
        if wav is None:
            kit.run("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{secs:.3f}", "-c:a", "pcm_s16le", str(seg))
        else:
            kit.run("-i", str(wav), "-af", f"apad=whole_dur={secs:.3f}", "-t", f"{secs:.3f}", "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(seg))
        parts.append(seg)
    lst = out_dir / "voice.txt"
    lst.write_text("".join(f"file '{x.resolve().as_posix()}'\n" for x in parts), encoding="utf-8")
    voice = out_dir / "voice.wav"
    kit.run("-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "pcm_s16le", str(voice))

    (out_dir / "spec.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    font = next((kit.folder / "tools" / "inter").rglob("InterVariable.ttf"))
    frames = out_dir / "frames"
    cmd = ["node", str(HERE / "frames.mjs"), "--spec", str(out_dir / "spec.json"), "--font", str(font), "--out", str(frames)]
    if os.environ.get("CHROME"):
        cmd += ["--chrome", os.environ["CHROME"]]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"frames failed: {r.stderr[-600:]}")
    video = out_dir / "video.mp4"
    kit.run("-framerate", "30", "-i", str(frames / "f%05d.jpg"), "-t", f"{total:.3f}", "-vf", "format=yuv420p", "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-an", str(video))
    bed = kit.bed(total, out_dir / "bed.wav", root_hz=98.0, volume=0.035)
    final = kit.finish(video, out_dir / "final.mp4", voice=voice, bed=bed)
    return {"file": final, "ai": {"generated": False}}
