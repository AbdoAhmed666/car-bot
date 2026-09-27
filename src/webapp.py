"""The bot on a web host that is always up (PythonAnywhere's free plan).

    POST /telegram   Telegram delivers each message here (webhook, see src/webhook.py)
    POST /upload     the shop PC sends a fresh snapshot here (src/sync.py)
    GET  /tick       a free pinger (cron-job.org) opens this every 15 minutes

The answers come from src/chat.py, the same as the laptop bot. Each of the
three also sends the scheduled reports that are due (src/push.py): the free
plan has no scheduled tasks. /tick needs no secret: all it can do is send a
report that is due and not sent yet, which is what the pinger is for.

On PythonAnywhere the WSGI file only needs:
    from src.webapp import create_app
    application = create_app()
"""
import gzip
import hmac
import logging
import os
import sqlite3
from pathlib import Path

from flask import Flask, abort, jsonify, request

from . import config
from .chat import Chat
from .push import run_due
from .reports import Reports
from .shop import Shop
from .state import State
from .telegram_api import Telegram

log = logging.getLogger("car-bot")
MAX_UPLOAD = 60 * 1024 * 1024
NEEDED_TABLES = {"meta", "items", "invoices", "invoice_lines", "customers"}


def valid_snapshot(path) -> bool:
    try:
        db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            stamp = db.execute("SELECT value FROM meta WHERE key = 'exported_at'").fetchone() \
                if "meta" in tables else None
        finally:
            db.close()
    except sqlite3.Error:
        return False
    return NEEDED_TABLES <= tables and stamp is not None


def create_app(cfg=None, telegram=None) -> Flask:
    cfg = cfg or config.load()
    tg = telegram or Telegram(cfg.telegram_token)
    state = State(cfg.state_path)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD

    def chat():
        return Chat(Reports(Shop(cfg), cfg, state, cfg.as_of), cfg)

    def send_due() -> list:
        try:
            return run_due(cfg, Reports(Shop(cfg), cfg, state, cfg.as_of), state, tg)
        except Exception:               # never let a report break an answer or an upload
            log.exception("error while sending the scheduled reports")
            return []

    @app.get("/")
    def health():
        return "car-bot is up"

    @app.route("/tick", methods=["GET", "POST"])
    def tick():
        return jsonify(sent=send_due())

    @app.post("/telegram")
    def telegram_update():
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not cfg.webhook_secret or not hmac.compare_digest(secret, cfg.webhook_secret):
            abort(403)
        try:
            handle(request.get_json(silent=True) or {})
        except Exception:               # answer 200 anyway, or Telegram resends the same update forever
            log.exception("error while handling an update")
        send_due()
        return "ok"

    def handle(update):
        c = chat()
        if "message" in update:
            message = update["message"]
            if message.get("text") is None:
                return
            for out in c.on_text(message["from"]["id"], message["text"]):
                tg.send(message["chat"]["id"], out)
        elif "callback_query" in update:
            query = update["callback_query"]
            tg.answer(query["id"])
            message = query.get("message") or {}
            chat_id = message.get("chat", {}).get("id", query["from"]["id"])
            for out in c.on_button(query["from"]["id"], query.get("data")):
                if out.edit and message and len(out.text) <= 4000:
                    tg.edit(chat_id, message["message_id"], out)
                else:
                    tg.send(chat_id, out)

    @app.post("/upload")
    def upload():
        auth = request.headers.get("Authorization", "")
        if not cfg.upload_token or not hmac.compare_digest(auth, f"Bearer {cfg.upload_token}"):
            abort(401)
        try:
            data = gzip.decompress(request.get_data(cache=False))
        except (OSError, EOFError):
            abort(400)
        target = Path(cfg.snapshot_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        incoming = target.with_name(target.name + ".upload")
        incoming.write_bytes(data)
        if not valid_snapshot(incoming):
            incoming.unlink(missing_ok=True)
            abort(400)
        os.replace(incoming, target)
        return jsonify(ok=True, exported_at=str(Shop(cfg).exported_at()), sent=send_due())

    return app
