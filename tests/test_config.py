"""Config parsing tests."""
from datetime import time

import pytest

from tesla_sentry_scheduler.config import ConfigError, load_settings

BASE = {
    "TESLA_CLIENT_ID": "id",
    "TESLA_CLIENT_SECRET": "secret",
    "TCC_VEHICLES": "Daily=VIN1,Second=VIN2",
}


def test_vehicle_parsing():
    s = load_settings(dict(BASE))
    assert [(v.name, v.vin) for v in s.vehicles] == [("Daily", "VIN1"), ("Second", "VIN2")]


def test_schedule_defaults():
    s = load_settings(dict(BASE))
    assert s.sentry_on == time(22, 0)
    assert s.sentry_off == time(6, 0)
    assert s.sentry_days == set(range(7))
    assert s.poll_interval_seconds == 900


def test_schedule_overrides():
    s = load_settings({**BASE, "TCC_SENTRY_ON": "9:00", "TCC_SENTRY_OFF": "17:00",
                       "TCC_SENTRY_DAYS": "mon,tue,wed,thu,fri"})
    assert s.sentry_on == time(9, 0)
    assert s.sentry_off == time(17, 0)
    assert s.sentry_days == {0, 1, 2, 3, 4}


def test_time_accepts_minutes():
    s = load_settings({**BASE, "TCC_SENTRY_ON": "22:30"})
    assert s.sentry_on == time(22, 30)


def test_time_rejects_garbage():
    for bad in ("25:00", "9pm", "22:61", "abc", "22:00:00"):
        with pytest.raises(ConfigError):
            load_settings({**BASE, "TCC_SENTRY_ON": bad})


def test_equal_on_off_rejected():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TCC_SENTRY_ON": "22:00", "TCC_SENTRY_OFF": "22:00"})


def test_days_rejects_unknown_token():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TCC_SENTRY_DAYS": "mon,funday"})


def test_days_empty_means_default():
    s = load_settings({**BASE, "TCC_SENTRY_DAYS": ""})
    assert s.sentry_days == set(range(7))


def test_missing_vehicles_rejected():
    env = dict(BASE)
    del env["TCC_VEHICLES"]
    with pytest.raises(ConfigError):
        load_settings(env)


def test_simulate_needs_no_config():
    s = load_settings({}, require_auth=False)
    assert s.vehicles == []
    assert s.sentry_on == time(22, 0)
