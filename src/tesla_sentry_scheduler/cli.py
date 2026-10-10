"""CLI: tcc-sentry auth | status | run | once | simulate | pairing"""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from datetime import datetime, time

from dotenv import load_dotenv

from . import __version__
from .config import ConfigError, Settings, VehicleConfig, load_settings
from .scheduler import build_states, load_decider, run_loop, run_once
from .sentry import SentryDecider
from .simulator import FakeVehicle, run_simulation
from .tesla_client import TeslaApiError, TeslaClient

log = logging.getLogger("tcc-sentry")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")


def _client(settings: Settings) -> TeslaClient:
    return TeslaClient(client_id=settings.client_id, client_secret=settings.client_secret,
                       region=settings.region, redirect_uri=settings.redirect_uri,
                       token_file=settings.token_file)


def cmd_auth(args, settings: Settings) -> int:
    client = _client(settings)
    url = client.authorize_url()
    print("1. Open this URL and sign in with your Tesla account:\n\n   %s\n" % url)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print("2. After sign-in you'll land on a localhost URL that fails to load.")
    print("   Paste that FULL redirected URL here (it contains ?code=...).")
    redirected = input("Redirected URL: ").strip()
    if "code=" not in redirected:
        print("ERROR: no ?code= found.", file=sys.stderr)
        return 1
    try:
        client.exchange_code(redirected.split("code=")[1].split("&")[0])
    except TeslaApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"\nAuthorized! Tokens saved to {settings.token_file} (mode 600).")
    print("Next: run `tcc-sentry pairing` for the one-time virtual-key setup.")
    return 0


def cmd_pairing(_args, _settings: Settings) -> int:
    print(
        "One-time virtual-key setup (required before commands work):\n\n"
        "  1. Host your app's public key at\n"
        "     https://<your-domain>/.well-known/appspecific/com.tesla.3p.public-key.pem\n"
        "  2. Register it: POST /api/1/partner_accounts {\"domain\": \"<your-domain>\"}\n"
        "  3. In EACH Tesla, open https://www.tesla.com/_ak/<your-domain>\n"
        "     and approve the key on the touchscreen.\n"
    )
    return 0


def cmd_status(_args, settings: Settings) -> int:
    client = _client(settings)
    states = build_states(client, settings)
    decider = SentryDecider(settings)
    now = datetime.now().astimezone()
    print(f"Sentry window: {settings.sentry_on:%H:%M}-{settings.sentry_off:%H:%M}, "
          f"days: {','.join(_DAY_ABBR[d] for d in sorted(settings.sentry_days))}")
    print(f"Now: {now:%a %H:%M} — in window: {decider.in_window(now) and decider.day_allowed(now)}")
    print(f"\n{'Vehicle':<12}{'Sentry':<8}{'Parked':<8}")
    print("-" * 28)
    for s in states:
        print(f"{s.name:<12}{'on' if s.sentry_on else 'off':<8}{str(s.parked):<8}")
    return 0


_DAY_ABBR = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def cmd_run(args, settings: Settings) -> int:
    if args.once:
        run_once(_client(settings), load_decider(settings), settings)
        return 0
    run_loop(settings)
    return 0


def cmd_simulate(_args, _settings: Settings) -> int:
    """48h demo: 22:00-06:00 window; car parked the whole time, sentry starts off."""
    start = datetime.now().astimezone().replace(hour=18, minute=0, second=0, microsecond=0)
    vehicles = [FakeVehicle(vin="SIM1", name="Model Y")]
    settings = Settings(
        vehicles=[VehicleConfig(name="Model Y", vin="SIM1")],
        sentry_on=time(22, 0), sentry_off=time(6, 0),
        poll_interval_seconds=900,
    )
    decider = SentryDecider(settings)
    report = run_simulation(vehicles, decider, settings, start, hours=48.0)

    print("\nSimulating 48h with a 22:00-06:00 Sentry window (car parked, sentry starts off)\n")
    print(f"{'Time':<8}{'Sentry':<8}Note")
    print("-" * 60)
    last = None
    for tick in report["timeline"]:
        key = (tick["sentry"]["Model Y"], tick["note"])
        if key != last:
            print(f"{tick['time']:<8}{str(tick['sentry']['Model Y']):<8}{tick['note']}")
            last = key
    ons = [c for c in report["commands"] if c[0] == "set_sentry_mode" and c[2] is True]
    offs = [c for c in report["commands"] if c[0] == "set_sentry_mode" and c[2] is False]
    ok = len(ons) == 2 and len(offs) == 2
    print(f"\nSentry armed at 22:00: {'yes' if len(ons) >= 1 else 'NO'}")
    print(f"Sentry disarmed at 06:00: {'yes' if len(offs) >= 1 else 'NO'}")
    print(f"Exactly 2 on / 2 off over 48h, no repeats: {'PASS' if ok else 'FAIL — bug!'}")
    print(f"Est. Fleet API cost (15-min daemon): ~${report['est_monthly_usd']}/month")
    print("Est. Fleet API cost (recommended: cron twice daily at window edges): ~$0.10-0.20/month")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tcc-sentry",
                                description="Put your Tesla's Sentry Mode on a schedule.")
    p.add_argument("--version", action="version", version=f"tcc-sentry {__version__}")
    p.add_argument("--env-file", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("auth", help="Authorize with your Tesla account (one-time)")
    sub.add_parser("pairing", help="Virtual-key pairing instructions")
    sub.add_parser("status", help="Show Sentry state + schedule")
    run_p = sub.add_parser("run", help="Run the Sentry loop (daemon)")
    run_p.add_argument("--once", action="store_true", help="Single pass, then exit")
    sub.add_parser("simulate", help="Demo against a fake fleet (no API calls)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    load_dotenv(args.env_file)
    try:
        settings = load_settings(require_auth=args.command in ("auth", "status", "run"))
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    return {
        "auth": cmd_auth, "pairing": cmd_pairing, "status": cmd_status,
        "run": cmd_run, "simulate": cmd_simulate,
    }[args.command](args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
