# Tesla Sentry Scheduler — Put Sentry Mode on a Real Schedule for Your Tesla Model 3, Y, S, X & Cybertruck

**A free, open-source Tesla Fleet API app that arms and disarms your Tesla's Sentry Mode on a schedule — nights only, work hours only, your call.**

## Why?

Sentry Mode is Tesla's best anti-theft and hit-and-run camera system — and its biggest phantom drain culprit. Every owner knows the dilemma, in their own words:

- *"I forget to turn Sentry on at night, then something happens in my apartment parking lot."*
- *"Sentry Mode is killing my battery at work — 3% a day just sitting in the lot."*
- *"I want Sentry at home overnight but I don't want to babysit the toggle every single day."*
- *"My Model Y lost 8% overnight because I left Sentry on in a safe garage."*

Tesla gives you one toggle and no schedule. This gives you the schedule.

## How it works

You define a Sentry window (default 22:00–06:00) and the days it applies to. The scheduler checks your car's Sentry state and only issues a command when a transition is needed — one `set_sentry_mode` per window edge, never a flood of repeats:

```
21:45  parked at home, sentry OFF   -> outside window, no action
22:00  window opens                 -> set_sentry_mode(true)   "Sentry armed"
22:01  parked at home, sentry ON    -> no action
...
05:59  parked at home, sentry ON    -> no action
06:00  window closes                -> set_sentry_mode(false)  "Sentry disarmed"
06:01  parked at home, sentry OFF   -> no action
```

**Expected API cost:** ~$0.10–0.20/month per vehicle with the recommended setup (cron runs twice a day at your window edges). The 15-minute daemon mode costs ~$5–6/month — only use it if you need fast reaction. Either way, the car is **never woken just to check Sentry** (wakes are the priciest Fleet API call): if the car is asleep, the pass is skipped and retried later.

Safety rules baked in:

- **Never touches Sentry while you're driving** — it only acts when parked.
- **Never wakes a sleeping car** to check the state.
- **Unknown state = no action** — it skips rather than guesses.

## Quickstart

```bash
git clone https://github.com/rtmalikian/tesla-sentry-scheduler
cd tesla-sentry-scheduler
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in your credentials (see below)
# 1. See it work with zero credentials, zero network:
PYTHONPATH=src .venv/bin/python -m tesla_sentry_scheduler.cli simulate
# 2. Authorize + pair (one time each):
PYTHONPATH=src .venv/bin/python -m tesla_sentry_scheduler.cli auth
PYTHONPATH=src .venv/bin/python -m tesla_sentry_scheduler.cli pairing
# 3. Check the schedule against your car:
PYTHONPATH=src .venv/bin/python -m tesla_sentry_scheduler.cli status
# 4. Run once (dry-run first with TCC_DRY_RUN=true):
PYTHONPATH=src .venv/bin/python -m tesla_sentry_scheduler.cli run --once
```

Or install it: `pip install -e .` then use the `tcc-sentry` command directly.

**Recommended production setup:** two cron entries per vehicle pass — one at `TCC_SENTRY_ON`, one at `TCC_SENTRY_OFF` — each running `tcc-sentry run --once`. That is the cheapest and most reliable mode. The daemon (`tcc-sentry run`) is there if you prefer a single long-running process.

## Tesla developer setup

1. Create an app at [developer.tesla.com](https://developer.tesla.com) and copy your client ID/secret into `.env`.
2. Required scopes: `openid offline_access vehicle_device_data vehicle_location vehicle_cmds vehicle_charging_cmds`.
3. Run `tcc-sentry pairing` and follow the one-time virtual-key steps (host your public key, approve it on the car's touchscreen at `tesla.com/_ak/<your-domain>`).

## `.env` reference

| Variable | Default | What it does |
|---|---|---|
| `TESLA_CLIENT_ID` / `TESLA_CLIENT_SECRET` | — | Your developer app credentials |
| `TESLA_REGION` | `na` | `na` / `eu` / `cn` |
| `TESLA_REDIRECT_URI` | `http://localhost:8080/callback` | OAuth callback |
| `TESLA_TOKEN_FILE` | `~/.tcc/tokens.json` | OAuth tokens (created mode 600) |
| `TCC_VEHICLES` | — | `name=VIN,name2=VIN2` — one per car |
| `TCC_SENTRY_ON` | `22:00` | Window start (HH:MM, 24h) |
| `TCC_SENTRY_OFF` | `06:00` | Window end (HH:MM, 24h); may be before start for overnight windows |
| `TCC_SENTRY_DAYS` | all days | e.g. `mon,tue,wed,thu,fri` for weekdays only |
| `TCC_STATE_FILE` | `~/.tcc/sentry_scheduler_state.json` | Decider state across runs |
| `TCC_POLL_INTERVAL_SECONDS` | `900` | Daemon loop interval only |
| `TCC_DRY_RUN` | `false` | Log what would happen, send nothing |

## FAQ

**Does this reduce phantom drain?**
Yes — that's the point. Sentry Mode is one of the largest phantom-drain sources (commonly 1–3% of battery per day). Limiting it to the hours you actually need it (e.g. overnight in an exposed lot) cuts the rest.

**Will it fight me if I toggle Sentry manually in the app?**
Yes, by design: the schedule wins. If you turn Sentry off at 23:00 and the window is 22:00–06:00, the next pass re-arms it. The scheduler treats the window as the source of truth.

**What if my car is asleep at 22:00 when the window opens?**
The pass is skipped (no wake — wakes are the expensive call) and retried on the next poll. With the 15-minute daemon you'll be armed within minutes of the car being reachable; with cron mode, consider adding a follow-up run 30 minutes after the window edge.

**Can I use this for daytime-only coverage, like work hours?**
Yes: set `TCC_SENTRY_ON=09:00` and `TCC_SENTRY_OFF=17:00`. Windows don't have to wrap overnight.

**Does it work with multiple Teslas?**
Yes — list them all in `TCC_VEHICLES`. Each car is scheduled independently.

**Is my Tesla login safe?**
OAuth tokens are stored only on your machine (`~/.tcc/tokens.json`, mode 600). `.env` is git-ignored. The code is fully open source — read every line before you run it.

---

Built by Raphael Malikian. MIT licensed. Part of a daily series of free, open-source Tesla Fleet API apps — see also [tesla-calendar-climate](https://github.com/rtmalikian/tesla-calendar-climate) and [tesla-charge-limit-coach](https://github.com/rtmalikian/tesla-charge-limit-coach).
