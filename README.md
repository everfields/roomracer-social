# RoomRacer: social

**Dry run only** until Carlos and Alberto approve the direction and the accounts exist: `SOCIAL_CRON=dry-run`, and no network is live. RoomRacer runs the Company OS since 2026-11-12. What differs from the standard install:
- The batches: the Company OS `social` loop writes them in `everfields/roomracer` (`company/social/batches/`). `plan.py` writes one from RoomRacer's own data only for a week the loop left empty.
- The alarms: they open `cos:alarm` issues in `everfields/roomracer`, carrying the engine's marker, which the incident loop owns. This is `"alarms": {"mode": "issues", "label": "cos:alarm"}` in `social.json`, and it needs only Issues write. Until that token exists, they open here.
- The outside clock: the PC sends `social-tick` every 15 minutes while it is on.

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
