"""Fake fleet for testing and demos. No API calls, no real cars."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class FakeVehicle:
    vin: str
    name: str
    sentry_on: bool = False
    parked: bool = True
    awake: bool = True
    # Scripted manual sentry toggles: list of (hour_offset_from_start, on).
    sentry_plan: list[tuple[float, bool]] = field(default_factory=list)


class FakeTeslaClient:
    """Stand-in for TeslaClient with the methods the scheduler uses."""

    def __init__(self, vehicles: list[FakeVehicle]):
        self.vehicles = {v.vin: v for v in vehicles}
        self.command_log = []
        self.data_calls = 0

    def read_if_awake(self, vin: str) -> dict | None:
        v = self.vehicles[vin]
        if not v.awake:
            return None
        self.data_calls += 1
        return {
            "state": "online",
            "vehicle_state": {"sentry_mode": v.sentry_on},
            "drive_state": {"shift_state": "P" if v.parked else "D"},
        }

    def set_sentry_mode(self, vin: str, on: bool) -> dict:
        self.vehicles[vin].sentry_on = on
        self.command_log.append(("set_sentry_mode", vin, on))
        return {"result": True}


def run_simulation(vehicles: list[FakeVehicle], decider, settings, start: datetime,
                   hours: float = 12.0, tick_minutes: float = 15.0) -> dict:
    """Drive the real scheduler against the fake fleet over virtual time."""
    from .scheduler import run_once

    client = FakeTeslaClient(vehicles)
    now = start
    end = start + timedelta(hours=hours)
    timeline: list[dict] = []
    while now < end:
        for v in vehicles:  # apply scripted manual toggles
            for offset_h, on in v.sentry_plan:
                if now >= start + timedelta(hours=offset_h):
                    v.sentry_on = on
        decision = run_once(client, decider, settings, now=now)
        timeline.append({
            "time": now.strftime("%H:%M"),
            "sentry": {v.name: v.sentry_on for v in vehicles},
            "note": decision.note,
            "actions": [(type(a).__name__, a.name, a.on) for a in decision.actions],
        })
        now += timedelta(minutes=tick_minutes)
    n_polls = len(timeline)
    # Cost estimate: data calls dominate (~$1 per 500), commands ~$1 per 1000,
    # wakes $0 (we never wake). Scale the sim to a full day at the app's real
    # poll interval (the sim ticks faster only for timeline resolution).
    polls_per_day = 86400 / settings.poll_interval_seconds
    day_data_calls = client.data_calls / max(n_polls, 1) * polls_per_day
    day_commands = len(client.command_log) / max(n_polls, 1) * polls_per_day
    est_monthly = (day_data_calls / 500 + day_commands / 1000) * 30
    return {"timeline": timeline, "commands": client.command_log,
            "data_calls": client.data_calls, "commands_day": day_commands,
            "est_monthly_usd": round(est_monthly, 2),
            "final_sentry": {v.name: v.sentry_on for v in vehicles}}
