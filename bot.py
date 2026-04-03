"""
Бот подтверждения промокодов GTA 5 RP: промо-пост, приём заявок (статик+сервер → видео/кружок/ссылка), админка.
Запуск из папки promo:  py -3 bot.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from html import escape as html_escape
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("promo_bot")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
SUBMISSIONS_FILE = DATA_DIR / "submissions.json"
CAPTION_FILE = BASE_DIR / "promo_caption.txt"
BANNED_WORDS_FILE = BASE_DIR / "banned_words.txt"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
_raw_admins = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: set[int] = set()
for part in _raw_admins.split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.add(int(part))

PROMO_BANNER = os.getenv("PROMO_BANNER", "banner.png").strip() or "banner.png"

BTN_SUBMIT = "📩 Отправить подтверждение"
BTN_HOWTO = "❓ Что нужно сделать"

# Убрать «бар» с кнопками, пока человек вводит данные / грузит медиа
HIDDEN_MENU = ReplyKeyboardRemove()

STATIC_LINE_MAX_LEN = 120
# Буквы/цифры разных алфавитов, пробелы, типичные символы статика и сервера
_STATIC_ALLOWED = re.compile(r"^[\w\s#./\\\-–—«»'№()\[\]=+*:,]+$", re.UNICODE)

MSG_REJECT_BANNED = (
    "Текст не прошёл проверку: есть недопустимые или оскорбительные слова. "
    "Напиши нормально и отправь снова."
)
MSG_REJECT_STATIC_FORMAT = (
    "Проверь строку: только статик и сервер без ссылок и лишних символов "
    f"(до {STATIC_LINE_MAX_LEN} символов). Пример: <code>12345 La Puerta</code>"
)
MSG_FLOW_NO_MENU = (
    "\n\n<i>Кнопки меню скрыты, пока ты не закончишь шаг. Отмена: /cancel</i>"
)

WELCOME_TEXT = (
    "👋 Добро пожаловать в бот подтверждения промокодов GTA 5 RP.\n\n"
    "⚠️ Подтверждение нужно отправлять только после достижения 5 уровня персонажа.\n\n"
    "Снизу две кнопки: сначала можно открыть «" + BTN_HOWTO + "», "
    "а заявку начать кнопкой «" + BTN_SUBMIT + "» — статик и сервер, затем фото или видео с промокодом "
    "<b>pestona</b> на экране (или ссылку на видео)."
)

HOWTO_TEXT = (
    "<b>Как отправить подтверждение</b>\n\n"
    "1) Нажми «" + BTN_SUBMIT + "».\n"
    "2) Одним сообщением напиши <b>статик</b> и <b>сервер</b> (пример: <code>12345 La Puerta</code>).\n"
    "3) Отправь <b>фото или видео</b>, где на экране видно, что введён промокод "
    "<b>pestona</b> (подойдут кружок, видеофайл или ссылка на ролик).\n\n"
    "Форму в игре нужно заполнить как обычно; в подтверждении мы проверяем, что промокод указан верно."
)

# user_id -> {"stage": "idle"|"static"|"proof", "static_line": str|None}
flow: dict[int, dict] = {}

# admin_id -> "broadcast" когда ждём текст рассылки
admin_pending: dict[int, str] = {}

_banned_cache: list[str] | None = None


def _load_banned_substrings() -> list[str]:
    out: list[str] = []
    if not BANNED_WORDS_FILE.is_file():
        return out
    try:
        raw = BANNED_WORDS_FILE.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def get_banned_substrings() -> list[str]:
    global _banned_cache
    if _banned_cache is None:
        _banned_cache = _load_banned_substrings()
    return _banned_cache


def _collapse_spaced_insults(s: str) -> str:
    """Убираем пробелы/точки между буквами для грубого обхода 'х у й'."""
    return re.sub(r"[\s_·.]+", "", s.lower())


def text_has_banned_content(text: str) -> bool:
    if not text or not text.strip():
        return False
    low = text.lower()
    collapsed = _collapse_spaced_insults(text)
    for chunk in (low, collapsed):
        for bad in get_banned_substrings():
            if len(bad) < 2:
                continue
            if bad in chunk:
                return True
    return False


def _has_bad_unicode_noise(text: str) -> bool:
    """Злоупотребление комбинирующими символами / непечатным мусором."""
    if len(text) < 8:
        return False
    bad = 0
    for c in text:
        o = ord(c)
        if unicodedata.category(c) in ("Cf", "Mn", "Me"):
            bad += 1
        elif o > 0x2000 and o not in (0x2013, 0x2014, 0x2019, 0x2032):
            if unicodedata.category(c).startswith("C"):
                bad += 1
    return bad / max(len(text), 1) > 0.25


def static_line_valid(text: str) -> tuple[bool, str]:
    t = text.strip()
    if len(t) < 3:
        return False, "short"
    if len(t) > STATIC_LINE_MAX_LEN:
        return False, "long"
    if re.search(r"https?://|t\.me/", t, re.I):
        return False, "link"
    if text_has_banned_content(t) or _has_bad_unicode_noise(t):
        return False, "banned"
    if not _STATIC_ALLOWED.match(t):
        return False, "chars"
    return True, ""


def caption_or_comment_ok(text: str | None) -> bool:
    if not text or not str(text).strip():
        return True
    t = str(text).strip()
    if text_has_banned_content(t) or _has_bad_unicode_noise(t):
        return False
    return True


def _load_text_caption() -> str:
    try:
        raw = CAPTION_FILE.read_text(encoding="utf-8").strip()
        if raw:
            return raw
    except OSError:
        pass
    return (
        "✳️ ВВЕДИ ПРОМОКОД <b>pestona</b> и получи поддержку от меня 🌟\n\n"
        "При достижении 5 уровня персонажа на любом из серверов GTA5RP — бонусы по условиям промо."
    )


PROMO_CAPTION = _load_text_caption()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def _save_json(path: Path, data) -> None:
    _ensure_data_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def register_user(user_id: int) -> None:
    _ensure_data_dir()
    data = _load_json(USERS_FILE, {"ids": []})
    ids: list = data.get("ids", [])
    if user_id not in ids:
        ids.append(user_id)
        data["ids"] = ids
        _save_json(USERS_FILE, data)


def all_user_ids() -> list[int]:
    data = _load_json(USERS_FILE, {"ids": []})
    return [int(x) for x in data.get("ids", []) if str(x).isdigit()]


def _load_submissions() -> dict:
    return _load_json(SUBMISSIONS_FILE, {"next_id": 1, "items": []})


def _save_submissions(data: dict) -> None:
    _save_json(SUBMISSIONS_FILE, data)


def add_submission(
    user_id: int,
    username: str | None,
    first_name: str | None,
    static_line: str,
    proof_kind: str,
    proof_ref: str,
    message_id: int | None,
) -> int:
    data = _load_submissions()
    sid = int(data.get("next_id", 1))
    item = {
        "id": sid,
        "user_id": user_id,
        "username": username or "",
        "first_name": first_name or "",
        "static_server": static_line,
        "proof_kind": proof_kind,
        "proof_ref": proof_ref,
        "source_message_id": message_id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    data.setdefault("items", []).append(item)
    data["next_id"] = sid + 1
    _save_submissions(data)
    return sid


def get_submission(sid: int) -> dict | None:
    data = _load_submissions()
    for it in data.get("items", []):
        if int(it.get("id", 0)) == sid:
            return it
    return None


def set_submission_status(sid: int, status: str) -> bool:
    data = _load_submissions()
    changed = False
    for it in data.get("items", []):
        if int(it.get("id", 0)) == sid:
            it["status"] = status
            changed = True
            break
    if changed:
        _save_submissions(data)
    return changed


def pending_submissions() -> list[dict]:
    data = _load_submissions()
    return [it for it in data.get("items", []) if it.get("status") == "pending"]


def main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_SUBMIT], [BTN_HOWTO]],
        resize_keyboard=True,
    )


def admin_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["📋 Заявки на модерацию", "📊 Статистика"],
            ["📣 Рассылка всем", "◀️ Закрыть админку"],
        ],
        resize_keyboard=True,
    )


def _fmt_user_line(uid: int, un: str | None, fn: str | None) -> str:
    parts = []
    if fn:
        parts.append(html_escape(fn))
    if un:
        parts.append(html_escape("@" + un))
    parts.append(f"id <code>{uid}</code>")
    return " · ".join(parts)


async def send_promo_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    banner_path = BASE_DIR / PROMO_BANNER
    caption = PROMO_CAPTION
    if len(caption) > 1024:
        caption = caption[:1020] + "…"
    if banner_path.is_file():
        with open(banner_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=caption,
                parse_mode="HTML",
            )
    else:
        await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    register_user(uid)
    flow[uid] = {"stage": "idle", "static_line": None}
    admin_pending.pop(uid, None)

    await send_promo_block(update, context)
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_reply_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    uid = update.effective_user.id
    kb = main_menu_reply_keyboard() if uid not in ADMIN_IDS else None
    await update.message.reply_text(
        "Команды:\n/start — меню и промо\n/cancel — сбросить ввод заявки\n\n"
        "Кнопки снизу: «" + BTN_SUBMIT + "» и «" + BTN_HOWTO + "». "
        "Дальше — статик и сервер, затем фото или видео с промокодом pestona (или ссылка).",
        reply_markup=kb,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    flow[uid] = {"stage": "idle", "static_line": None}
    await update.message.reply_text(
        "Ввод сброшен.",
        reply_markup=main_menu_reply_keyboard(),
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("Нет доступа.")
        return
    admin_pending.pop(uid, None)
    await update.message.reply_text(
        "Админ-панель. Выбери действие кнопками ниже.",
        reply_markup=admin_reply_keyboard(),
    )


def _is_video_document(m) -> bool:
    if not m.document:
        return False
    mime = (m.document.mime_type or "").lower()
    return mime.startswith("video/")


def _text_has_video_url(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if not re.search(r"https?://", t, re.I):
        return False
    low = t.lower()
    if any(x in low for x in ("youtube.com", "youtu.be", "vk.com", "vkvideo", "t.me/", "rutube")):
        return True
    return True


async def callback_submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.from_user or not q.message:
        return
    await q.answer()
    uid = q.from_user.id
    register_user(uid)
    flow[uid] = {"stage": "static", "static_line": None}
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await q.message.reply_text(
        "Отправь <b>одним сообщением</b> статик и сервер.\n"
        "Пример: <code>12345 La Puerta</code>"
        + MSG_FLOW_NO_MENU,
        parse_mode="HTML",
        reply_markup=HIDDEN_MENU,
    )


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    msg = update.message
    text = (msg.text or "").strip()

    if uid in ADMIN_IDS and text in (
        "📋 Заявки на модерацию",
        "📊 Статистика",
        "📣 Рассылка всем",
        "◀️ Закрыть админку",
    ):
        await handle_admin_menu_text(update, context)
        return

    if uid in admin_pending and admin_pending.get(uid) == "broadcast":
        if uid in ADMIN_IDS:
            await run_broadcast(update, context, text)
        return

    st = flow.get(uid, {"stage": "idle", "static_line": None})

    if text == BTN_HOWTO:
        await msg.reply_text(
            HOWTO_TEXT,
            parse_mode="HTML",
            reply_markup=main_menu_reply_keyboard(),
        )
        return

    if text == BTN_SUBMIT:
        flow[uid] = {"stage": "static", "static_line": None}
        await msg.reply_text(
            "Отправь <b>одним сообщением</b> статик и сервер.\n"
            "Пример: <code>12345 La Puerta</code>"
            + MSG_FLOW_NO_MENU,
            parse_mode="HTML",
            reply_markup=HIDDEN_MENU,
        )
        return

    if st.get("stage") == "static":
        if not text:
            await msg.reply_text(
                "Нужен текст: статик и сервер одной строкой." + MSG_FLOW_NO_MENU,
                parse_mode="HTML",
                reply_markup=HIDDEN_MENU,
            )
            return
        ok, reason = static_line_valid(text)
        if not ok:
            if reason == "banned":
                err = MSG_REJECT_BANNED
            elif reason == "link":
                err = "Не вставляй ссылки в эту строку — только статик и название сервера."
            elif reason == "long":
                err = f"Слишком длинно (максимум {STATIC_LINE_MAX_LEN} символов)."
            elif reason == "chars":
                err = MSG_REJECT_STATIC_FORMAT
            else:
                err = "Слишком коротко. Укажи статик и сервер понятнее."
            await msg.reply_text(
                err + MSG_FLOW_NO_MENU,
                parse_mode="HTML",
                reply_markup=HIDDEN_MENU,
            )
            return
        flow[uid] = {"stage": "proof", "static_line": text}
        await msg.reply_text(
            f"Принято: <b>{html_escape(text)}</b>\n\n"
            "Теперь отправь подтверждение: <b>фото или видео</b>, где на экране видно промокод "
            "<b>pestona</b> (можно кружок, файл или ссылку на ролик — YouTube, VK и т.п.)."
            + MSG_FLOW_NO_MENU,
            parse_mode="HTML",
            reply_markup=HIDDEN_MENU,
        )
        return

    if st.get("stage") == "proof":
        static_line = st.get("static_line") or ""
        proof_kind = ""
        proof_ref = ""

        cap = msg.caption or ""
        if not caption_or_comment_ok(cap):
            await msg.reply_text(
                MSG_REJECT_BANNED + MSG_FLOW_NO_MENU,
                parse_mode="HTML",
                reply_markup=HIDDEN_MENU,
            )
            return

        if msg.photo:
            proof_kind = "photo"
            proof_ref = msg.photo[-1].file_id
        elif msg.video:
            proof_kind = "video"
            proof_ref = msg.video.file_id
        elif msg.video_note:
            proof_kind = "video_note"
            proof_ref = msg.video_note.file_id
        elif _is_video_document(msg):
            proof_kind = "document"
            proof_ref = msg.document.file_id
        elif msg.document and (msg.document.mime_type or "").lower().startswith("image/"):
            proof_kind = "image"
            proof_ref = msg.document.file_id
        elif text and _text_has_video_url(text):
            if text_has_banned_content(text) or _has_bad_unicode_noise(text):
                await msg.reply_text(
                    MSG_REJECT_BANNED + MSG_FLOW_NO_MENU,
                    parse_mode="HTML",
                    reply_markup=HIDDEN_MENU,
                )
                return
            proof_kind = "url"
            proof_ref = text
        else:
            await msg.reply_text(
                "Нужно фото, видео, видеокружок, видеофайл, картинку файлом или ссылку на видео."
                + MSG_FLOW_NO_MENU,
                parse_mode="HTML",
                reply_markup=HIDDEN_MENU,
            )
            return

        sid = add_submission(
            user_id=uid,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            static_line=static_line,
            proof_kind=proof_kind,
            proof_ref=proof_ref,
            message_id=msg.message_id,
        )
        flow[uid] = {"stage": "idle", "static_line": None}

        await msg.reply_text(
            f"Заявка <b>#{sid}</b> отправлена на проверку. Ожидай ответа.",
            parse_mode="HTML",
            reply_markup=main_menu_reply_keyboard(),
        )
        await notify_admins_new_submission(update, context, sid)
        return

    hint = (
        "Нажми /start или кнопки внизу экрана."
        if uid not in ADMIN_IDS
        else "Нажми /start для меню или /admin для панели."
    )
    await msg.reply_text(
        hint,
        reply_markup=main_menu_reply_keyboard() if uid not in ADMIN_IDS else None,
    )


async def notify_admins_new_submission(
    update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int
) -> None:
    item = get_submission(sid)
    if not item or not update.message:
        return
    u = update.effective_user
    header = (
        f"🆕 Заявка <b>#{sid}</b>\n"
        f"От: {_fmt_user_line(u.id, u.username, u.first_name)}\n"
        f"Статик + сервер:\n<code>{html_escape(item['static_server'])}</code>\n"
        f"Тип: <b>{html_escape(str(item['proof_kind']))}</b>"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Принять", callback_data=f"ap_{sid}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"rj_{sid}"),
            ]
        ]
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=aid, text=header, parse_mode="HTML", reply_markup=kb
            )
            await context.bot.forward_message(
                chat_id=aid,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
        except Exception as e:
            log.warning("admin notify %s: %s", aid, e)


async def callback_moderate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data or not q.from_user:
        return
    if q.from_user.id not in ADMIN_IDS:
        await q.answer("Нет доступа", show_alert=True)
        return

    data = q.data
    if data.startswith("ap_"):
        sid = int(data[3:])
        action = "approved"
        user_text = "Заявка принята ✅ Свяжусь с тобой при необходимости."
    elif data.startswith("rj_"):
        sid = int(data[3:])
        action = "rejected"
        user_text = "Заявка отклонена ❌ Если это ошибка, оформи заново через /start."
    else:
        await q.answer()
        return

    item = get_submission(sid)
    if not item:
        await q.answer("Заявка не найдена", show_alert=True)
        return
    if item.get("status") != "pending":
        await q.answer("Уже обработана", show_alert=True)
        return

    set_submission_status(sid, action)
    await q.answer("Сохранено")
    try:
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(f"Заявка #{sid} → {action}")
    except Exception:
        pass

    target = int(item["user_id"])
    try:
        await context.bot.send_message(chat_id=target, text=user_text)
    except Exception as e:
        log.warning("notify user %s: %s", target, e)


async def handle_admin_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    if text == "◀️ Закрыть админку":
        admin_pending.pop(uid, None)
        await update.message.reply_text("Админка закрыта.", reply_markup=ReplyKeyboardRemove())
        return

    if text == "📊 Статистика":
        users = all_user_ids()
        items = _load_submissions().get("items", [])
        pend = sum(1 for x in items if x.get("status") == "pending")
        ok = sum(1 for x in items if x.get("status") == "approved")
        bad = sum(1 for x in items if x.get("status") == "rejected")
        await update.message.reply_text(
            f"Пользователей в базе: <b>{len(users)}</b>\n"
            f"Заявок всего: <b>{len(items)}</b>\n"
            f"Ожидают: <b>{pend}</b>\n"
            f"Принято: <b>{ok}</b>\n"
            f"Отклонено: <b>{bad}</b>",
            parse_mode="HTML",
        )
        return

    if text == "📋 Заявки на модерацию":
        pend = pending_submissions()
        if not pend:
            await update.message.reply_text("Нет заявок в ожидании.")
            return
        for it in pend[-10:]:
            sid = int(it["id"])
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Принять", callback_data=f"ap_{sid}"),
                        InlineKeyboardButton("❌ Отклонить", callback_data=f"rj_{sid}"),
                    ]
                ]
            )
            preview = (
                f"#{sid} · {_fmt_user_line(int(it['user_id']), it.get('username'), it.get('first_name'))}\n"
                f"<code>{html_escape(str(it.get('static_server', '')))}</code>\n"
                f"{html_escape(str(it.get('proof_kind', '')))} · {html_escape(str(it.get('created_at', '')))}"
            )
            await update.message.reply_text(
                preview, parse_mode="HTML", reply_markup=kb
            )
        return

    if text == "📣 Рассылка всем":
        admin_pending[uid] = "broadcast"
        await update.message.reply_text(
            "Пришли следующим сообщением текст (HTML допускается) — разошлю всем, кто нажимал /start."
        )
        return


async def run_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    admin_pending.pop(uid, None)
    if not text:
        await update.message.reply_text("Пустое сообщение — отменено.")
        return
    ids = all_user_ids()
    ok, fail = 0, 0
    for chat_id in ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            ok += 1
        except Exception:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
                ok += 1
            except Exception:
                fail += 1
    await update.message.reply_text(f"Рассылка завершена: доставлено {ok}, ошибок {fail}.")


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("В .env не задан BOT_TOKEN")
    if not ADMIN_IDS:
        log.warning("ADMIN_IDS пуст — модерация и админка будут недоступны")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("admin", cmd_admin))

    app.add_handler(CallbackQueryHandler(callback_submit, pattern=r"^start_submit$"))
    app.add_handler(CallbackQueryHandler(callback_moderate, pattern=r"^(ap|rj)_\d+$"))

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_user_message,
        )
    )

    log.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
