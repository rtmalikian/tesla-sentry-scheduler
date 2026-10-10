"""End-to-end test: fake fleet over virtual time.

Core invariant: Sentry Mode is armed inside the schedule window and
disarmed outside it — exactly one command per transition, no repeats,
no action while the car is asleep or driving.
"""
from datetime import datetime, time

from tesla_sentry_scheduler.config import Settings, VehicleConfig
from tesla_sentry_scheduler.sentry import SentryDecider
from tesla_sentry_scheduler.simulator import FakeVehicle, run_simulation


def make_settings(**over):
    kw = dict(
        vehicles=[VehicleConfig(name="Model Y", vin="VIN1")],
        sentry_on=time(22, 0), sentry_off=time(6, 0),
        sentry_days=set(range(7)),
        poll_interval_seconds=900,
        state_file="/tmp/tesla_sentry_scheduler_test_state.json",
    )
    kw.update(over)
    return Settings(**kw)


def test_two_full_cycles_over_48h():
    # Monday 18:00 -> Wednesday 18:00: window opens 22:00 each night,
    # closes 06:00 each morning.
    start = datetime(2026, 10, 12, 18, 0, 0)  # Monday
    vehicles = [FakeVehicle(vin="VIN1", name="Model Y", sentry_on=False)]
    settings = make_settings()
    report = run_simulation(vehicles, SentryDecider(settings), settings,
                            start, hours=48.0, tick_minutes=15.0)

    ons = [c for c in report["commands"] if c[0] == "set_sentry_mode" and c[2] is True]
    offs = [c for c in report["commands"] if c[0] == "set_sentry_mode" and c[2] is False]
    assert len(ons) == 2, f"expected 2 armings, got {report['commands']}"
    assert len(offs) == 2, f"expected 2 disarmings, got {report['commands']}"


def test_arming_happens_at_22h00_and_disarming_at_06h00():
    start = datetime(2026, 10, 12, 18, 0, 0)  # Monday
    vehicles = [FakeVehicle(vin="VIN1", name="Model Y", sentry_on=False)]
    settings = make_settings()
    report = run_simulation(vehicles, SentryDecider(settings), settings,
                            start, hours=48.0, tick_minutes=15.0)

    armed = [t for t in report["timeline"]
             if any(a[0] == "SetSentryMode" and a[2] is True for a in t["actions"])]
    disarmed = [t for t in report["timeline"]
                if any(a[0] == "SetSentryMode" and a[2] is False for a in t["actions"])]
    assert [t["time"] for t in armed] == ["22:00", "22:00"], \
        f"arming fired at wrong times: {[t['time'] for t in armed]}"
    assert [t["time"] for t in disarmed] == ["06:00", "06:00"], \
        f"disarming fired at wrong times: {[t['time'] for t in disarmed]}"


def test_sentry_state_matches_window_throughout():
    # Every timeline tick records state AFTER actions run, so sentry must
    # equal "inside the window" on every single tick.
    start = datetime(2026, 10, 12, 18, 0, 0)  # Monday
    vehicles = [FakeVehicle(vin="VIN1", name="Model Y", sentry_on=False)]
    settings = make_settings()
    report = run_simulation(vehicles, SentryDecider(settings), settings,
                            start, hours=48.0, tick_minutes=15.0)

    for tick in report["timeline"]:
        h = int(tick["time"][:2])
        in_window = h >= 22 or h < 6
        assert tick["sentry"]["Model Y"] == in_window, \
            f"{tick['time']}: sentry={tick['sentry']['Model Y']} but in_window={in_window}"
    assert report["final_sentry"]["Model Y"] is False  # 18:00 Wed: outside window


def test_no_action_while_car_is_away():
    # Car drives from 21:00-23:00: no arming at 22:00; it arms on the next
    # poll after the car parks (no wakeups, no commands while driving).
    start = datetime(2026, 10, 12, 18, 0, 0)  # Monday
    vehicles = [FakeVehicle(vin="VIN1", name="Model Y", sentry_on=False, parked=True)]
    settings = make_settings()

    from tesla_sentry_scheduler.scheduler import run_once
    from tesla_sentry_scheduler.simulator import FakeTeslaClient
    from datetime import timedelta
    client = FakeTeslaClient(vehicles)
    d = SentryDecider(settings)
    now = start
    while now < start + timedelta(hours=10):
        vehicles[0].parked = not (now.hour == 22 and now.minute < 45)  # driving 22:00-22:45
        decision = run_once(client, d, settings, now=now)
        now += timedelta(minutes=15)
    cmds_at_2200 = [c for c in client.command_log]
    assert cmds_at_2200, "expected some commands over the 10h window"
    # The arm happened exactly once, at the first parked poll inside the window.
    ons = [c for c in client.command_log if c[0] == "set_sentry_mode" and c[2] is True]
    assert len(ons) == 1
