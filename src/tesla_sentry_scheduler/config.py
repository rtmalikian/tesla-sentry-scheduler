"""Configuration for Tesla Sentry Scheduler. All settings come from the
environment (see .env.example). Copy .env.example to .env — .env is
git-ignored so secrets never leave your machine."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time


class ConfigError(Exception):
    pass


@dataclass
class VehicleConfig:
    name: str
    vin: str


@dataclass
class Settings:
    client_id: str = ""
    client_secret: str = ""
    region: str = "na"
    redirect_uri: str = "http://localhost:8080/callback"
    token_file: str = "~/.tcc/tokens.json"
    vehicles: list[VehicleConfig] = field(default_factory=list)
    sentry_on: time = field(default_factory=lambda: time(22, 0))
    sentry_off: time = field(default_factory=lambda: time(6, 0))
    sentry_days: set[int] = field(default_factory=lambda: set(range(7)))  # 0=Mon
    state_file: str = "~/.tcc/sentry_scheduler_state.json"
    poll_interval_seconds: int = 900
    dry_run: bool = False


def _parse_vehicles(raw: str) -> list[VehicleConfig]:
    """Format: name=VIN,name2=VIN2 (or bare VINs)."""
    vehicles = []
    for idx, item in enumerate(raw.split(",")):
        item = item.strip()
        if not item:
            continue
        name = None
        if "=" in item:
            name, item = item.split("=", 1)
            name = name.strip()
        vin = item.strip()
        if not vin:
            raise ConfigError("Empty VIN in TCC_VEHICLES")
        vehicles.append(VehicleConfig(name=name or f"car-{idx + 1}", vin=vin))
    if not vehicles:
        raise ConfigError("TCC_VEHICLES is empty — add at least one name=VIN entry")
    return vehicles


def _float(env: dict, key: str, default: float | None) -> float | None:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


def _int(env: dict, key: str, default: int) -> int:
    try:
        return int(env.get(key, default))
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{key} must be an integer") from exc


def _bool(env: dict, key: str, default: bool) -> bool:
    return env.get(key, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


def _time(env: dict, key: str, default: time) -> time:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    parts = raw.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59) or len(parts) > 2:
            raise ValueError
        return time(hour, minute)
    except (ValueError, IndexError) as exc:
        raise ConfigError(f"{key} must be HH:MM (24h), got {raw!r}") from exc


_DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _days(env: dict, key: str, default: str) -> set[int]:
    raw = (env.get(key) or default).strip().lower()
    days: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item not in _DAY_NAMES:
            raise ConfigError(
                f"{key} has invalid day {item!r} — use mon,tue,wed,thu,fri,sat,sun")
        days.add(_DAY_NAMES[item])
    if not days:
        raise ConfigError(f"{key} must name at least one day")
    return days


def load_settings(env: dict | None = None, require_auth: bool = True) -> Settings:
    env = env if env is not None else os.environ

    client_id = env.get("TESLA_CLIENT_ID", "").strip()
    client_secret = env.get("TESLA_CLIENT_SECRET", "").strip()
    if require_auth and (not client_id or not client_secret):
        raise ConfigError("TESLA_CLIENT_ID and TESLA_CLIENT_SECRET are required (see README).")

    region = env.get("TESLA_REGION", "na").strip().lower()
    if region not in ("na", "eu", "cn"):
        raise ConfigError(f"TESLA_REGION must be na/eu/cn, got {region!r}")

    vehicles_raw = env.get("TCC_VEHICLES", "").strip()
    vehicles = _parse_vehicles(vehicles_raw) if (require_auth or vehicles_raw) else []

    sentry_on = _time(env, "TCC_SENTRY_ON", time(22, 0))
    sentry_off = _time(env, "TCC_SENTRY_OFF", time(6, 0))
    if sentry_on == sentry_off:
        raise ConfigError("TCC_SENTRY_ON and TCC_SENTRY_OFF must differ (empty window)")

    return Settings(
        client_id=client_id,
        client_secret=client_secret,
        region=region,
        redirect_uri=env.get("TESLA_REDIRECT_URI", "http://localhost:8080/callback").strip(),
        token_file=env.get("TESLA_TOKEN_FILE", "~/.tcc/tokens.json").strip(),
        vehicles=vehicles,
        sentry_on=sentry_on,
        sentry_off=sentry_off,
        sentry_days=_days(env, "TCC_SENTRY_DAYS", "mon,tue,wed,thu,fri,sat,sun"),
        state_file=env.get("TCC_STATE_FILE", "~/.tcc/sentry_scheduler_state.json").strip(),
        poll_interval_seconds=_int(env, "TCC_POLL_INTERVAL_SECONDS", 900),
        dry_run=_bool(env, "TCC_DRY_RUN", False),
    )
