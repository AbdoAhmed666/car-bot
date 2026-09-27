"""The always-on side: webhook, snapshot upload, reports sent when due, and the shop PC's sync."""
import gzip
from dataclasses import replace
from datetime import datetime

import pytest

from src import push, sync, webapp
from src.shop import Shop


class FakeTelegram:
    def __init__(self):
        self.sent, self.edits, self.answered = [], [], []

    def send(self, chat_id, out):
        self.sent.append((chat_id, out.text, out.buttons))

    def edit(self, chat_id, message_id, out):
        self.edits.append((chat_id, message_id, out.text, out.buttons))

    def answer(self, callback_id):
        self.answered.append(callback_id)

    def broadcast(self, user_ids, out):
        for user_id in sorted(user_ids):
            self.send(user_id, out)


@pytest.fixture
def server_cfg(shop_cfg, tmp_path):
    return replace(shop_cfg, snapshot_path=tmp_path / "server" / "snapshot.db", state_path=tmp_path / "server" / "state.db",
                   upload_token="up-secret", webhook_secret="hook-secret", as_of=datetime(2026, 9, 26, 17, 0))


def client(cfg):
    tg = FakeTelegram()
    return webapp.create_app(cfg, telegram=tg).test_client(), tg


def upload(c, body, token="up-secret"):
    return c.post("/upload", data=body, headers={"Authorization": f"Bearer {token}"})


# --- /upload ---------------------------------------------------------------------

def test_upload_needs_the_token(server_cfg, fake_snapshot):
    c, _ = client(server_cfg)
    body = gzip.compress(fake_snapshot.read_bytes())
    assert c.post("/upload", data=body).status_code == 401
    assert upload(c, body, token="wrong").status_code == 401
    assert not server_cfg.snapshot_path.exists()


def test_upload_rejects_what_is_not_a_snapshot(server_cfg):
    c, _ = client(server_cfg)
    assert upload(c, b"not gzip").status_code == 400
    assert upload(c, gzip.compress(b"not a database")).status_code == 400
    assert not server_cfg.snapshot_path.exists()


def test_upload_replaces_the_snapshot_and_sends_the_daily_update_once(server_cfg, fake_snapshot):
    c, tg = client(server_cfg)
    body = gzip.compress(fake_snapshot.read_bytes())
    first = upload(c, body)
    assert first.status_code == 200 and first.json["sent"] == ["daily"]
    assert Shop(server_cfg).check()["invoices"] > 1000
    assert [(to, text.splitlines()[0]) for to, text, _ in tg.sent] == [(111, "📊 تحديث العصر · السبت 26/9 (من أول اليوم)")]
    assert upload(c, body).json["sent"] == []                   # already sent today
    assert len(tg.sent) == 1


def test_no_daily_update_before_its_time(server_cfg, fake_snapshot):
    c, tg = client(replace(server_cfg, as_of=datetime(2026, 9, 26, 12, 0)))
    assert upload(c, gzip.compress(fake_snapshot.read_bytes())).json["sent"] == []
    assert tg.sent == []


# --- /telegram ------------------------------------------------------------------

def message(user, text):
    return {"message": {"message_id": 5, "from": {"id": user}, "chat": {"id": user}, "text": text}}


def test_webhook_needs_the_secret(server_cfg):
    c, tg = client(server_cfg)
    assert c.post("/telegram", json=message(111, "hi")).status_code == 403
    assert c.post("/telegram", json=message(111, "hi"),
                  headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}).status_code == 403
    assert tg.sent == []


def test_webhook_answers(server_cfg, fake_snapshot):
    c, tg = client(server_cfg)
    upload(c, gzip.compress(fake_snapshot.read_bytes()))
    tg.sent.clear()
    headers = {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"}
    assert c.post("/telegram", json=message(111, "كويل لانوس"), headers=headers).status_code == 200
    assert tg.sent[-1][1].startswith("📦 كويل لانوس")
    c.post("/telegram", json=message(999, "كويل لانوس"), headers=headers)
    assert "999" in tg.sent[-1][1] and "خاص" in tg.sent[-1][1]
    press = {"callback_query": {"id": "cb1", "from": {"id": 111}, "data": "list:idle:0",
                                "message": {"message_id": 42, "chat": {"id": 111}}}}
    c.post("/telegram", json=press, headers=headers)
    assert tg.answered == ["cb1"] and tg.edits[-1][:2] == (111, 42) and tg.edits[-1][2].startswith("💤 الراكد")


def test_webhook_survives_errors(server_cfg):
    c, tg = client(server_cfg)                                  # no snapshot yet
    headers = {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"}
    assert c.post("/telegram", json=message(111, "كويل"), headers=headers).status_code == 200
    assert tg.sent[-1][1] == "مفيش داتا من البرنامج لسه. لما جهاز المحل يبعت أول تحديث هقدر أرد."
    assert c.post("/telegram", json={"weird": 1}, headers=headers).status_code == 200


# --- reports sent when due ------------------------------------------------------------
# the fake snapshot came from the shop PC on Saturday 26/9 at 18:00; WEEKLY_DAY is Thursday

@pytest.mark.parametrize("now, jobs", [
    (datetime(2026, 9, 26, 12, 0), []),                                     # too early
    (datetime(2026, 9, 26, 17, 0), [("daily", "2026-09-26")]),
    (datetime(2026, 9, 26, 23, 40), [("daily", "2026-09-26"), ("eod", "2026-09-26")]),
    (datetime(2026, 9, 27, 0, 30), [("eod", "2026-09-26")]),                # past midnight: still Saturday
    (datetime(2026, 9, 27, 17, 0), []),                                     # nothing came from the shop today
    (datetime(2026, 9, 27, 23, 45), []),                                    # ... so no end of day either
    (datetime(2026, 9, 24, 23, 30), [("eod", "2026-09-24"), ("weekly", "2026-09-24")]),   # Thursday
    (datetime(2026, 10, 1, 23, 45), [("weekly", "2026-10-01")]),           # Thursday, shop PC off all day
])
def test_what_is_due(shop_cfg, now, jobs):
    from src.reports import Reports
    from src.state import State
    reports = Reports(Shop(shop_cfg), shop_cfg, State(shop_cfg.state_path), as_of=now)
    assert push.due(shop_cfg, reports, reports.state) == jobs


def test_end_of_day_after_midnight(shop_cfg):
    from datetime import time
    from src.reports import Reports
    from src.state import State
    cfg = replace(shop_cfg, end_of_day=time(0, 30))             # the shop closes after midnight
    before = Reports(Shop(cfg), cfg, State(cfg.state_path), as_of=datetime(2026, 9, 26, 23, 50))
    assert push.due(cfg, before, before.state) == [("daily", "2026-09-26")]
    after = Reports(Shop(cfg), cfg, State(cfg.state_path), as_of=datetime(2026, 9, 27, 0, 40))
    assert push.due(cfg, after, after.state) == [("eod", "2026-09-26")]


def test_each_report_goes_once_to_everyone(shop_cfg):
    from src.reports import Reports
    from src.state import State
    tg = FakeTelegram()
    cfg = replace(shop_cfg, allowed_users=frozenset({111, 222}))
    state = State(cfg.state_path)
    reports = Reports(Shop(cfg), cfg, state, as_of=datetime(2026, 9, 24, 23, 30))
    assert push.run_due(cfg, reports, state, tg) == ["eod", "weekly"]
    assert [(to, text.split(" · ")[0]) for to, text, _ in tg.sent] == [
        (111, "🌙 آخر اليوم"), (222, "🌙 آخر اليوم"), (111, "📅 الأسبوع"), (222, "📅 الأسبوع")]
    assert push.run_due(cfg, reports, state, tg) == [] and len(tg.sent) == 4


def test_tick(server_cfg, fake_snapshot):
    c, tg = client(replace(server_cfg, as_of=datetime(2026, 9, 26, 23, 40)))
    assert c.get("/tick").json == {"sent": []}                  # no snapshot yet: nothing to say
    server_cfg.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    server_cfg.snapshot_path.write_bytes(fake_snapshot.read_bytes())
    assert c.get("/tick").json == {"sent": ["daily", "eod"]}
    assert c.get("/tick").json == {"sent": []}
    assert [text.split(" · ")[0] for _, text, _ in tg.sent] == ["📊 تحديث العصر", "🌙 آخر اليوم"]


def test_a_message_also_sends_what_is_due(server_cfg, fake_snapshot):
    c, tg = client(replace(server_cfg, as_of=datetime(2026, 9, 27, 0, 30)))
    server_cfg.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    server_cfg.snapshot_path.write_bytes(fake_snapshot.read_bytes())
    c.post("/telegram", json=message(111, "كويل لانوس"), headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})
    assert tg.sent[0][1].startswith("📦 كويل لانوس") and tg.sent[1][1].startswith("🌙 آخر اليوم")


def test_push_by_hand(shop_cfg, monkeypatch, capsys):
    tg = FakeTelegram()
    cfg = replace(shop_cfg, as_of=datetime(2026, 9, 26, 12, 0))
    monkeypatch.setattr(push.config, "load", lambda: cfg)
    monkeypatch.setattr(push, "Telegram", lambda token: tg)
    assert push.main([]) == 0 and "nothing due" in capsys.readouterr().out
    assert push.main(["weekly"]) == 0 and tg.sent[0][1].startswith("📅 الأسبوع")
    assert push.main(["nightly"]) == 2


# --- the shop PC's sync ------------------------------------------------------------

def test_sync_sends_the_snapshot_to_the_server(server_cfg, shop_cfg, fake_snapshot, tmp_path, monkeypatch):
    c, _ = client(server_cfg)
    shop_side = replace(shop_cfg, snapshot_path=tmp_path / "shop" / "snapshot.db", server_url="https://srv",
                        upload_token="up-secret")

    def fake_export(cfg):
        cfg.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.snapshot_path.write_bytes(fake_snapshot.read_bytes())
        return {"items": 36}

    class Response:
        def __init__(self, r):
            self.r = r

        def raise_for_status(self):
            if self.r.status_code >= 400:
                raise sync.requests.HTTPError(str(self.r.status_code))

        def json(self):
            return self.r.json

    def post(url, data, headers, timeout):
        assert url == "https://srv/upload"
        return Response(c.post("/upload", data=data, headers=headers))

    monkeypatch.setattr(sync, "export", fake_export)
    monkeypatch.setattr(sync.requests, "post", post)
    assert sync.run(shop_side) == 0
    assert Shop(server_cfg).check()["invoices"] > 1000             # arrived on the server


def test_sync_when_the_program_is_closed(shop_cfg, monkeypatch):
    def closed(cfg):
        raise sync.ExportError("ELYASSER is not open")
    monkeypatch.setattr(sync, "export", closed)
    assert sync.run(shop_cfg) == 0


def test_sync_retries_then_gives_up(shop_cfg, fake_snapshot, monkeypatch):
    calls = []
    monkeypatch.setattr(sync, "export", lambda cfg: {})
    monkeypatch.setattr(sync, "upload", lambda cfg: calls.append(1) or (_ for _ in ()).throw(
        sync.requests.ConnectionError("offline")))
    cfg = replace(shop_cfg, snapshot_path=fake_snapshot, server_url="https://srv")
    assert sync.run(cfg, tries=3, wait=0) == 1 and len(calls) == 3


def test_sync_without_a_console(shop_cfg, fake_snapshot, monkeypatch, tmp_path):
    """Started by the Task Scheduler with pythonw: no stdout/stderr at all."""
    cfg = replace(shop_cfg, snapshot_path=tmp_path / "shop" / "snapshot.db")
    monkeypatch.setattr(sync.config, "load", lambda: cfg)
    monkeypatch.setattr(sync, "export", lambda c: print("a print that would crash") or {"items": 1})
    monkeypatch.setattr(sync.sys, "stdout", None)
    monkeypatch.setattr(sync.sys, "stderr", None)
    monkeypatch.setattr(sync.logging.root, "handlers", [])
    assert sync.main() == 0
    assert "exported" in (tmp_path / "shop" / "sync.log").read_text(encoding="utf-8")
