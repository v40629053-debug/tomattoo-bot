# -*- coding: utf-8 -*-
"""
Telegram-бот кулинарной школы ToMattoo.
Реализация по ТЗ: меню, каталог, акции, контакты, пошаговый сбор заявок
(согласие на ПД -> имя -> телефон -> комментарий -> действие)
и передача лидов в Битрикс24.
"""

import logging
import re
import time
import uuid

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
)

import config

# Стадии (состояния) заявки
S_IDLE = "idle"          # ничего не собираем
S_CONSENT = "consent"    # ждём согласие на ПД (inline)
S_NAME = "name"          # ждём имя
S_PHONE = "phone"        # ждём телефон
S_COMMENT = "comment"    # ждём комментарий (или пропуск)
S_ACTION = "action"      # ждём: записаться / акции

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def build_reply_keyboard():
    """Клавиатура основного меню (Reply-кнопки)."""
    return ReplyKeyboardMarkup(config.REPLY_KEYBOARD, resize_keyboard=True)


# ---------------------------------------------------------------
# Служебные функции
# ---------------------------------------------------------------
def validate_phone_soft(phone):
    """Мягкая проверка телефона: минимум 10 цифр."""
    digits = re.sub(r"\D", "", phone or "")
    return len(digits) >= 10


def create_crm_lead(name, phone, comment):
    """Передаёт лид в Битрикс24 методом crm.lead.add.json (POST)."""
    payload = {
        "fields[TITLE]": f"Заявка с Telegram — {name}",
        "fields[NAME]": name,
        "fields[PHONE][0][VALUE]": phone,
        "fields[PHONE][0][VALUE_TYPE]": "HOME",
        "fields[COMMENTS]": comment,
        "fields[SOURCE_ID]": config.BITRIX24_SOURCE_ID,
        "fields[ASSIGNED_BY_ID]": config.BITRIX24_USER_ID,
    }
    try:
        logger.info("Отправка лида в Битрикс24: %s", phone)
        response = requests.post(
            config.BITRIX24_LEAD_ADD_URL,
            data=payload,
            timeout=15,
            proxies={"http": None, "https": None},
        )
        response.raise_for_status()
        data = response.json()
        if "result" in data:
            logger.info("Лид создан, ID=%s", data["result"])
            return {"ok": True, "lead_id": data["result"]}
        logger.error("Битрикс24 вернул ошибку: %s", data)
        return {"ok": False, "error": data.get("error", "unknown"), "detail": data.get("error_description", "")}
    except requests.exceptions.RequestException as exc:
        logger.error("Ошибка сети при обращении к Битрикс24: %s", exc)
        return {"ok": False, "error": "network", "detail": str(exc)}


def generate_request_number():
    """Уникальный номер заявки."""
    return f"TG-{int(time.time())}-{uuid.uuid4().hex[:6].upper()}"


def consent_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(config.CONSENT_AGREE, callback_data="consent_yes")],
            [InlineKeyboardButton(config.CONSENT_DISAGREE, callback_data="consent_no")],
        ]
    )


def action_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(config.ACTION_BOOK, callback_data="action_book")],
            [InlineKeyboardButton(config.ACTION_PROMO, callback_data="action_promo")],
        ]
    )


def is_menu_label(text):
    """Является ли текст одной из Reply-кнопок меню."""
    return text in config.REPLY_KEYBOARD_FLAT


# ---------------------------------------------------------------
# Действия меню
# ---------------------------------------------------------------
def do_menu(update, context, text):
    """Обрабатывает Reply-кнопку, которая не является стартом заявки."""
    message = update.message
    if text == config.MENU_ABOUT:
        try:
            with open(config.FOUNDER_PHOTO_PATH, "rb") as photo:
                message.reply_photo(
                    photo=photo,
                    caption=f"{config.ABOUT_SCHOOL_TEXT}\n\n{config.FOUNDER_TEXT}",
                )
        except FileNotFoundError:
            message.reply_text(f"{config.ABOUT_SCHOOL_TEXT}\n\n{config.FOUNDER_TEXT}")

    elif text == config.MENU_CATALOG:
        try:
            with open(config.CATALOG_PATH, "rb") as pdf:
                message.reply_document(
                    document=pdf,
                    filename="Каталог_курсов_ToMattoo.pdf",
                    caption=config.CATALOG_PROMPT,
                )
        except FileNotFoundError:
            message.reply_text(
                "📚 Каталог курсов скоро появится! А пока напиши боту и подбери курс за минуту."
            )

    elif text == config.MENU_PROMO:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Оставить заявку на пробный урок", callback_data="request_start")]]
        )
        message.reply_text(config.PROMO_TEXT, reply_markup=keyboard)

    elif text == config.MENU_CONTACTS:
        site_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🌐 Открыть сайт ToMattoo", url=config.SITE_URL)]]
        )
        message.reply_text(config.CONTACTS_TEXT, reply_markup=site_kb)

    elif text == config.MENU_SITE:
        site_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🌐 Открыть сайт ToMattoo", url=config.SITE_URL)]]
        )
        message.reply_text(config.SITE_TEXT, reply_markup=site_kb)

    elif text == config.MENU_PICK:
        start_pick(update, context)


# ---------------------------------------------------------------
# Подбор курса (анкета — шаги 1–3, результат)
# ---------------------------------------------------------------
# Стадии подбора
P_LEVEL = "pick_level"
P_CUISINE = "pick_cuisine"
P_TIME = "pick_time"
P_DONE = "pick_done"

def start_pick(update, context):
    """Начало подбора: шаг 1 — уровень."""
    context.user_data["pick"] = {}
    context.user_data["pick_stage"] = P_LEVEL
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(config.LEVEL_NEWBIE, callback_data="pick_l_newbie")],
            [InlineKeyboardButton(config.LEVEL_HOME, callback_data="pick_l_home")],
            [InlineKeyboardButton(config.LEVEL_PRO, callback_data="pick_l_pro")],
        ]
    )
    update.message.reply_text(config.PICK_INTRO + "\n\n" + config.PICK_LEVEL_QUESTION, reply_markup=kb)


def pick_handle_callback(data, query, context):
    """Обработка inline-кнопок подбора в зависимости от стадии."""
    stage = context.user_data.get("pick_stage")
    pick = context.user_data.setdefault("pick", {})

    if data.startswith("pick_l_"):
        # Шаг 1: уровень -> шаг 2 кухня
        pick["level"] = data.replace("pick_l_", "")
        context.user_data["pick_stage"] = P_CUISINE
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(config.CUISINE_IT, callback_data="pick_c_it")],
                [InlineKeyboardButton(config.CUISINE_ASIA, callback_data="pick_c_asia")],
                [InlineKeyboardButton(config.CUISINE_DESSERT, callback_data="pick_c_dessert")],
                [InlineKeyboardButton(config.CUISINE_ANY, callback_data="pick_c_any")],
            ]
        )
        query.edit_message_text(config.PICK_CHOICE_QUESTION, reply_markup=kb)

    elif data.startswith("pick_c_"):
        # Шаг 2: кухня -> шаг 3 время
        pick["cuisine"] = data.replace("pick_c_", "")
        context.user_data["pick_stage"] = P_TIME
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(config.TIME_MORNING, callback_data="pick_t_morning")],
                [InlineKeyboardButton(config.TIME_EVENING, callback_data="pick_t_evening")],
                [InlineKeyboardButton(config.TIME_WEEKEND, callback_data="pick_t_weekend")],
            ]
        )
        query.edit_message_text(config.PICK_TIME_QUESTION, reply_markup=kb)

    elif data.startswith("pick_t_"):
        # Шаг 3: время -> результат
        pick["time"] = data.replace("pick_t_", "")
        context.user_data["pick_stage"] = P_DONE
        recommended = recommend_courses(pick)
        if recommended:
            text = config.PICK_RESULT_TITLE
            for i, name in enumerate(recommended, 1):
                info = config.COURSES_DATA[name]
                text += f"{i}. {name} — {info['desc']}\n"
            text += "\n" + config.PICK_FINISH
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(config.PICK_BOOK, callback_data="request_start")]]
            )
            query.edit_message_text(text, reply_markup=kb)
        else:
            query.edit_message_text(config.PICK_NO_MATCH)


def recommend_courses(pick):
    """Подбирает 2–3 курса по выборам анкеты."""
    level = pick.get("level")
    cuisine = pick.get("cuisine")
    time_ = pick.get("time")

    matched = []
    for name, tags in config.COURSES_DATA.items():
        if level in tags["levels"] and cuisine in tags["cuisines"] and time_ in tags["times"]:
            matched.append(name)

    # Если полных совпадений меньше 2 — дополняем по кухне + уровню
    if len(matched) < 2:
        for name, tags in config.COURSES_DATA.items():
            if name in matched:
                continue
            cuisine_ok = cuisine in tags["cuisines"] or (cuisine == "any" and "any" in tags["cuisines"])
            if cuisine_ok and level in tags["levels"]:
                matched.append(name)

    # Если всё ещё мало — добавляем по уровню (любая кухня)
    if len(matched) < 2:
        for name, tags in config.COURSES_DATA.items():
            if name in matched:
                continue
            if level in tags["levels"]:
                matched.append(name)

    return matched[:3]


# ---------------------------------------------------------------
# Старт заявки (через меню или inline-кнопку «Акций»)
# ---------------------------------------------------------------
def begin_request(message_or_query, context):
    """Начинает сбор заявки: запрашиваем согласие на ПД.

    Принимает либо Message (из текстового обработчика),
    либо CallbackQuery (из inline-кнопки заявки/подбора).
    """
    context.user_data["stage"] = S_CONSENT
    context.user_data["draft"] = {"comment": "—"}
    # Различаем объект: у Message есть .reply_text, у CallbackQuery есть .message
    target = message_or_query if hasattr(message_or_query, "reply_text") else message_or_query.message
    return target.reply_text(config.CONSENT_NEEDED, reply_markup=consent_keyboard())


# ---------------------------------------------------------------
# Текстовый обработчик (все текстовые сообщения)
# ---------------------------------------------------------------
def on_message(update: Update, context):
    """Главный обработчик текста: Reply-меню и шаги заявки."""
    text = update.message.text
    stage = context.user_data.get("stage", S_IDLE)

    # Приоритет: Reply-кнопки меню — ВСЕГДА выполняются как команды.
    # Это исключает ситуацию, когда текст кнопки уходит в заявку.
    if is_menu_label(text):
        if text == config.MENU_REQUEST:
            # Заявка: либо начинаем, либо (если уже идёт) перезапускаем
            begin_request(update.message, context)
        else:
            do_menu(update, context, text)
        return

    # --- Шаги заявки (если menu не сработал) ---
    if stage == S_CONSENT:
        # Ждём inline-кнопку согласия
        update.message.reply_text(
            "Пожалуйста, нажмите кнопку «Согласен» или «Не согласен» под моим вопросом."
        )
        return

    elif stage == S_NAME:
        name = text.strip()
        if not name:
            update.message.reply_text("Пожалуйста, напишите ваше имя:")
            return
        context.user_data.setdefault("draft", {})["name"] = name
        context.user_data["stage"] = S_PHONE
        update.message.reply_text(config.ASK_PHONE)

    elif stage == S_PHONE:
        phone = text.strip()
        if not validate_phone_soft(phone):
            update.message.reply_text(config.PHONE_TOO_SHORT)
            return
        context.user_data.setdefault("draft", {})["phone"] = phone
        context.user_data["stage"] = S_COMMENT
        skip_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Пропустить", callback_data="skip_comment")]])
        update.message.reply_text(config.ASK_COMMENT, reply_markup=skip_kb)

    elif stage == S_COMMENT:
        context.user_data.setdefault("draft", {})["comment"] = text.strip() or "—"
        context.user_data["stage"] = S_ACTION
        update.message.reply_text(config.ASK_ACTION, reply_markup=action_keyboard())

    elif stage == S_ACTION:
        update.message.reply_text(
            "Нажмите кнопку «Записаться на курс» или «Посмотреть акции» ниже.",
            reply_markup=action_keyboard(),
        )

    else:
        # idle — неизвестный текст
        update.message.reply_text(
            "Я тебя немного не понял 😅 Выбери пункт в меню ниже.",
            reply_markup=build_reply_keyboard(),
        )


# ---------------------------------------------------------------
# Обработчики inline-кнопок
# ---------------------------------------------------------------
def on_callback(update, context):
    query = update.callback_query
    query.answer()
    data = query.data

    # Подбор курса (анкета)
    if data.startswith("pick_l_") or data.startswith("pick_c_") or data.startswith("pick_t_"):
        pick_handle_callback(data, query, context)
        return

    if data == "consent_yes":
        context.user_data["stage"] = S_NAME
        query.edit_message_text("✅ Согласие получено. Приступим!\n\n" + config.ASK_NAME)

    elif data == "consent_no":
        context.user_data.clear()
        query.edit_message_text(config.CONSENT_DENIED)
        query.message.reply_text(
            "Если захотите оставить заявку — просто нажмите «Оставить заявку» в меню.",
            reply_markup=build_reply_keyboard(),
        )

    elif data == "skip_comment":
        context.user_data.setdefault("draft", {})["comment"] = "—"
        context.user_data["stage"] = S_ACTION
        query.edit_message_text("Комментарий не добавлен.")
        query.message.reply_text(config.ASK_ACTION, reply_markup=action_keyboard())

    elif data == "action_book":
        finish_request(query, context)

    elif data == "action_promo":
        context.user_data["saved_request"] = True
        promo_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Оставить заявку на пробный урок", callback_data="request_start")]]
        )
        query.edit_message_text(config.PROMO_TEXT, reply_markup=promo_kb)

    elif data == "request_start":
        # Кнопка «Оставить заявку» из блока «Акции»
        begin_request(query, context)


def finish_request(query, context):
    """Отправка лида в CRM и подтверждение пользователю."""
    draft = context.user_data.get("draft", {})
    name = draft.get("name", "")
    phone = draft.get("phone", "")
    comment = draft.get("comment", "—")

    query.edit_message_text("⏳ Отправляю заявку...")

    if not name or not phone:
        context.user_data.clear()
        query.message.reply_text(
            "Произошла ошибка: не хватает данных. Начните заявку заново.",
            reply_markup=build_reply_keyboard(),
        )
        return

    comment_with_consent = f"{comment}\nПодтверждено согласие на обработку ПД: да"
    result = create_crm_lead(name, phone, comment_with_consent)

    if result and result.get("ok"):
        request_number = generate_request_number()
        query.message.reply_text(
            f"✅ Заявка создана!\n\n"
            f"Ваш номер заявки: {request_number}\n\n"
            f"Данные:\n"
            f"👤 Имя: {name}\n"
            f"📞 Телефон: {phone}\n"
            f"💬 Комментарий: {comment}\n\n"
            f"Мы свяжемся с вами в ближайшее время. Спасибо, что выбрали ToMattoo! 🍅",
            reply_markup=build_reply_keyboard(),
        )
        logger.info("Заявка %s от %s успешно отправлена", request_number, phone)
    else:
        detail = ""
        if result:
            detail = f"\n({result.get('error', '')})"
        query.message.reply_text(
            "😔 Что-то пошло не так при отправке заявки. Попробуйте ещё раз чуть позже" + detail,
            reply_markup=build_reply_keyboard(),
        )

    context.user_data.clear()
    query.message.reply_text(
        "Выберите следующий пункт меню:", reply_markup=build_reply_keyboard()
    )


# ---------------------------------------------------------------
# Команды
# ---------------------------------------------------------------
def start(update, context):
    context.user_data.clear()
    update.message.reply_text(config.START_TEXT, reply_markup=build_reply_keyboard())
    logger.info("Пользователь %s запустил бота", update.effective_user.id)


def cancel(update, context):
    context.user_data.clear()
    update.message.reply_text(
        "Заявка отменена. Выберите пункт меню.", reply_markup=build_reply_keyboard()
    )


def main():
    updater = Updater(config.TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("cancel", cancel))
    dp.add_handler(CallbackQueryHandler(on_callback))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, on_message))

    logger.info("Бот запущен")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
