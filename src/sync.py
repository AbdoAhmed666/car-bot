"""On the shop PC: refresh the snapshot and send it to the server.

    python -m src.sync

Windows' Task Scheduler runs it at logon and every 30 minutes
(tools/install_sync.ps1), without a window. When ELYASSER is closed there is
nothing to read: it logs that and tries again next time. The log is data/sync.log.
"""
import gzip
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

import requests

from . import config
from .export import ExportError, export

log = logging.getLogger("car-bot.sync")


def upload(cfg, path=None) -> dict:
    """Send the snapshot to the server's /upload; returns the server's answer."""
    body = gzip.compress((path or cfg.snapshot_path).read_bytes())
    response = requests.post(f"{cfg.server_url.rstrip('/')}/upload", data=body, timeout=120,
                             headers={"Authorization": f"Bearer {cfg.upload_token}",
                                      "Content-Type": "application/octet-stream"})
    response.raise_for_status()
    return response.json()


def run(cfg, tries=3, wait=30) -> int:
    try:
        counts = export(cfg)
    except ExportError as e:
        log.warning("nothing to read (%s): trying again next time", e)
        return 0
    log.info("exported: %s", ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    if not cfg.server_url:
        log.info("no SERVER_URL in .env: kept the snapshot here")
        return 0
    for attempt in range(1, tries + 1):
        try:
            answer = upload(cfg)
            log.info("sent: %s", answer)
            return 0
        except requests.RequestException as e:
            log.warning("send failed (try %d of %d): %s", attempt, tries, e)
            if attempt < tries:
                time.sleep(wait * attempt)
    return 1


def main() -> int:
    # started by the Task Scheduler with pythonw there is no console: anything
    # printed would fail, so send it nowhere and keep only the log file
    windowless = sys.stdout is None or sys.stderr is None
    if windowless:
        sys.stdout = sys.stderr = open(os.devnull, "w")
    cfg = config.load()
    cfg.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    handlers = [RotatingFileHandler(cfg.snapshot_path.parent / "sync.log", maxBytes=1_000_000, backupCount=3,
                                    encoding="utf-8")]
    if not windowless:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO, handlers=handlers)
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
