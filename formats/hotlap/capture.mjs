#!/usr/bin/env node
// Films RoomRacer's own Hot Lap in a headless Chrome on the PC's GPU, with no third-party library: the DevTools
// protocol over Node's built-in WebSocket. Only our own renders are filmed: every image that is not served by
// roomracer.com is refused, so no brand photo ever reaches a frame, and analytics are blocked.
//   node capture.mjs --url "https://roomracer.com/?rig=<id>&lapq=high&internal=1" --track laguna-seca --out <dir>
//        [--skip 12] [--seconds 24] [--full] [--width 540 --height 960 --scale 2]
// Writes <dir>/f00000.jpg... and <dir>/frames.ffconcat (each frame with its real duration) and <dir>/capture.json.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

const args = {};
for (let i = 2; i < process.argv.length; i++) {
  const a = process.argv[i];
  if (!a.startsWith('--')) continue;
  const next = process.argv[i + 1];
  if (next === undefined || next.startsWith('--')) args[a.slice(2)] = true;
  else args[a.slice(2)] = process.argv[++i];
}
const out = path.resolve(String(args.out ?? 'capture'));
const W = Number(args.width ?? 540);
const H = Number(args.height ?? 960);
const SCALE = Number(args.scale ?? 2);
const SKIP = Number(args.skip ?? 10);
const SECONDS = Number(args.seconds ?? 20);
const CHROME = args.chrome ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OWN = /(^|\.)roomracer\.com$/;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'rr-capture-'));
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, `--window-size=${W},${H}`, `--force-device-scale-factor=${SCALE}`,
  '--ignore-gpu-blocklist', '--enable-gpu-rasterization', '--use-angle=d3d11', '--mute-audio', '--hide-scrollbars',
  '--no-first-run', '--no-default-browser-check', '--disable-background-timer-throttling',
  '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', 'about:blank',
], { stdio: 'ignore' });

let ws;
let id = 0;
const pending = new Map();
const listeners = [];
function send(method, params = {}) {
  const msg = { id: ++id, method, params };
  ws.send(JSON.stringify(msg));
  return new Promise((resolve, reject) => pending.set(msg.id, { resolve, reject, method }));
}
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.value;

async function connect() {
  const portFile = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await sleep(100);
  const port = fs.readFileSync(portFile, 'utf8').split('\n')[0].trim();
  let page;
  for (let i = 0; i < 50 && !page; i++) {
    page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page');
    if (!page) await sleep(100);
  }
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.reject(new Error(`${p.method}: ${m.error.message}`)) : p.resolve(m.result);
    } else if (m.method) for (const l of listeners) l(m);
  };
}

async function main() {
  await connect();
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setBlockedURLs', { urls: ['*google-analytics.com*', '*googletagmanager.com*', '*/_vercel/insights*', '*/_vercel/speed-insights*', '*doubleclick*'] });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*', resourceType: 'Image' }] });
  let refused = 0;
  listeners.push((m) => {
    if (m.method !== 'Fetch.requestPaused') return;
    const host = new URL(m.params.request.url).hostname;
    if (m.params.request.url.startsWith('data:') || OWN.test(host) || host === 'localhost' || host === '127.0.0.1') send('Fetch.continueRequest', { requestId: m.params.requestId }).catch(() => {});
    else {
      refused++;
      send('Fetch.failRequest', { requestId: m.params.requestId, errorReason: 'BlockedByClient' }).catch(() => {});
    }
  });
  await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 0, mobile: true });
  await send('Emulation.setTouchEmulationEnabled', { enabled: true });
  const loaded = new Promise((r) => listeners.push((m) => m.method === 'Page.loadEventFired' && r()));
  await send('Page.navigate', { url: String(args.url) });
  await loaded;
  for (let i = 0; i < 60 && !(await evaluate("!!document.querySelector('.lap-btn')")); i++) await sleep(500);
  await sleep(1500);
  await evaluate("document.querySelector('.lap-btn').click()");
  if (args.track) await evaluate(`[...document.querySelectorAll('.hud-tracks button')].find(b => b.textContent.trim().toLowerCase().replace(/ /g,'-') === ${JSON.stringify(String(args.track))})?.click()`);
  if (args.full) await evaluate("[...document.querySelectorAll('.hud-actions button')].find(b => b.textContent.includes('Full screen'))?.click()");
  // the circuit is ready once the timer leaves "Loading…"
  for (let i = 0; i < 240; i++) {
    const t = await evaluate("document.querySelector('.hud-time')?.textContent || ''");
    if (t && !t.includes('Loading')) break;
    await sleep(500);
  }
  // what is on screen is the lap and its timing screen, not the site's controls
  await evaluate(`(() => { const s = document.createElement('style'); s.textContent = '.hud-actions,.hud-tracks,.viewbar,.fitbadge,header,nav,footer,.panel,.sheet,.dock,.tabs,[class*=cookie],[class*=consent]{display:none!important} .viewport.lap-on{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;z-index:2147483000!important}'; document.head.appendChild(s); })()`);
  await sleep(SKIP * 1000);
  const frames = [];
  listeners.push((m) => {
    if (m.method !== 'Page.screencastFrame') return;
    const file = `f${String(frames.length).padStart(5, '0')}.jpg`;
    fs.writeFileSync(path.join(out, file), Buffer.from(m.params.data, 'base64'));
    frames.push({ file, t: m.params.metadata.timestamp });
    send('Page.screencastFrameAck', { sessionId: m.params.sessionId }).catch(() => {});
  });
  await send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: W * SCALE, maxHeight: H * SCALE, everyNthFrame: 1 });
  // the car's own telemetry from the timing screen, for an engine sound made by code
  const telemetry = [];
  const until = Date.now() + SECONDS * 1000;
  while (Date.now() < until) {
    const v = await evaluate("({ t: Date.now() / 1000, mph: +(document.querySelector('.hud-speed b')?.textContent || 0), gear: +(document.querySelector('.hud-gear')?.textContent || 1), lights: document.querySelectorAll('.hud-revs i.g, .hud-revs i.r, .hud-revs i.p').length })");
    if (v) telemetry.push(v);
    await sleep(40);
  }
  await send('Page.stopScreencast');
  await sleep(300);
  const hud = await evaluate("({ track: document.querySelector('.hud-tracks .on')?.textContent || '', attribution: document.querySelector('.hud-attr')?.textContent || '', lap: document.querySelector('.hud-time')?.textContent || '' })");
  const gl = await evaluate("(() => { const c = document.createElement('canvas').getContext('webgl2'); const d = c && c.getExtension('WEBGL_debug_renderer_info'); return d ? c.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'unknown'; })()");
  const lines = ['ffconcat version 1.0'];
  frames.forEach((f, i) => {
    const next = frames[i + 1]?.t ?? f.t + 1 / 30;
    lines.push(`file ${f.file}`, `duration ${Math.max(0.001, next - f.t).toFixed(4)}`);
  });
  if (frames.length) lines.push(`file ${frames.at(-1).file}`);
  fs.writeFileSync(path.join(out, 'frames.ffconcat'), `${lines.join('\n')}\n`);
  const t0 = frames[0]?.t ?? 0;
  fs.writeFileSync(path.join(out, 'telemetry.json'), `${JSON.stringify(telemetry.map((x) => ({ ...x, t: Number((x.t - t0).toFixed(3)) })))}\n`);
  const span = frames.length > 1 ? frames.at(-1).t - frames[0].t : 0;
  const info = { frames: frames.length, seconds: Number(span.toFixed(2)), fps: Number((frames.length / Math.max(span, 0.001)).toFixed(1)), refused_images: refused, gpu: gl, ...hud };
  fs.writeFileSync(path.join(out, 'capture.json'), `${JSON.stringify(info, null, 2)}\n`);
  console.log(JSON.stringify(info));
}

main()
  .catch((e) => {
    console.error(`capture: ${e.message}`);
    process.exitCode = 1;
  })
  .finally(() => {
    try { ws?.close(); } catch {}
    chrome.kill();
    setTimeout(() => fs.rmSync(profile, { recursive: true, force: true }), 1500);
  });
