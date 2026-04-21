#!/usr/bin/env python3
"""
╔══════════════════════════════════════════╗
║      ANTIBABKA CLUB — TELEGRAM BOT      ║
╚══════════════════════════════════════════╝

Функции:
  • /start → приветственное сообщение
  • Через 30 минут → фото с тарифами + 3 кнопки
  • Кнопки → персональная ссылка на Продамус (с telegram_id)
  • Продамус вебхук → генерация одноразовой ссылки → сообщение пользователю
  • Ежечасная проверка подписок → кик + уведомление по истечению
  • /chatid — команда для получения ID группы (только для админа)
  • /setclub — сохранить текущий чат как клуб (запускать в группе, только для админа)
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import web
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ════════════════════════════════════════════════════════
#  ЛОГИРОВАНИЕ
# ════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ════════════════════════════════════════════════════════
BOT_TOKEN   = "8724804779:AAE0bSUwRsJGw2LUYgww4q0bw2ZcxqG3jfg"
ADMIN_ID    = 1574658804   # Telegram ID Лизы
DB_FILE     = "antibabka.db"
CONFIG_FILE = "config.json"
PHOTO_FILE  = "tariffs.jpg"  # фото с тарифами (положи рядом с bot.py)

WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PORT = int(os.environ.get("PORT", 8080))  # Railway задаёт PORT автоматически

# Задержка перед отправкой тарифов (в минутах)
TARIFF_DELAY_MINUTES = 30

# ════════════════════════════════════════════════════════
#  ТАРИФНЫЕ ПЛАНЫ
# ════════════════════════════════════════════════════════
PLANS = {
    "1month": {
        "url":   "https://payform.ru/cnaS4vN/",
        "label": "1 месяц — 1 490 ₽",
        "days":  30,
    },
    "3months": {
        "url":   "https://payform.ru/osaS4Cg/",
        "label": "3 месяца — 3 999 ₽",
        "days":  90,
    },
    "6months": {
        "url":   "https://payform.ru/4kaS4HC/",
        "label": "6 месяцев — 7 490 ₽",
        "days":  180,
    },
}


# ════════════════════════════════════════════════════════
#  ТЕКСТЫ СООБЩЕНИЙ
# ════════════════════════════════════════════════════════
MSG_WELCOME = """\
✨ <b>Привет! Я Лиза</b> — основатель закрытого клуба <b>Antibabka</b>.

Это место, где ты забудешь про усталость, отёки и диеты и научишься чувствовать себя лёгкой, энергичной и уверенной каждый день.

🔥 <b>Что тебя ждёт в клубе:</b>
• Мини-тренировки от 5 минут в день
• Зарядки утро/вечер 10–15 минут
• Комплексы на разные части тела до 40 минут
• Точечные тренировки экстренной помощи
• 30+ лекций (диастаз, холка, целлюлит и др.)

💛 <b>Что ты получишь:</b>
• −2–4 кг в месяц без жёстких диет
• Лёгкость в теле: без отёков, боли и усталости
• Красивая осанка и уверенность в себе
• Долгосрочный результат без стресса

👩🏼‍⚕️ <b>Немного обо мне:</b>
В профессии с 2015 года. Фитнес-тренер, кинезиолог, прохожу обучение по физиотерапии в США. Мои тренировки построены на базе медицины и анатомии — результат сравним с работой остеопата.

Рада, что ты здесь 💛
<i>Скоро пришлю тебе варианты тарифов — жди!</i>"""

MSG_TARIFFS = """\
🌿 <b>Выбери свой тариф!</b>

На фото — 3 плана: на 1, 3 и 6 месяцев. Они отличаются не только сроком, но и набором возможностей — посмотри внимательно.

После оплаты тебе придёт ссылка, чтобы вступить в клуб 🎉

Выбирай то, что тебе подходит, и нажимай кнопку 👇"""

MSG_PAY_REDIRECT = """\
✅ Отлично! Ты выбрала тариф <b>{label}</b>.

Нажми кнопку ниже для перехода к оплате 👇"""

MSG_THANKS = """\
🎉 <b>Спасибо за оплату! Добро пожаловать в клуб Antibabka!</b>

Вот твоя персональная ссылка — она работает <b>только 1 раз и только для тебя:</b>

🔗 {invite_link}

Нажми на ссылку и вступай — жду тебя внутри! 💛"""

MSG_EXPIRED = """\
⏰ <b>Привет!</b> Твоя подписка на клуб <b>Antibabka</b> закончилась.

Надеюсь, ты уже почувствовала результат! Чтобы продолжить путь — выбери тариф и продли доступ 👇"""


# ════════════════════════════════════════════════════════
#  КОНФИГ (хранит CLUB_CHAT_ID между перезапусками)
# ════════════════════════════════════════════════════════
def load_config() -> dict:
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"club_chat_id": 0}


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


config = load_config()


def get_club_chat_id() -> int:
    return config.get("club_chat_id", 0)


def set_club_chat_id(chat_id: int):
    config["club_chat_id"] = chat_id
    save_config(config)


# ════════════════════════════════════════════════════════
#  БАЗА ДАННЫХ (SQLite)
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


def upsert_user(user_id: int, username: str, first_name: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """INSERT INTO users (user_id, username, first_name)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   username=excluded.username,
                   first_name=excluded.first_name""",
            (user_id, username or "", first_name or ""),
        )


def add_subscription(user_id: int, plan: str, days: int) -> str:
    """Добавляет подписку, деактивирует старые. Возвращает дату окончания."""
    end = (datetime.utcnow() + timedelta(days=days)).isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "UPDATE subscriptions SET active=0 WHERE user_id=?", (user_id,)
        )
        conn.execute(
            "INSERT INTO subscriptions (user_id, plan, end_date) VALUES (?,?,?)",
            (user_id, plan, end),
        )
    return end


def get_expired_subscriptions():
    """Возвращает [(user_id, plan, end_date)] истёкших активных подписок."""
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute(
            "SELECT user_id, plan, end_date FROM subscriptions WHERE active=1 AND end_date <= ?",
            (now,),
        ).fetchall()


def deactivate_subscription(user_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "UPDATE subscriptions SET active=0 WHERE user_id=? AND active=1",
            (user_id,),
        )


def schedule_tariff_message(user_id: int, send_at: datetime):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """INSERT INTO tariff_scheduled (user_id, send_at)
               VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET send_at=excluded.send_at, sent=0""",
            (user_id, send_at.isoformat()),
        )


def get_pending_tariff_users() -> list[int]:
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT user_id FROM tariff_scheduled WHERE sent=0 AND send_at <= ?",
            (now,),
        ).fetchall()
    return [r[0] for r in rows]


def mark_tariff_sent(user_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "UPDATE tariff_scheduled SET sent=1 WHERE user_id=?", (user_id,)
        )


# ════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ════════════════════════════════════════════════════════
def tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(PLANS["1month"]["label"],  callback_data="plan_1month")],
        [InlineKeyboardButton(PLANS["3months"]["label"], callback_data="plan_3months")],
        [InlineKeyboardButton(PLANS["6months"]["label"], callback_data="plan_6months")],
    ])


def pay_keyboard(plan: str, user_id: int) -> InlineKeyboardMarkup:
    """Кнопка с персональной ссылкой на Продамус (содержит telegram_id)."""
    url = f"{PLANS[plan]['url']}?us_telegram_id={user_id}&us_plan={plan}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Перейти к оплате", url=url)],
        [InlineKeyboardButton("◀️ Выбрать другой тариф", callback_data="back_to_tariffs")],
    ])


# ════════════════════════════════════════════════════════
#  ОБРАБОТЧИКИ КОМАНД И КНОПОК
# ════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username, user.first_name)

    await update.message.reply_html(MSG_WELCOME)

    # Запланировать отправку тарифов через N минут
    send_at = datetime.utcnow() + timedelta(minutes=TARIFF_DELAY_MINUTES)
    schedule_tariff_message(user.id, send_at)

    log.info(f"[START] user_id={user.id} @{user.username} first_name={user.first_name}")


async def cmd_chatid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показывает ID текущего чата — для настройки бота."""
    if update.effective_user.id != ADMIN_ID:
        return
    chat = update.effective_chat
    await update.message.reply_text(
        f"📋 Информация о чате:\n"
        f"ID: <code>{chat.id}</code>\n"
        f"Тип: {chat.type}\n"
        f"Название: {chat.title or '—'}",
        parse_mode="HTML",
    )


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /confirm USER_ID PLAN — вручную выдать подписку пользователю.
    Только для Лизы (ADMIN_ID). Использовать если вебхук Продамуса не сработал.
    Пример: /confirm 123456789 1month
    """
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
            await update.message.reply_text(f"❌ Неверный план. Доступные: {', '.join(PLANS.keys())}")
            return
        days = PLANS[plan]["days"]
        club_id = get_club_chat_id()
        end_date = add_subscription(user_id, plan, days)
        # Создаём одноразовую инвайт-ссылку
        if club_id != 0:
            invite = await ctx.bot.create_chat_invite_link(
                chat_id=club_id,
                member_limit=1,
                expire_date=datetime.now(timezone.utc) + timedelta(hours=48),
                name=f"manual_{user_id}_{plan}",
            )
            invite_link = invite.invite_link
        else:
            invite_link = "⚠️ Сначала настрой клуб командой /setclub"
        await ctx.bot.send_message(
            chat_id=user_id,
            text=MSG_THANKS.format(invite_link=invite_link),
            parse_mode="HTML",
        )
        await update.message.reply_text(
            f"✅ Готово!\nПользователь {user_id} получил тариф {plan} до {end_date[:10]}\n"
            f"Инвайт: {invite_link}"
        )
        log.info(f"[MANUAL] Admin confirmed: user_id={user_id} plan={plan}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        log.error(f"[MANUAL] Error: {e}")


async def cmd_setclub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Сохраняет текущий чат как клуб. Запускать в группе клуба!"""
    if update.effective_user.id != ADMIN_ID:
        return
    chat = update.effective_chat
    set_club_chat_id(chat.id)
    log.info(f"Club chat set to {chat.id} ({chat.title})")
    await update.message.reply_text(
        f"✅ Клуб настроен!\n"
        f"ID группы: <code>{chat.id}</code>\n"
        f"Название: {chat.title}\n\n"
        f"Теперь бот будет выдавать инвайт-ссылки и кикать участников отсюда.",
        parse_mode="HTML",
    )


async def cb_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Пользователь выбрал тариф — показываем кнопку оплаты."""
    query = update.callback_query
    await query.answer()

    plan = query.data.replace("plan_", "")
    user_id = query.from_user.id
    label = PLANS[plan]["label"]

    await query.edit_message_caption(
        caption=MSG_PAY_REDIRECT.format(label=label),
        reply_markup=pay_keyboard(plan, user_id),
        parse_mode="HTML",
    )


async def cb_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Кнопка «Назад» — возврат к выбору тарифа."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_caption(
        caption=MSG_TARIFFS,
        reply_markup=tariff_keyboard(),
        parse_mode="HTML",
    )


# ════════════════════════════════════════════════════════
#  ФОНОВЫЕ ЗАДАЧИ (Job Queue)
# ════════════════════════════════════════════════════════
async def job_send_tariffs(ctx: ContextTypes.DEFAULT_TYPE):
    """Каждую минуту: отправляем тарифы тем, кто ждёт 30 минут."""
    pending = get_pending_tariff_users()
    for user_id in pending:
        try:
            with open(PHOTO_FILE, "rb") as photo:
                await ctx.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=MSG_TARIFFS,
                    reply_markup=tariff_keyboard(),
                    parse_mode="HTML",
                )
            mark_tariff_sent(user_id)
            log.info(f"[TARIFF] Sent to user_id={user_id}")
        except Exception as e:
            log.error(f"[TARIFF] Failed for user_id={user_id}: {e}")


async def job_check_subscriptions(ctx: ContextTypes.DEFAULT_TYPE):
    """Каждый час: кикаем участников с истёкшей подпиской."""
    expired = get_expired_subscriptions()
    club_id = get_club_chat_id()

    for user_id, plan, end_date in expired:
        log.info(f"[EXPIRE] user_id={user_id} plan={plan} ended={end_date}")
        try:
            # Кик из группы (бан + немедленный разбан = кик без чёрного списка)
            if club_id != 0:
                await ctx.bot.ban_chat_member(chat_id=club_id, user_id=user_id)
                await ctx.bot.unban_chat_member(chat_id=club_id, user_id=user_id)
                log.info(f"[EXPIRE] Kicked user_id={user_id} from club")

            # Уведомление с предложением продлить
            with open(PHOTO_FILE, "rb") as photo:
                await ctx.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=MSG_EXPIRED,
                    reply_markup=tariff_keyboard(),
                    parse_mode="HTML",
                )

            deactivate_subscription(user_id)
        except Exception as e:
            log.error(f"[EXPIRE] Error for user_id={user_id}: {e}")


# ════════════════════════════════════════════════════════
#  ВЕБХУК ПРОДАМУСА (aiohttp сервер)
# ════════════════════════════════════════════════════════

# Глобальная ссылка на бота (нужна в вебхуке)
_bot: Bot | None = None


async def prodamus_webhook(request: web.Request) -> web.Response:
    """
    Принимает POST-уведомление от Продамуса об успешной оплате.
    Ожидаемые поля: status, us_telegram_id, us_plan
    """
    try:
        content_type = request.content_type or ""
        if "json" in content_type:
            data = await request.json()
        else:
            data = dict(await request.post())

        log.info(f"[WEBHOOK] Prodamus data: {json.dumps(data, ensure_ascii=False)}")

        # Проверяем статус оплаты
        status = str(data.get("status", "")).lower()
        if status not in ("success", "paid", "1", "true"):
            log.info(f"[WEBHOOK] Non-success status: {status}, ignoring")
            return web.Response(text="OK")

        # Telegram ID и план из кастомных полей
        raw_uid = data.get("us_telegram_id") or data.get("telegram_id") or ""
        plan    = data.get("us_plan")        or data.get("plan")         or ""

        if not raw_uid or plan not in PLANS:
            log.warning(f"[WEBHOOK] Missing us_telegram_id or invalid plan. data={data}")
            return web.Response(text="OK")

        user_id = int(raw_uid)
        days    = PLANS[plan]["days"]
        club_id = get_club_chat_id()

        # Сохраняем подписку
        end_date = add_subscription(user_id, plan, days)
        log.info(f"[WEBHOOK] Subscription: user_id={user_id} plan={plan} until={end_date}")

        # Создаём одноразовую инвайт-ссылку
        if club_id != 0 and _bot is not None:
            invite = await _bot.create_chat_invite_link(
                chat_id=club_id,
                member_limit=1,
                expire_date=datetime.now(timezone.utc) + timedelta(hours=48),
                name=f"user_{user_id}_{plan}",
            )
            invite_link = invite.invite_link
        else:
            invite_link = "⚠️ Ссылка ещё не настроена — напишите @LizaGoal"

        # Отправляем благодарность с инвайт-ссылкой
        if _bot is not None:
            await _bot.send_message(
                chat_id=user_id,
                text=MSG_THANKS.format(invite_link=invite_link),
                parse_mode="HTML",
            )
        log.info(f"[WEBHOOK] Thanks sent to user_id={user_id}, invite={invite_link}")

    except Exception as e:
        log.error(f"[WEBHOOK] Error: {e}", exc_info=True)

    return web.Response(text="OK")


# ════════════════════════════════════════════════════════
#  ЗАПУСК
# ════════════════════════════════════════════════════════
async def main():
    global _bot

    init_db()

    # Создаём Telegram Application
    application = Application.builder().token(BOT_TOKEN).build()
    _bot = application.bot

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start",   cmd_start))
    application.add_handler(CommandHandler("chatid",  cmd_chatid))
    application.add_handler(CommandHandler("setclub", cmd_setclub))
    application.add_handler(CommandHandler("confirm", cmd_confirm))
    application.add_handler(CallbackQueryHandler(cb_plan, pattern=r"^plan_"))
    application.add_handler(CallbackQueryHandler(cb_back, pattern=r"^back_to_tariffs$"))

    # Фоновые задачи
    jq = application.job_queue
    jq.run_repeating(job_send_tariffs,        interval=60,   first=5)   # каждую минуту
    jq.run_repeating(job_check_subscriptions, interval=3600, first=60)  # каждый час

    # Запускаем aiohttp-сервер для вебхука Продамуса
    web_app = web.Application()
    web_app.router.add_post("/prodamus", prodamus_webhook)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    log.info(f"Prodamus webhook listening on 0.0.0.0:{WEBHOOK_PORT}/prodamus")

    # Запускаем бота (polling)
    log.info("Bot is starting...")
    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        log.info("Bot is running! Press Ctrl+C to stop.")
        await asyncio.Event().wait()  # ждём вечно


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot stopped by user")
