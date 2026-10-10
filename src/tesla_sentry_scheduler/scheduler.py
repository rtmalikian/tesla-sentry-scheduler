"""Run loop: read vehicle state, decide, execute.

Cost discipline: the scheduler NEVER wakes the car just to check Sentry
(wakes are the priciest Fleet API call). If the car is asleep, the pass is
skipped and retried on the next poll.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from .config import Settings
from .sentry import Decision, SentryDecider, SetSentryMode, VehicleSentryState
from .tesla_client import TeslaApiError, TeslaClient

log = logging.getLogger("tcc-sentry")


def build_states(client, settings: Settings) -> list[VehicleSentryState]:
    states = []
    for vc in settings.vehicles:
        data = client.read_if_awake(vc.vin)
        if data is None:
            log.info("%s: asleep or unreachable — skipping (no wake)", vc.name)
            continue
        vehicle = data.get("vehicle_state", {}) or {}
        drive = data.get("drive_state", {}) or {}
        shift = drive.get("shift_state")
        parked = shift in ("P", None)
        states.append(VehicleSentryState(
            vin=vc.vin,
            name=vc.name,
            parked=parked,
            sentry_on=bool(vehicle.get("sentry_mode")) if vehicle.get("sentry_mode") is not None else None,
        ))
    return states


def load_decider(settings: Settings) -> SentryDecider:
    decider = SentryDecider(settings)
    path = Path(settings.state_file).expanduser()
    if path.exists():
        try:
            decider.from_dict(json.loads(path.read_text()))
        except Exception as exc:
            log.warning("Could not load state file: %s", exc)
    return decider


def save_decider(decider: SentryDecider, settings: Settings) -> None:
    path = Path(settings.state_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decider.to_dict(), indent=2))


def execute(client, settings: Settings, decision: Decision) -> None:
    for action in decision.actions:
        if isinstance(action, SetSentryMode):
            verb = "ON " if action.on else "OFF"
            log.info("SENTRY %s  %s (%s)", verb, action.name, action.reason)
            if not settings.dry_run:
                try:
                    client.set_sentry_mode(action.vin, action.on)
                except TeslaApiError as exc:
                    log.warning("set_sentry_mode failed for %s: %s", action.name, exc)
    if decision.note:
        log.info("note: %s", decision.note)


def run_once(client, decider: SentryDecider, settings: Settings,
             now: datetime | None = None) -> Decision:
    """Single sense-decide-act pass."""
    now = now or datetime.now().astimezone()
    states = build_states(client, settings)
    for s in states:
        log.info("%-12s sentry=%s parked=%s",
                 s.name, "on" if s.sentry_on else "off", s.parked)
    decision = decider.decide(states, now)
    execute(client, settings, decision)
    save_decider(decider, settings)
    return decision


def run_loop(settings: Settings) -> None:
    client = TeslaClient(
        client_id=settings.client_id, client_secret=settings.client_secret,
        region=settings.region, redirect_uri=settings.redirect_uri,
        token_file=settings.token_file,
    )
    decider = load_decider(settings)
    mode = "DRY-RUN" if settings.dry_run else "LIVE"
    log.info("Tesla Sentry Scheduler starting (%s), poll every %ds",
             mode, settings.poll_interval_seconds)
    while True:
        try:
            run_once(client, decider, settings)
        except TeslaApiError as exc:
            log.error("Fleet API error: %s", exc)
        except Exception:
            log.exception("Unexpected error in run loop")
        time.sleep(settings.poll_interval_seconds)
