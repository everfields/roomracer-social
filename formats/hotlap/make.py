"""hotlap: a stretch of RoomRacer's own Hot Lap, onboard and full screen, filmed from the live site on the PC's GPU.

Nothing here is AI-made, and nothing is a brand's: the circuit is drawn by RoomRacer's code from OpenStreetMap and SRTM,
every image not served by roomracer.com is refused while filming, and the sound is an engine note made by code from the
car's own speed and revs. The OpenStreetMap credit is on screen for the whole clip.

post["prompts"]: track (laguna-seca | suzuka), rig (its livery colours the car), skip (seconds into the lap), seconds,
hook (the line on screen at the start).
"""

import json
import math
import subprocess
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SITE = "https://roomracer.com"
CREDIT = "Track © OpenStreetMap contributors · SRTM elevation"


def engine_wav(telemetry: list[dict], seconds: float, out: Path, rate: int = 44100) -> Path:
    """A six-cylinder note from the revs: firing frequency = rpm / 60 * 3, with harmonics and a little road noise."""
    if not telemetry:
        telemetry = [{"t": 0.0, "lights": 6}, {"t": seconds, "lights": 6}]
    ts = np.array([max(0.0, float(x["t"])) for x in telemetry])
    revs = np.array([float(x["lights"]) / 12 for x in telemetry])
    n = int(seconds * rate)
    t = np.arange(n) / rate
    r = np.interp(t, ts, revs)
    k = max(1, int(rate * 0.12))
    r = np.convolve(np.pad(r, (k, k), mode="edge"), np.ones(k) / k, mode="same")[k:-k]
    rpm = 3500 + 5500 * r
    f = rpm / 60 * 3
    phase = 2 * np.pi * np.cumsum(f) / rate
    tone = sum(a * np.sin(h * phase) for h, a in ((1, 1.0), (2, 0.55), (3, 0.3), (4, 0.18), (6, 0.08)))
    rough = 0.08 * np.random.default_rng(7).standard_normal(n)
    noise = np.convolve(rough, np.ones(30) / 30, mode="same")
    sig = (0.6 + 0.4 * r) * tone / 2.2 + noise
    fade = np.minimum(1, np.minimum(t / 0.4, (seconds - t) / 0.6))
    pcm = (np.clip(sig * fade * 0.5, -1, 1) * 32767).astype("<i2")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return out


def make(post, out_dir, kit):
    out_dir = Path(out_dir)
    p = post["prompts"]
    seconds = float(p.get("seconds", 18))
    cap = out_dir / "capture"
    url = f"{SITE}/?rig={p['rig']}&lapq=high&internal=1"
    if not (cap / "capture.json").is_file():  # footage already filmed is reused: a lap is filmed in real time
        r = subprocess.run(["node", str(HERE / "capture.mjs"), "--url", url, "--track", p["track"], "--full", "--skip",
                            str(p.get("skip", 10)), "--seconds", str(seconds + 0.6), "--out", str(cap)],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"capture failed: {r.stderr[-600:]}")
    info = json.loads((cap / "capture.json").read_text(encoding="utf-8"))
    if info["fps"] < 24 or "SwiftShader" in info.get("gpu", "") or info["track"].lower().replace(" ", "-") != p["track"]:
        raise RuntimeError(f"capture not good enough: {info}")
    raw = out_dir / "raw.mp4"
    kit.run("-f", "concat", "-safe", "0", "-i", str(cap / "frames.ffconcat"), "-t", f"{seconds:.3f}", "-vf",
            "fps=30,scale=1080:1920:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", str(raw))
    hook = kit.caption_png(p["hook"], out_dir / "hook.png", y=560, size=78)
    credit = kit.caption_png(CREDIT, out_dir / "credit.png", y=1668, size=28, weight="Medium")  # above the speed readout
    with_hook = kit.overlay(raw, hook, out_dir / "hooked.mp4", start=0.1, end=3.4)
    video = kit.overlay(with_hook, credit, out_dir / "video.mp4")
    telemetry = json.loads((cap / "telemetry.json").read_text(encoding="utf-8"))
    sound = engine_wav(telemetry, kit.seconds(video), out_dir / "engine.wav")
    final = kit.finish(video, out_dir / "final.mp4", voice=sound, loudness=-17.0)
    return {"file": final, "ai": {"generated": False}}
