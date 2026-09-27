"""The server's Telegram client, with the network replaced."""
import pytest

from src import telegram_api
from src.chat import Out


@pytest.fixture
def calls(monkeypatch):
    sent = []

    class Response:
        def __init__(self, ok=True, description=""):
            self.data = {"ok": ok, "result": {}, "description": description}

        def json(self):
            return self.data

    def post(url, json, timeout):
        sent.append((url.rsplit("/", 1)[1], json))
        if json.get("text") == "same":
            return Response(False, "Bad Request: message is not modified")
        return Response()

    monkeypatch.setattr(telegram_api.requests, "post", post)
    return sent


def test_long_text_is_split_and_buttons_go_on_the_last_part(calls):
    tg = telegram_api.Telegram("T")
    tg.send(7, Out("\n".join("x" * 100 for _ in range(90)), [[("next", "list:low:1")]]))
    assert [m for m, _ in calls] == ["sendMessage", "sendMessage", "sendMessage"]
    assert all(len(p["text"]) <= 4000 for _, p in calls)
    assert "reply_markup" not in calls[0][1] and calls[-1][1]["reply_markup"] == {
        "inline_keyboard": [[{"text": "next", "callback_data": "list:low:1"}]]}


def test_main_keyboard(calls):
    telegram_api.Telegram("T").send(7, Out("hi", keyboard=True))
    markup = calls[0][1]["reply_markup"]
    assert markup["resize_keyboard"] and markup["keyboard"][0][0] == {"text": "📊 النهارده"}


def test_edit_ignores_the_same_text_twice(calls):
    tg = telegram_api.Telegram("T")
    tg.edit(7, 42, Out("same"))                       # Telegram: "message is not modified"
    with pytest.raises(telegram_api.TelegramError):
        tg.call("sendMessage", text="same")


def test_broadcast_keeps_going(calls, monkeypatch):
    tg = telegram_api.Telegram("T")
    real_send = tg.send

    def send(chat_id, out):
        if chat_id == 1:
            raise telegram_api.TelegramError("user never pressed Start")
        real_send(chat_id, out)

    monkeypatch.setattr(tg, "send", send)
    tg.broadcast({1, 2}, Out("hello"))
    assert [p["chat_id"] for _, p in calls] == [2]
