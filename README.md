# RoomRacer: social

**Dry run only** until Carlos and Alberto approve the direction and the accounts exist: `SOCIAL_CRON=dry-run`, and no network is live. RoomRacer has no Company OS, so three things differ from the standard install:
- `plan.py` writes each week's batch from RoomRacer's own data, in place of the Company OS `social` loop;
- alarms open issues labelled `social:alarm` in `everfields/roomracer` (`"alarms": {"mode": "issues"}` in `social.json`), or here until the token for that repo exists;
- the PC is the outside clock: a Windows task sends `social-tick` every 15 minutes while it is on.

The format is `formats/hotlap/`: RoomRacer's own Hot Lap, filmed from roomracer.com on the PC's GPU, with every image not served by roomracer.com refused while filming.

The publisher of RoomRacer's own social accounts. Public on purpose: standard Actions runners are free on public repos, GitHub Pages gives the media the plain URLs that Buffer and Meta fetch, and the media are public once posted anyway. Secrets stay secret.

Claude writes in the company repo (`company/social/batches/`), the PC renders at night, and this repo checks and publishes.

- `engine/`: the pipe, vendored from the launch-company skill (`install-social.mjs`). Improve it there, never here.
- `formats/<name>/`: the creative engine: `brief.md`, `make.py`, `samples/`.
- `queue/<network>/`: ready posts. `quarantine/`: what failed intake, with the reasons. `archive/`: posted a week ago or more.
- Branch `social-state`: `posts.csv` (a row before every API call), `state.json`, `metrics/`.
- `social.json`: time zone, slots, routes. Limits are the engine's: a company may go below them, never above.

Repository variables: `SOCIAL_CRON` (`off`, `dry-run`, `live`), `SOCIAL_LIVE_NETWORKS`, `SOCIAL_PUBLIC_BASE_URL`, `SOCIAL_ROUTE_<NETWORK>`, `SOCIAL_SLOTS_<NETWORK>`.

Run by hand from the repo root, with `PYTHONPATH=engine`: `python -m social status`, `validate`, `due`, `publish`, `intake`, `metrics`, `watch`. A post with no outcome: `python -m social resolve <network> <id> --url <link>` or `--failed`. A stopped network: `python -m social resume <network> --reason "..."`.
