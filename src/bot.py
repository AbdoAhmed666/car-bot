"""The bot on a computer that stays on while it runs (the laptop, for testing).

    python -m src.bot

Long polling: it asks Telegram for new messages, so nothing has to be open
to the internet. The answers come from src/chat.py; the server version
(src/webapp.py) gives the same answers through a webhook.
"""
import asyncio
import logging
import sys
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, Defaults, MessageHandler, filters

from . import config, messages
from .chat import Chat
from .reports import Reports
from .shop import Shop
from .state import State

log = logging.getLogger("car-bot")
KEYBOARD = ReplyKeyboardMarkup(messages.BUTTONS, resize_keyboard=True)


def markup(out):
    if out.buttons:
        return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row]
                                     for row in out.buttons])
    return KEYBOARD if out.keyboard else None


async def send(bot, chat_id, out):
    parts = messages.split(out.text)
    for n, part in enumerate(parts):
        last = n == len(parts) - 1
        await bot.send_message(chat_id, part, reply_markup=markup(out) if last else None)


async def on_text(update, context):
    chat, user = context.bot_data["chat"], update.effective_user
    if chat.allowed(user.id):
        await update.effective_chat.send_action("typing")
    else:
        log.info("refused Telegram user %s (%s)", user.id, user.full_name)
    for out in await asyncio.to_thread(chat.on_text, user.id, update.effective_message.text):
        await send(context.bot, update.effective_chat.id, out)


async def on_button(update, context):
    query = update.callback_query
    await query.answer()
    for out in await asyncio.to_thread(context.bot_data["chat"].on_button, update.effective_user.id, query.data):
        if out.edit and len(out.text) <= 4000:
            await query.edit_message_text(out.text, reply_markup=markup(out))
        else:
            await send(context.bot, update.effective_chat.id, out)


def _job(which):
    async def run(context):
        out = await asyncio.to_thread(context.bot_data["chat"].scheduled, which)
        for user_id in context.bot_data["cfg"].allowed_users:
            try:
                await send(context.bot, user_id, out)
            except Exception:
                log.exception("could not send to %s (did they press Start?)", user_id)
    return run


async def on_error(update, context):
    log.error("error while handling an update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("حصل خطأ. جرّب تاني بعد شوية.")


def build_app(cfg, reports=None) -> Application:
    tz = ZoneInfo(cfg.timezone)
    app = Application.builder().token(cfg.telegram_token).defaults(Defaults(tzinfo=tz)).build()
    reports = reports or Reports(Shop(cfg), cfg, State(cfg.state_path), cfg.as_of)
    app.bot_data.update(cfg=cfg, chat=Chat(reports, cfg))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT, on_text))
    app.add_error_handler(on_error)

    jobs = app.job_queue
    jobs.run_daily(_job("daily"), cfg.daily_update.replace(tzinfo=tz), name="daily")
    jobs.run_daily(_job("eod"), cfg.end_of_day.replace(tzinfo=tz), name="end_of_day")
    # python-telegram-bot numbers days Sunday = 0, Python Monday = 0
    jobs.run_daily(_job("weekly"), cfg.weekly_time.replace(tzinfo=tz), days=((cfg.weekly_day + 1) % 7,),
                   name="weekly")
    return app


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)     # otherwise every poll is logged
    cfg = config.load()
    if not cfg.telegram_token:
        sys.exit("TELEGRAM_TOKEN is empty: put the token from @BotFather in .env")
    if not cfg.allowed_users:
        log.warning("ALLOWED_USERS is empty: send /start to the bot to get your id, then add it to .env")
    if cfg.as_of:
        log.warning("AS_OF is set: every report acts as if it were %s (testing on a copy)", cfg.as_of)
    app = build_app(cfg)
    log.info("car-bot running: snapshot %s, %d allowed users", cfg.snapshot_path, len(cfg.allowed_users))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
