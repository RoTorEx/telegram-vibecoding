"""Telegram-only process entrypoint and container readiness check."""

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from telegram_vibecoding import __version__
from telegram_vibecoding.config import Settings


def healthy(settings: Settings, instance_file=Path("/tmp/telegram-vibecoding-instance")) -> bool:
    try:
        with closing(sqlite3.connect((settings.data_dir / "bot.db").as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT value FROM meta WHERE key='bot_pid'").fetchone()
            instance = db.execute("SELECT value FROM meta WHERE key='bot_instance'").fetchone()
            heartbeat = db.execute("SELECT value FROM meta WHERE key='poll_heartbeat'").fetchone()
        if not row or not instance or instance[0] != instance_file.read_text().strip():
            return False
        if not heartbeat or not 0 <= time.time() - float(heartbeat[0]) <= 120:
            return False
        os.kill(int(row[0]), 0)
        return True
    except (OSError, ValueError, sqlite3.Error):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--health", action="store_true")
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument(
        "--auth-enroll",
        action="store_true",
        help="Print a one-use phone enrollment code; SSH only, never paste it in Telegram",
    )
    auth.add_argument("--auth-devices", action="store_true", help="List enrolled devices without secrets")
    auth.add_argument("--auth-revoke", metavar="DEVICE", help="Revoke a device and its unused approvals")
    args = parser.parse_args()
    os.umask(0o077)
    settings = Settings.load(args.config)
    if args.auth_enroll or args.auth_devices or args.auth_revoke:
        from telegram_vibecoding.confirmation import Confirmations
        from telegram_vibecoding.store import BotStore

        store = BotStore(settings.data_dir / "bot.db")
        try:
            confirmations = Confirmations(store)
            if args.auth_enroll:
                print(confirmations.enrollment())
            elif args.auth_devices:
                for device in store.rows("SELECT id,created,revoked FROM auth_devices ORDER BY created"):
                    print(device["id"], "revoked" if device["revoked"] else "enrolled")
            else:
                confirmations.revoke(args.auth_revoke)
                print("Device revoked")
        finally:
            store.close()
        return
    if args.health:
        if not healthy(settings):
            raise SystemExit(1)
        return
    from telegram_vibecoding.bot import run

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp").setLevel(logging.CRITICAL)
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print("Telegram process failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
