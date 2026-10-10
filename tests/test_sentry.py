"""Decision-logic unit tests (no network, `now` injected)."""
from datetime import datetime, time

from tesla_sentry_scheduler.config import Settings, VehicleConfig
from tesla_sentry_scheduler.sentry import SentryDecider, SetSentryMode, VehicleSentryState


def make_settings(**over):
    kw = dict(
        vehicles=[VehicleConfig(name="Model Y", vin="VIN1")],
        sentry_on=time(22, 0), sentry_off=time(6, 0),
        sentry_days=set(range(7)),
        poll_interval_seconds=900,
    )
    kw.update(over)
    return Settings(**kw)


def state(**over):
    kw = dict(vin="VIN1", name="Model Y", parked=True, sentry_on=False)
    kw.update(over)
    return VehicleSentryState(**kw)


# A Monday 23:00 (inside the overnight window, day allowed).
MON_2300 = datetime(2026, 10, 12, 23, 0, 0)
# A Monday 21:59 (just before the window opens).
MON_2159 = datetime(2026, 10, 12, 21, 59, 0)
# A Tuesday 02:00 (inside the window, on the other side of midnight).
TUE_0200 = datetime(2026, 10, 13, 2, 0, 0)
# A Tuesday 06:00 (window boundary: end is exclusive).
TUE_0600 = datetime(2026, 10, 13, 6, 0, 0)
# A Tuesday 12:00 (outside the window).
TUE_1200 = datetime(2026, 10, 13, 12, 0, 0)


def test_arms_at_window_start():
    d = SentryDecider(make_settings())
    decision = d.decide([state(sentry_on=False)], MON_2300)
    assert len(decision.actions) == 1
    a = decision.actions[0]
    assert isinstance(a, SetSentryMode)
    assert a.on is True
    assert a.vin == "VIN1"


def test_disarms_at_window_end():
    d = SentryDecider(make_settings())
    decision = d.decide([state(sentry_on=True)], TUE_1200)
    assert len(decision.actions) == 1
    assert decision.actions[0].on is False


def test_no_action_when_already_correct():
    d = SentryDecider(make_settings())
    assert d.decide([state(sentry_on=True)], MON_2300).actions == []
    assert d.decide([state(sentry_on=False)], TUE_1200).actions == []


def test_no_double_command_across_polls():
    # Poll twice inside the window: the second poll sees sentry already on,
    # so no repeat command is issued (no flapping).
    d = SentryDecider(make_settings())
    first = d.decide([state(sentry_on=False)], MON_2300)
    assert len(first.actions) == 1
    second = d.decide([state(sentry_on=True)], datetime(2026, 10, 12, 23, 15, 0))
    assert second.actions == []


def test_overnight_wrap_window():
    d = SentryDecider(make_settings())
    assert d.in_window(MON_2300) is True
    assert d.in_window(TUE_0200) is True
    assert d.in_window(MON_2159) is False
    assert d.in_window(TUE_1200) is False


def test_window_boundaries():
    d = SentryDecider(make_settings())
    # Start is inclusive, end is exclusive.
    assert d.in_window(datetime(2026, 10, 12, 22, 0, 0)) is True
    assert d.in_window(TUE_0600) is False


def test_daytime_window_no_wrap():
    d = SentryDecider(make_settings(sentry_on=time(9, 0), sentry_off=time(17, 0)))
    assert d.in_window(datetime(2026, 10, 13, 9, 0, 0)) is True
    assert d.in_window(datetime(2026, 10, 13, 16, 59, 0)) is True
    assert d.in_window(datetime(2026, 10, 13, 17, 0, 0)) is False
    assert d.in_window(datetime(2026, 10, 13, 8, 59, 0)) is False
    assert d.in_window(datetime(2026, 10, 13, 23, 0, 0)) is False


def test_day_filter_weekdays_only():
    d = SentryDecider(make_settings(sentry_days={0, 1, 2, 3, 4}))  # mon-fri
    sat_2300 = datetime(2026, 10, 17, 23, 0, 0)  # Saturday
    assert sat_2300.weekday() == 5
    assert d.decide([state(sentry_on=False)], sat_2300).actions == []
    # Monday (weekday 0) in window: armed.
    assert len(d.decide([state(sentry_on=False)], MON_2300).actions) == 1


def test_day_filter_blocks_sunday_early_morning():
    # Sunday 02:00 is inside the 22:00-06:00 window, but Sunday is excluded:
    # the car stays disarmed.
    d = SentryDecider(make_settings(sentry_days={0, 1, 2, 3, 4}))
    sun_0200 = datetime(2026, 10, 18, 2, 0, 0)
    assert sun_0200.weekday() == 6
    assert d.decide([state(sentry_on=False)], sun_0200).actions == []


def test_no_action_while_driving():
    d = SentryDecider(make_settings())
    decision = d.decide([state(parked=False, sentry_on=False)], MON_2300)
    assert decision.actions == []
    assert "driving" in decision.note


def test_no_action_when_asleep():
    d = SentryDecider(make_settings())
    decision = d.decide([state(asleep=True, sentry_on=False)], MON_2300)
    assert decision.actions == []


def test_no_action_when_sentry_state_unknown():
    d = SentryDecider(make_settings())
    decision = d.decide([state(sentry_on=None)], MON_2300)
    assert decision.actions == []
    assert "unknown" in decision.note


def test_multi_vehicle_independent():
    d = SentryDecider(make_settings())
    states = [
        VehicleSentryState(vin="VIN1", name="Car1", parked=True, sentry_on=False),
        VehicleSentryState(vin="VIN2", name="Car2", parked=True, sentry_on=True),
    ]
    decision = d.decide(states, MON_2300)
    assert len(decision.actions) == 1
    assert decision.actions[0].vin == "VIN1"


def test_persistence_roundtrip():
    d = SentryDecider(make_settings())
    d.decide([state(sentry_on=False)], MON_2300)
    d2 = SentryDecider(make_settings())
    d2.from_dict(d.to_dict())
    assert d2.last_action["VIN1"] == MON_2300.isoformat()
