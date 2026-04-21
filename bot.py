#!/usr/bin/env python3
"""
╔══════════════════════════════════════════╗
║      ANTIBABKA CLUB — TELEGRAM BOT      ║
╚══════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from aiohttp import web
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ════════════════════════════════════════════════════════
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "8724804779:AAE0bSUwRsJGw2LUYgww4q0bw2ZcxqG3jfg")
ADMIN_ID     = 1574658804
DB_FILE      = "antibabka.db"
PHOTO_FILE   = "tariffs.jpg"
WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PORT = int(os.environ.get("PORT", 8080))
TARIFF_DELAY_MINUTES = 1

def get_club_chat_id() -> int:
    env_id = os.environ.get("CLUB_CHAT_ID", "0")
    if env_id and env_id != "0":
        return int(env_id)
    return 0

# ════════════════════════════════════════════════════════
#  ТАРИФНЫЕ ПЛАНЫ
# ════════════════════════════════════════════════════════
PLANS = {
    "1month": {
        "url":   "https://payform.ru/cnaS4vN/",
        "label": "1 месяц - 1 490 ₽",
        "days":  30,
    },
    "3months": {
        "url":   "https://payform.ru/osaS4Cg/",
        "label": "3 месяца - 3 999 ₽",
        "days":  90,
    },
    "6months": {
        "url":   "https://payform.ru/4kaS4HC/",
        "label": "6 месяцев - 7 490 ₽",
        "days":  180,
    },
}

# ════════════════════════════════════════════════════════
#  ТЕКСТЫ
# ════════════════════════════════════════════════════════
MSG_WELCOME = """\
Привет! Я Лиза - основатель закрытого клуба Antibabka.

Это место, где ты забудешь про усталость, отёки, диеты и прочие неприятности! Ты научишься чувствовать себя лёгкой, энергичной и уверенной каждый день.

🔥 Что тебя ждёт в клубе:
• Мини-тренировки от 5 минут в день
• Зарядки утро/вечер 10-15 минут
• Комплексы на разные части тела до 40 минут
• Точечные тренировки экстренной помощи (если что-то заболело)
• 30+ лекций (диастаз, холка, целлюлит и др.)

💛 Что ты получишь:
• -2-4 кг в месяц без диет (тк тело будет выравниваться)
• Лёгкость в теле: без отёков, боли и усталости
• Красивая осанка = уверенность в себе
• Долгосрочный результат без стресса (через месяц снова набрала - такого не будет)

👩🏼‍⚕️ Немного обо мне:
В профессии с 2015 года. Первое образование фитнес-тренер, дальше я дипломировалась на кинезиолога, сейчас заканчиваю обучение по физиотерапии в США. Мои тренировки построены на медицине и анатомии - результат сравним с работой остеопата.

Рада, что ты здесь 💛
Ниже варианты тарифов, жду тебя в клубе"""

MSG_TARIFFS = """\
🌿 Выбери свой тариф!

На фото - 3 плана: на 1, 3 и 6 месяцев. Они отличаются не только сроком, но и набором возможностей - посмотри внимательно.

После оплаты тебе придёт ссылка, чтобы вступить в клуб 🎉

Выбирай то, что тебе подходит, и нажимай кнопку 👇"""

MSG_PAY_REDIRECT = """\
Ты выбрала тариф {label}.

Нажми кнопку ниже для перехода к оплате 👇"""

# Разные сообщения для каждого тарифа
MSG_THANKS_1MONTH = """\
Спасибо за оплату! Добро пожаловать в клуб Antibabka! 🎉

Вот твоя персональная ссылка - она работает только 1 раз и только для тебя:

{invite_link}

Нажми на ссылку и вступай - жду тебя внутри! 💛"""

MSG_THANKS_3MONTHS = """\
Спасибо за оплату! Добро пожаловать в клуб Antibabka! 🎉

Вот твоя персональная ссылка - она работает только 1 раз и только для тебя:

{invite_link}

Так как выбран тариф на 3 месяца, ты получаешь дополнительные бонусы, напиши мне в личку: @LizaGoal "Привет Лиза, я в клубе на 3 месяца, готова приступать к апгрейду!" 💛"""

MSG_THANKS_6MONTHS = """\
Спасибо за оплату! Добро пожаловать в клуб Antibabka! 🎉

Вот твоя персональная ссылка - она работает только 1 раз и только для тебя:

{invite_link}

Так как выбран тариф на 6 месяцев, ты получаешь ВСЕ бонусы, напиши мне в личку: @LizaGoal "Привет Лиза, я в клубе на 6 месяцев, готова к личному ведению!" 💛"""

THANKS_BY_PLAN = {
    "1month":  MSG_THANKS_1MONTH,
    "3months": MSG_THANKS_3MONTHS,
    "6months": MSG_THANKS_6MONTHS,
}

MSG_EXPIRED = """\
Привет! Твоя подписка на клуб Antibabka закончилась.

Надеюсь, ты уже почувствовала результат! Чтобы продолжить - выбери тариф и продли доступ 👇"""

# ════════════════════════════════════════════════════════
#  БАЗА ДАННЫХ
# ════════════════════════════════════════════════════════
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                first_name TEXT,
                joined_at  TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                plan       TEXT    NOT NULL,
                end_date   TEXT    NOT NULL,
                active     INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tariff_scheduled (
                user_id    INTEGER PRIMARY KEY,
                send_at    TEXT    NOT NULL,
                sent       INTEGER DEFAULT 0
            );
        """)
    log.info("Database initialized")


def upsert_user(user_id, username, first_name):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """INSERT INTO users (user_id, username, first_name) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name""",
            (user_id, username or "", first_name or ""),
        )


def add_subscription(user_id, plan, days):
    end = (datetime.utcnow() + timedelta(days=days)).isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE subscriptions SET active=0 WHERE user_id=?", (user_id,))
        conn.execute("INSERT INTO subscriptions (user_id, plan, end_date) VALUES (?,?,?)", (user_id, plan, end))
    return end


def get_expired_subscriptions():
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute(
            "SELECT user_id, plan, end_date FROM subscriptions WHERE active=1 AND end_date <= ?", (now,)
        ).fetchall()


def deactivate_subscription(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE subscriptions SET active=0 WHERE user_id=? AND active=1", (user_id,))


def schedule_tariff_message(user_id, send_at):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """INSERT INTO tariff_scheduled (user_id, send_at) VALUES (?,?)
               ON CONFLICT(user_id) DO UPDATE SET send_at=excluded.send_at, sent=0""",
            (user_id, send_at.isoformat()),
        )


def get_pending_tariff_users():
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT user_id FROM tariff_scheduled WHERE sent=0 AND send_at <= ?", (now,)
        ).fetchall()
    return [r[0] for r in rows]


def mark_tariff_sent(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE tariff_scheduled SET sent=1 WHERE user_id=?", (user_id,))

# ════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ════════════════════════════════════════════════════════
def tariff_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(PLANS["1month"]["label"],  callback_data="plan_1month")],
        [InlineKeyboardButton(PLANS["3months"]["label"], callback_data="plan_3months")],
        [InlineKeyboardButton(PLANS["6months"]["label"], callback_data="plan_6months")],
    ])


def pay_keyboard(plan, user_id):
    url = f"{PLANS[plan]['url']}?us_telegram_id={user_id}&us_plan={plan}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Перейти к оплате", url=url)],
        [InlineKeyboardButton("Выбрать другой тариф", callback_data="back_to_tariffs")],
    ])

# ════════════════════════════════════════════════════════
#  ОБРАБОТЧИКИ
# ════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username, user.first_name)
    await update.message.reply_text(MSG_WELCOME)
    send_at = datetime.utcnow() + timedelta(minutes=TARIFF_DELAY_MINUTES)
    schedule_tariff_message(user.id, send_at)
    log.info(f"[START] user_id={user.id} @{user.username}")


async def cmd_chatid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    chat = update.effective_chat
    await update.message.reply_text(f"Chat ID: {chat.id}\nТип: {chat.type}\nНазвание: {chat.title or '—'}")


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ручное подтверждение оплаты: /confirm USER_ID PLAN"""
    if update.effective_user.id != ADMIN_ID:
        return
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Использование: /confirm USER_ID PLAN\n"
            "Планы: 1month, 3months, 6months\n"
            "Пример: /confirm 123456789 1month"
        )
        return
    try:
        user_id = int(args[0])
        plan = args[1]
        if plan not in PLANS:
            await update.message.reply_text(f"Неверный план. Доступные: {', '.join(PLANS.keys())}")
            return
        days = PLANS[plan]["days"]
        club_id = get_club_chat_id()
        end_date = add_subscription(user_id, plan, days)
        if club_id != 0:
            invite = await ctx.bot.create_chat_invite_link(
                chat_id=club_id,
                member_limit=1,
                expire_date=datetime.now(timezone.utc) + timedelta(hours=48),
                name=f"manual_{user_id}_{plan}",
            )
            invite_link = invite.invite_link
        else:
            invite_link = "Свяжитесь с @LizaGoal"
        msg_text = THANKS_BY_PLAN[plan].format(invite_link=invite_link)
        await ctx.bot.send_message(chat_id=user_id, text=msg_text)
        await update.message.reply_text(
            f"Готово! Пользователь {user_id} получил тариф {plan} до {end_date[:10]}\n"
            f"Инвайт: {invite_link}"
        )
        log.info(f"[MANUAL] user_id={user_id} plan={plan}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")
        log.error(f"[MANUAL] Error: {e}")


async def cb_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan = query.data.replace("plan_", "")
    user_id = query.from_user.id
    label = PLANS[plan]["label"]
    await query.edit_message_caption(
        caption=MSG_PAY_REDIRECT.format(label=label),
        reply_markup=pay_keyboard(plan, user_id),
    )


async def cb_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_caption(
        caption=MSG_TARIFFS,
        reply_markup=tariff_keyboard(),
    )

# ════════════════════════════════════════════════════════
#  ФОНОВЫЕ ЗАДАЧИ
# ════════════════════════════════════════════════════════
async def job_send_tariffs(ctx: ContextTypes.DEFAULT_TYPE):
    pending = get_pending_tariff_users()
    for user_id in pending:
        try:
            with open(PHOTO_FILE, "rb") as photo:
                await ctx.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=MSG_TARIFFS,
                    reply_markup=tariff_keyboard(),
                )
            mark_tariff_sent(user_id)
            log.info(f"[TARIFF] Sent to user_id={user_id}")
        except Exception as e:
            log.error(f"[TARIFF] Failed for user_id={user_id}: {e}")


async def job_check_subscriptions(ctx: ContextTypes.DEFAULT_TYPE):
    expired = get_expired_subscriptions()
    club_id = get_club_chat_id()
    for user_id, plan, end_date in expired:
        log.info(f"[EXPIRE] user_id={user_id} plan={plan} ended={end_date}")
        try:
            if club_id != 0:
                await ctx.bot.ban_chat_member(chat_id=club_id, user_id=user_id)
                await ctx.bot.unban_chat_member(chat_id=club_id, user_id=user_id)
            with open(PHOTO_FILE, "rb") as photo:
                await ctx.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=MSG_EXPIRED,
                    reply_markup=tariff_keyboard(),
                )
            deactivate_subscription(user_id)
        except Exception as e:
            log.error(f"[EXPIRE] Error for user_id={user_id}: {e}")

# ════════════════════════════════════════════════════════
#  ВЕБХУК ПРОДАМУСА
# ════════════════════════════════════════════════════════
_bot: Bot | None = None


async def prodamus_webhook(request: web.Request) -> web.Response:
    try:
        content_type = request.content_type or ""
        if "json" in content_type:
            data = await request.json()
        else:
            data = dict(await request.post())
        log.info(f"[WEBHOOK] {json.dumps(data, ensure_ascii=False)}")
        status = str(data.get("status", "")).lower()
        if status not in ("success", "paid", "1", "true"):
            return web.Response(text="OK")
        raw_uid = data.get("us_telegram_id") or data.get("telegram_id") or ""
        plan    = data.get("us_plan") or data.get("plan") or ""
        if not raw_uid or plan not in PLANS:
            return web.Response(text="OK")
        user_id = int(raw_uid)
        club_id = get_club_chat_id()
        end_date = add_subscription(user_id, plan, PLANS[plan]["days"])
        if club_id != 0 and _bot is not None:
            invite = await _bot.create_chat_invite_link(
                chat_id=club_id,
                member_limit=1,
                expire_date=datetime.now(timezone.utc) + timedelta(hours=48),
                name=f"user_{user_id}_{plan}",
            )
            invite_link = invite.invite_link
        else:
            invite_link = "Свяжитесь с @LizaGoal"
        if _bot is not None:
            msg_text = THANKS_BY_PLAN[plan].format(invite_link=invite_link)
            await _bot.send_message(chat_id=user_id, text=msg_text)
        log.info(f"[WEBHOOK] Done: user={user_id} plan={plan} until={end_date}")
    except Exception as e:
        log.error(f"[WEBHOOK] Error: {e}", exc_info=True)
    return web.Response(text="OK")

# ════════════════════════════════════════════════════════
#  ЗАПУСК
# ════════════════════════════════════════════════════════
async def main():
    global _bot
    init_db()
    log.info(f"CLUB_CHAT_ID = {get_club_chat_id()}")

    application = Application.builder().token(BOT_TOKEN).build()
    _bot = application.bot

    application.add_handler(CommandHandler("start",   cmd_start))
    application.add_handler(CommandHandler("chatid",  cmd_chatid))
    application.add_handler(CommandHandler("confirm", cmd_confirm))
    application.add_handler(CallbackQueryHandler(cb_plan, pattern=r"^plan_"))
    application.add_handler(CallbackQueryHandler(cb_back, pattern=r"^back_to_tariffs$"))

    jq = application.job_queue
    jq.run_repeating(job_send_tariffs,        interval=60,   first=5)
    jq.run_repeating(job_check_subscriptions, interval=3600, first=60)

    web_app = web.Application()
    web_app.router.add_post("/prodamus", prodamus_webhook)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    log.info(f"Webhook on port {WEBHOOK_PORT}")

    log.info("Bot starting...")
    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        log.info("Bot is running!")
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot stopped")
