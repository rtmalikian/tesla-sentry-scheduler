"""Decision logic: enforce the Sentry Mode schedule.

If parked and the current time is inside the ON window (e.g. 22:00-06:00)
and Sentry is off, arm it. If outside the ON window and Sentry is on,
disarm it. Everything else is left alone.

Pure logic — no network, `now` injected — so it is fully unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class VehicleSentryState:
    vin: str
    name: str
    parked: bool
    sentry_on: bool | None  # None = unknown (skip rather than guess)
    asleep: bool = False


@dataclass
class SetSentryMode:
    vin: str
    name: str
    on: bool
    reason: str


@dataclass
class Decision:
    actions: list = field(default_factory=list)
    note: str = ""


class SentryDecider:
    """Enforces the Sentry Mode schedule for the fleet."""

    def __init__(self, settings):
        self.s = settings
        self.last_action: dict[str, str] = {}  # vin -> ISO timestamp of last command

    # -- window ------------------------------------------------------------
    def in_window(self, now: datetime) -> bool:
        t = now.time()
        start, end = self.s.sentry_on, self.s.sentry_off
        if start <= end:
            return start <= t < end
        return t >= start or t < end  # overnight wrap (e.g. 22:00-06:00)

    def day_allowed(self, now: datetime) -> bool:
        return now.weekday() in self.s.sentry_days

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        return {"last_action": self.last_action}

    def from_dict(self, data: dict) -> None:
        self.last_action = dict(data.get("last_action", {}))

    # -- main --------------------------------------------------------------
    def decide(self, states: list[VehicleSentryState], now: datetime) -> Decision:
        actions: list = []
        notes: list[str] = []

        window = self.in_window(now) and self.day_allowed(now)

        for st in states:
            if st.asleep:
                notes.append(f"{st.name}: asleep — skipping (never wake to measure)")
                continue
            if not st.parked:
                notes.append(f"{st.name}: driving — leaving Sentry alone")
                continue
            if st.sentry_on is None:
                notes.append(f"{st.name}: Sentry state unknown — skipping")
                continue

            if window and not st.sentry_on:
                actions.append(SetSentryMode(
                    st.vin, st.name, True,
                    f"sentry window {self.s.sentry_on:%H:%M}-{self.s.sentry_off:%H:%M} "
                    f"started — arming",
                ))
                self.last_action[st.vin] = now.isoformat()
                notes.append(f"{st.name}: Sentry armed")
            elif not window and st.sentry_on:
                actions.append(SetSentryMode(
                    st.vin, st.name, False,
                    f"sentry window {self.s.sentry_on:%H:%M}-{self.s.sentry_off:%H:%M} "
                    f"ended — disarming",
                ))
                self.last_action[st.vin] = now.isoformat()
                notes.append(f"{st.name}: Sentry disarmed")

        return Decision(actions, note="; ".join(notes))
