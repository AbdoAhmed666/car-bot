"""A small Telegram Bot API client for the server: send, edit, answer button presses."""
import logging

import requests

from . import messages

API = "https://api.telegram.org/bot{token}/{method}"
log = logging.getLogger("car-bot")


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token, timeout=20):
        self.token, self.timeout = token, timeout

    def call(self, method, **params):
        try:
            data = requests.post(API.format(token=self.token, method=method), json=params, timeout=self.timeout).json()
        except (requests.RequestException, ValueError) as e:
            raise TelegramError(f"{method}: {e}") from e
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description')}")
        return data.get("result")

    @staticmethod
    def markup(out):
        if out.buttons:
            return {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in row]
                                        for row in out.buttons]}
        if out.keyboard:
            return {"keyboard": [[{"text": b} for b in row] for row in messages.BUTTONS], "resize_keyboard": True}
        return None

    def send(self, chat_id, out):
        parts = messages.split(out.text)
        for n, part in enumerate(parts):
            params = {"chat_id": chat_id, "text": part}
            markup = self.markup(out) if n == len(parts) - 1 else None
            if markup:
                params["reply_markup"] = markup
            self.call("sendMessage", **params)

    def edit(self, chat_id, message_id, out):
        params = {"chat_id": chat_id, "message_id": message_id, "text": out.text}
        if out.buttons:
            params["reply_markup"] = self.markup(out)
        try:
            self.call("editMessageText", **params)
        except TelegramError as e:
            if "not modified" not in str(e):        # pressing the same button twice
                raise

    def answer(self, callback_id):
        self.call("answerCallbackQuery", callback_query_id=callback_id)

    def broadcast(self, user_ids, out):
        """Send to every user; one who never pressed Start in the bot can't be reached."""
        for user_id in user_ids:
            try:
                self.send(user_id, out)
            except TelegramError:
                log.exception("could not send to %s", user_id)
