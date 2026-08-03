#!/usr/bin/env python3
"""Telegram-бот библиотеки Antibabka: один пожизненный доступ."""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from aiohttp import web
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# Railway Variables: BOT_TOKEN, CLUB_CHAT_ID, PORT
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = 1574658804
DB_FILE = "/data/antibabka.db"
WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PORT = int(os.environ.get("PORT", "8080"))

LIFETIME_PLAN = "lifetime"
PLANS = {
    LIFETIME_PLAN: {
        "url": "https://payform.ru/5fcbJnu/",
        "label": "Доступ навсегда — 6 499 ₽",
        "amount": 6499.0,
    }
}

MSG_WELCOME = """Привет! Я Лиза, кинезио-фитнес-тренер.

Ты попала в бот библиотеки тренировок Antibabka — пространства с пожизненным доступом, где ты научишься чувствовать себя лёгкой, энергичной и уверенной каждый день.

🔥 Что ждёт тебя в библиотеке:

• 180+ тренировок на разные части тела до 40 минут: дыхание, лицо, шея, руки, плечи, живот, осанка, спина, ягодицы, ноги, таз, МТД, колени, стопы, отёки
• 15+ мини-тренировок экстренной помощи от 5 минут: при боли во время ПМС, головной боли, после сидячей работы и в других ситуациях, когда телу нужна поддержка
• 25+ зарядок для утра и вечера по 10–15 минут
• 20+ тренировок на всё тело
• 10+ силовых тренировок из умного фитнеса — для дома и зала
• 55+ упражнений для точечной работы с разными частями тела
• 27+ лекций: диастаз, холка, целлюлит и другие темы

Везде стоит «+», потому что я продолжаю пополнять библиотеку новыми тренировками и материалами.

💛 Что ты получишь:

• Минус 2–4 кг в месяц без диет — благодаря тому, что тело будет постепенно выравниваться
• Лёгкость в теле без отёков, боли и постоянной усталости
• Красивую осанку и больше уверенности в себе
• Долгосрочный результат без стресса и жёстких ограничений

👩🏼‍⚕️ Немного обо мне:

Я в профессии с 2015 года. Моё первое образование — фитнес-тренер. Затем я получила образование в сфере кинезиологии и сейчас заканчиваю обучение по физиотерапии в США.

Мои тренировки основаны на понимании медицины и анатомии: я помогаю телу двигаться лучше, чувствовать себя сильнее и легче.

Рада, что ты здесь 💛"""

MSG_OFFER = """🌿 Доступ к библиотеке приобретается один раз и остаётся с тобой навсегда.

После оплаты бот сразу пришлёт тебе персональную ссылку для вступления в клуб 🎉"""

MSG_PAY_REDIRECT = """Ты выбрала пожизненный доступ к библиотеке Antibabka.

Нажми кнопку ниже для перехода к оплате 👇"""

MSG_THANKS = """Спасибо за оплату! 💛

Добро пожаловать в библиотеку тренировок Antibabka.

Теперь у тебя пожизненный доступ ко всем тренировкам, лекциям и новым материалам, которые будут появляться в библиотеке. Продлевать ничего не нужно — доступ остаётся с тобой навсегда.

Ниже твоя персональная ссылка для вступления в клуб. Она работает один раз и только для тебя:

{invite_link}

Нажми на неё и вступай — жду тебя внутри! 🌿"""

# Это сообщение получают только участницы со СТАРОЙ срочной подпиской,
# когда она закончится. Новые пожизненные участницы его никогда не получат.
MSG_EXPIRED = """Привет! Твоя подписка на клуб Antibabka закончилась.

Теперь клуб работает в новом формате — это библиотека тренировок и лекций с пожизненным доступом 💛

Доступ приобретается один раз и остаётся с тобой навсегда: без ежемесячных продлений и ограничений по времени.

Чтобы вернуться в библиотеку, выбери пожизненный доступ ниже 👇"""


def get_club_chat_id() -> int:
    value = os.environ.get("CLUB_CHAT_ID", "0")
    return int(value) if value else 0


def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT DEFAULT (datetime('now'))
            );
            -- Старые подписки: нужны только чтобы корректно завершить их.
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan TEXT NOT NULL,
                end_date TEXT NOT NULL,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS pending_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS lifetime_access (
                user_id INTEGER PRIMARY KEY,
                granted_at TEXT NOT NULL,
                payment_plan TEXT NOT NULL DEFAULT 'lifetime'
            );
        """)
    log.info("Database initialized")


def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """INSERT INTO users (user_id, username, first_name) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name""",
            (user_id, username or "", first_name or ""),
        )


def add_pending_payment(user_id: int, plan: str, amount: float) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        # Один свежий ожидающий платёж на человека и тариф.
        conn.execute(
            "UPDATE pending_payments SET used=1 WHERE user_id=? AND plan=? AND used=0",
            (user_id, plan),
        )
        conn.execute(
            "INSERT INTO pending_payments (user_id, plan, amount, created_at) VALUES (?,?,?,?)",
            (user_id, plan, amount, datetime.utcnow().isoformat()),
        )


def match_pending_payment(amount: float):
    """Ищет ожидание оплаты за последние 24 часа.

    Это запасной способ, потому что короткие ссылки payform.ru могут не передать
    Telegram ID обратно в уведомлении Продамуса.
    """
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            """SELECT id, user_id, plan FROM pending_payments
               WHERE amount=? AND used=0 AND created_at > ?
               ORDER BY created_at ASC LIMIT 1""",
            (amount, cutoff),
        ).fetchone()
    return row if row else (None, None, None)


def mark_pending_used(pending_id: int) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE pending_payments SET used=1 WHERE id=?", (pending_id,))


def grant_lifetime_access(user_id: int) -> bool:
    """Даёт доступ навсегда и отключает любую старую срочную подписку.

    Возвращает True, если это первая пожизненная покупка пользователя.
    """
    with sqlite3.connect(DB_FILE) as conn:
        exists = conn.execute(
            "SELECT 1 FROM lifetime_access WHERE user_id=?", (user_id,)
        ).fetchone()
        conn.execute("UPDATE subscriptions SET active=0 WHERE user_id=? AND active=1", (user_id,))
        if not exists:
            conn.execute(
                "INSERT INTO lifetime_access (user_id, granted_at) VALUES (?,?)",
                (user_id, datetime.utcnow().isoformat()),
            )
            return True
    return False


def get_expired_subscriptions():
    """Только старые срочные подписки, которые ещё не завершены."""
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute(
            """SELECT s.user_id, s.plan, s.end_date
               FROM subscriptions s
               LEFT JOIN lifetime_access l ON l.user_id=s.user_id
               WHERE s.active=1 AND s.end_date <= ? AND l.user_id IS NULL""",
            (now,),
        ).fetchall()


def deactivate_subscription(user_id: int) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE subscriptions SET active=0 WHERE user_id=? AND active=1", (user_id,))


def tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(PLANS[LIFETIME_PLAN]["label"], callback_data="plan_lifetime")]
    ])


def pay_keyboard(user_id: int) -> InlineKeyboardMarkup:
    # Параметры оставлены: если Продамус их передаст, бот сразу узнает покупателя.
    url = f"{PLANS[LIFETIME_PLAN]['url']}?us_telegram_id={user_id}&us_plan={LIFETIME_PLAN}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Перейти к оплате", url=url)]
    ])


async def is_current_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in {"creator", "administrator", "member", "restricted"}
    except (BadRequest, Forbidden):
        return False


async def make_invite_link(bot: Bot, user_id: int) -> str | None:
    club_id = get_club_chat_id()
    if not club_id:
        return None
    invite = await bot.create_chat_invite_link(
        chat_id=club_id,
        member_limit=1,
        expire_date=datetime.now(timezone.utc) + timedelta(hours=48),
        name=f"lifetime_{user_id}",
    )
    return invite.invite_link


async def send_lifetime_access(bot: Bot, user_id: int) -> None:
    # Сообщение после оплаты одинаковое для всех покупателей.
    grant_lifetime_access(user_id)
    invite_link = await make_invite_link(bot, user_id)
    if invite_link:
        await bot.send_message(chat_id=user_id, text=MSG_THANKS.format(invite_link=invite_link))
    else:
        await bot.send_message(
            chat_id=user_id,
            text="Спасибо за оплату! Напиши, пожалуйста, @LizaGoal — я помогу со вступлением в библиотеку.",
        )


async def send_expired_offer(bot: Bot, user_id: int) -> None:
    await bot.send_message(chat_id=user_id, text=MSG_EXPIRED, reply_markup=tariff_keyboard())


# ── Команды и кнопки ─────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username, user.first_name)
    await update.message.reply_text(MSG_WELCOME)
    await update.message.reply_text(MSG_OFFER, reply_markup=tariff_keyboard())
    log.info(f"[START] user_id={user.id} @{user.username}")


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Резервное ручное подтверждение: /confirm USER_ID"""
    if update.effective_user.id != ADMIN_ID:
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /confirm USER_ID")
        return
    try:
        user_id = int(ctx.args[0])
        await send_lifetime_access(ctx.bot, user_id)
        await update.message.reply_text(f"Готово: пожизненный доступ отправлен пользователю {user_id}.")
        log.info(f"[MANUAL] lifetime user_id={user_id}")
    except Exception as exc:
        log.exception("[MANUAL] Error")
        await update.message.reply_text(f"Ошибка: {exc}")


async def cmd_expire(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Резервная команда для старой подписки: /expire USER_ID"""
    if update.effective_user.id != ADMIN_ID:
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /expire USER_ID")
        return
    try:
        user_id = int(ctx.args[0])
        await send_expired_offer(ctx.bot, user_id)
        await update.message.reply_text(f"Готово: предложение пожизненного доступа отправлено {user_id}.")
    except Exception as exc:
        log.exception("[EXPIRE_MANUAL] Error")
        await update.message.reply_text(f"Ошибка: {exc}")


async def cb_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Старые кнопки из давних сообщений тоже ведут на новый пожизненный доступ.
    user_id = query.from_user.id
    add_pending_payment(user_id, LIFETIME_PLAN, PLANS[LIFETIME_PLAN]["amount"])
    try:
        await query.edit_message_text(MSG_PAY_REDIRECT, reply_markup=pay_keyboard(user_id))
    except BadRequest:
        # Старые сообщения были с фото и подписью; в них нельзя заменить текст.
        await query.message.reply_text(MSG_PAY_REDIRECT, reply_markup=pay_keyboard(user_id))
    log.info(f"[PAY_INTENT] user_id={user_id} plan=lifetime")


# ── Автоматическое завершение только СТАРЫХ подписок ──────
async def job_check_subscriptions(ctx: ContextTypes.DEFAULT_TYPE):
    expired = get_expired_subscriptions()
    club_id = get_club_chat_id()
    for user_id, plan, end_date in expired:
        log.info(f"[EXPIRE] user_id={user_id} plan={plan} ended={end_date}")
        try:
            if club_id:
                await ctx.bot.ban_chat_member(chat_id=club_id, user_id=user_id)
                await ctx.bot.unban_chat_member(chat_id=club_id, user_id=user_id)
                log.info(f"[EXPIRE] Removed from club: user_id={user_id}")
        except Exception:
            log.exception(f"[EXPIRE] Could not remove user_id={user_id}")
            # Не деактивируем: бот повторит попытку позже.
            continue
        try:
            await send_expired_offer(ctx.bot, user_id)
            log.info(f"[EXPIRE] Lifetime offer sent: user_id={user_id}")
        except Exception:
            # Удаление уже прошло. Подписку всё равно закрываем, чтобы не слать спам.
            log.exception(f"[EXPIRE] Could not message user_id={user_id}")
        deactivate_subscription(user_id)
        log.info(f"[EXPIRE] Subscription deactivated: user_id={user_id}")


# ── Продамус ──────────────────────────────────────────────
_bot: Bot | None = None


def payment_amount(data: dict) -> float:
    for key in ("sum", "amount", "payment_amount"):
        value = data.get(key)
        if value not in (None, ""):
            return float(str(value).replace(",", "."))
    return 0.0


async def prodamus_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json() if "json" in (request.content_type or "") else dict(await request.post())
        log.info(f"[WEBHOOK] {json.dumps(data, ensure_ascii=False)}")
        status = str(data.get("status") or data.get("payment_status", "")).lower()
        if status not in ("success", "paid", "1", "true", "успешная оплата"):
            return web.Response(text="OK")

        raw_uid = data.get("us_telegram_id") or data.get("telegram_id") or ""
        plan = data.get("us_plan") or data.get("plan") or ""
        if not raw_uid or plan != LIFETIME_PLAN:
            amount = payment_amount(data)
            pending_id, raw_uid, plan = match_pending_payment(amount)
            if not raw_uid or plan != LIFETIME_PLAN:
                log.warning(f"[WEBHOOK] No pending match: amount={amount}")
                return web.Response(text="OK")
            mark_pending_used(pending_id)
            log.info(f"[WEBHOOK] Matched by amount {amount}: user={raw_uid}")

        if _bot is None:
            log.error("[WEBHOOK] Telegram bot is not ready")
            return web.Response(text="OK")
        user_id = int(raw_uid)
        await send_lifetime_access(_bot, user_id)
        log.info(f"[WEBHOOK] Lifetime access granted: user_id={user_id}")
    except Exception:
        log.exception("[WEBHOOK] Error")
    return web.Response(text="OK")


async def main():
    global _bot
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    _bot = application.bot

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("confirm", cmd_confirm))
    application.add_handler(CommandHandler("expire", cmd_expire))
    application.add_handler(CallbackQueryHandler(cb_plan, pattern=r"^plan_"))

    web_app = web.Application()
    web_app.router.add_post("/prodamus", prodamus_webhook)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT).start()

    # Проверка старых подписок каждые 5 минут.
    application.job_queue.run_repeating(job_check_subscriptions, interval=300, first=30)

    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        log.info("Bot is running")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
