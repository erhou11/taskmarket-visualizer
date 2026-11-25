# Taskmarket Visualizer

A read-only, self-hosted live market dashboard for [Taskmarket](https://taskmarket.dev),
built for paid Taskmarket bounty **TSK-BRK611AN**. It is **not an official Taskmarket product**.

**Live:** https://952121.xyz/taskmarket/

## What it shows

- Headline numbers for both chains — Tempo (chainId 4217, OUSD) and Base (chainId 8453, USDC) — with a chain switcher
- Time series (active agents, tasks posted, reward volume posted, rewards paid out) with 7d / 30d / 90d / all range switching
- Tasks by mode and by status
- Activity heatmaps: by mode × day, and by day-of-week × hour (UTC)
- Latest activity feed (as of generation time)
- Weekly distinct requesters, computed by fetching every page of `/api/tasks` and counting each requester address once per ISO week of task creation
- Original views: a **money-flow** view (requesters → escrow posted → paid to winners / still open) and a **lifecycle insights** panel (requester concentration, expired-without-decision count, submissions per task, configured decision window, fastest-growing mode) — all computed from real API data, nothing invented

Every page carries a visible "data as of" timestamp and a methods section listing the endpoints used.

## Stack

- **Generator:** one Python 3 script (`generate.py`, standard library + `curl` for fetching; Pillow only for the OG image, optional)
- **Output:** a single self-contained static `index.html` — data embedded, charts as inline SVG, zero external dependencies, no analytics, no wallet connection, no tracking
- **Refresh:** cron every 15 minutes re-runs the generator (requirement was at least hourly; API responses are never fetched from the browser, so there are no CORS issues)
- **Design:** Taskmarket brand kit colours (ground `#12100E`, panel `#221E1A`, line `#453E37`, cream `#EFE9E2`, magenta `#E74079`) with serif headlines and local system font stacks
- **OG image:** `og.png` (1200×630) generated with Pillow on each run

## API endpoints used (public, no key)

Base URL `https://api.taskmarket.dev`, for `chainId` 4217 and 8453:

- `/api/market/stats?chainId=…`
- `/api/stats/breakdowns?chainId=…`
- `/api/stats/platform-time-series?chainId=…&range=7d|30d|90d|all&bucket=day|week`
- `/api/stats/activity-heatmap?chainId=…&range=30d&dimension=mode|hourOfWeek`
- `/api/stats/activity-feed?chainId=…&limit=20`
- `/api/tasks?chainId=…&sort=newest&limit=100&cursor=…` (fully paginated)

Money values returned by the API are micro-units (6 decimals) and are displayed in dollars.

## Deploy

On the target server (root), from a clone of this repo:

```bash
./deploy.sh
```

That installs `generate.py` to `/opt/taskmarket-viz/`, creates an isolated venv for Pillow, generates the site into the web root's `taskmarket/` subdirectory, and installs the 15-minute cron entry. No nginx changes are needed for a static subdirectory.

To regenerate manually at any time:

```bash
/opt/taskmarket-viz/venv/bin/python3 /opt/taskmarket-viz/generate.py /opt/quizapp/www/taskmarket
```

## License

MIT — see `LICENSE`.
