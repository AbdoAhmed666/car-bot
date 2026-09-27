"""Tell Telegram where the server is (once, after the web app is up).

    python -m src.webhook set https://USERNAME.pythonanywhere.com
    python -m src.webhook info
    python -m src.webhook delete      back to long polling (python -m src.bot on the laptop)
"""
import json
import sys

from . import config
from .telegram_api import Telegram


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cfg = config.load()
    tg = Telegram(cfg.telegram_token)
    if argv[:1] == ["set"] and len(argv) == 2:
        if not cfg.webhook_secret:
            print("Put a WEBHOOK_SECRET in .env first")
            return 1
        tg.call("setWebhook", url=argv[1].rstrip("/") + "/telegram", secret_token=cfg.webhook_secret,
                allowed_updates=["message", "callback_query"], drop_pending_updates=True)
        print("webhook set")
    elif argv[:1] == ["delete"]:
        tg.call("deleteWebhook")
        print("webhook deleted")
    elif argv[:1] == ["info"]:
        print(json.dumps(tg.call("getWebhookInfo"), indent=2, ensure_ascii=False))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
