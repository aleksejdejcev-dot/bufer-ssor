"""
Модуль Telegram-бота на aiogram 3.x.
Работает в режиме Webhook с проверкой секрета X-Telegram-Bot-Api-Secret-Token.

ПРАВИЛА БЕЗОПАСНОСТИ И КОНФИДЕНЦИАЛЬНОСТИ:
- Никаких персональных текстов и расшифрованных данных в логах.
- Скачанные аудиофайлы (.ogg) обрабатываются исключительно в оперативной памяти (io.BytesIO)
  и сразу шифруются через Fernet перед записью в pending_inputs. На диск ничего не сохраняется!
- Имена партнеров берутся строго из first_name.
"""

import io
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from aiogram.enums import ParseMode

from config import settings
import crypto
import db
from providers import get_provider
from ai_service import analyze_session

logger = logging.getLogger(__name__)

bot_token = settings.TELEGRAM_BOT_TOKEN
if not bot_token or ":" not in bot_token:
    bot_token = "123456789:dummy_token_placeholder_for_tests_35c"
bot = Bot(token=bot_token)
dp = Dispatcher()
router = Router()
dp.include_router(router)


def get_miniapp_keyboard(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    """Кнопка для открытия Telegram Mini App и админ-панели"""
    url = settings.MINIAPP_URL or "http://localhost:8000"
    buttons = []
    if url.startswith("https://t.me/"):
        buttons.append([InlineKeyboardButton(text="Открыть Буфер Ссор 💬", url=url)])
    else:
        buttons.append([InlineKeyboardButton(text="Открыть Буфер Ссор 💬", web_app=WebAppInfo(url=url))])

    if is_admin_user:
        buttons.append([InlineKeyboardButton(text="👑 Панель управления", callback_data="admin_stats")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==============================================================================
# Функции и клавиатуры панели администратора
# ==============================================================================

_authorized_admin_ids = set()


def is_admin(telegram_id: int) -> bool:
    """Проверка прав администратора бота"""
    if telegram_id in _authorized_admin_ids:
        return True

    raw_ids = getattr(settings, "ADMIN_TELEGRAM_IDS", "") or ""
    allowed_ids = [int(x.strip()) for x in raw_ids.replace(";", ",").split(",") if x.strip().isdigit()]
    return telegram_id in allowed_ids


def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура админки"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить сводку", callback_data="admin_stats"),
                InlineKeyboardButton(text="👥 Список пар", callback_data="admin_couples"),
            ],
            [
                InlineKeyboardButton(text="🚪 Закрыть панель", callback_data="admin_close"),
            ],
        ]
    )


def format_admin_stats_text() -> str:
    """Форматирование аналитической сводки для админа"""
    stats = db.get_admin_stats()
    return (
        "👑 <b>Панель администратора «Буфер Ссор»</b>\n\n"
        "👥 <b>Пользователи и пары:</b>\n"
        f"• Всего зарегистрировано: <b>{stats['total_users']}</b>\n"
        f"• Всего создано пар: <b>{stats['total_couples']}</b>\n"
        f"• Активных пар (оба партнёра): <b>{stats['paired_couples']}</b>\n"
        f"• Ожидают подключения: <b>{stats['waiting_couples']}</b>\n\n"
        "💬 <b>Сессии и разборы конфликтов:</b>\n"
        f"• Всего запущено: <b>{stats['total_sessions']}</b>\n"
        f"• Успешно завершено: <b>{stats['completed_sessions']}</b>\n"
        f"• В процессе ожидания/анализа: <b>{stats['active_sessions']}</b>\n"
        f"• Случаев высокого риска (кризис): <b>{stats['high_risk_sessions']}</b>\n\n"
        "🔒 <i>Режим тайны исповеди: личные аудиозаписи и тексты шифруются и не отображаются.</i>"
    )


# ==============================================================================
# Обработчик /start
# ==============================================================================

@router.message(CommandStart())
async def handle_start(message: Message, command: CommandObject):
    telegram_id = message.from_user.id
    first_name = message.from_user.first_name or "Партнер"

    # Регистрируем/обновляем пользователя
    user = db.upsert_user(telegram_id=telegram_id, first_name=first_name)

    args = command.args

    # Сценарий 1: Пользователь перешел по инвайт-ссылке (pair_XXXX)
    if args and args.startswith("pair_"):
        invite_code = args.replace("pair_", "").strip().upper()

        # 0. Защита от брутфорса: 5 неверных попыток за час -> блокировка ввода инвайтов на 1 час
        is_blocked, retry_after = db.check_invite_bruteforce(telegram_id)
        if is_blocked:
            minutes = max(1, (retry_after + 59) // 60)
            await message.answer(
                f"❌ Слишком много неверных попыток ввода инвайта. Ввод заблокирован на {minutes} мин.",
                reply_markup=get_miniapp_keyboard(),
            )
            return

        # 1. Проверяем принятие условий (18+)
        if not user.get("accepted_legal_at"):
            await message.answer(
                "Прежде чем присоединиться к паре, необходимо подтвердить возраст 18+ "
                "и согласиться с правилами сервиса в приложении.\n\n"
                "Сервис не является психотерапией и служит помощником для спокойной коммуникации в паре.",
                reply_markup=get_miniapp_keyboard(),
            )
            return

        # 2. Ищем пару по коду приглашения
        couple = db.get_couple_by_invite(invite_code)
        if not couple:
            db.record_failed_invite_attempt(telegram_id)
            await message.answer(
                "❌ Приглашение не найдено или код недействителен. Попросите партнера прислать свежую ссылку.",
                reply_markup=get_miniapp_keyboard(),
            )
            return

        # 2.1 Проверка срока жизни инвайта (7 дней)
        expires_at = couple.get("invite_expires_at")
        if expires_at and expires_at <= datetime.now(timezone.utc).isoformat():
            await message.answer(
                "❌ Срок действия инвайта истёк, попросите партнёра создать новый.",
                reply_markup=get_miniapp_keyboard(),
            )
            return

        # 3. Проверка: нельзя связаться с собой
        if couple["partner_1_id"] == telegram_id:
            await message.answer(
                "Вы не можете объединиться в пару с самим собой 🙂 Перешлите эту ссылку вашей половинке.",
                reply_markup=get_miniapp_keyboard(),
            )
            return

        # 4. Проверка: пара уже заполнена (одноразовость)
        if couple.get("partner_2_id"):
            await message.answer(
                "К этой паре уже присоединился партнер. Этот код приглашения уже был использован.",
                reply_markup=get_miniapp_keyboard(),
            )
            return

        # 5. Проверка: текущий пользователь уже состоит в другой паре
        existing_couple = db.get_user_couple(telegram_id)
        if existing_couple and existing_couple["id"] != couple["id"]:
            await message.answer(
                "Вы уже состоите в паре. Чтобы объединиться с новым партнером, сначала разорвите текущую связку в приложении.",
                reply_markup=get_miniapp_keyboard(),
            )
            return

        # 6. Успешная связка
        db.join_couple(couple["id"], telegram_id)
        db.reset_invite_bruteforce(telegram_id)
        partner_1 = db.get_user(couple["partner_1_id"])
        partner_1_name = partner_1["first_name"] if partner_1 else "Партнер"

        await message.answer(
            f"🎉 Вы успешно объединились в пару с <b>{partner_1_name}</b>!\n\n"
            "Теперь вы можете вместе пользоваться Буфером Ссор, делиться настроением и экологично разбирать конфликты.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_miniapp_keyboard(),
        )

        # Оповещаем Партнера 1
        try:
            await bot.send_message(
                chat_id=couple["partner_1_id"],
                text=(
                    f"🎉 <b>{first_name}</b> присоединился(-ась) к вашей паре в Буфере Ссор!\n"
                    "Теперь вы можете начинать совместные разборы и обмениваться сигналами заботы."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=get_miniapp_keyboard(),
            )
        except Exception as e:
            logger.warning("Не удалось отправить уведомление партнеру 1: %s", e)
        return

    # Сценарий 2: Обычный /start без параметров
    welcome_text = (
        f"Привет, {first_name}! 👋\n\n"
        "«Буфер Ссор» — это безопасное пространство и ИИ-медиатор для пар в ссоре.\n\n"
        "🔒 <b>Как это работает:</b>\n"
        "1. Каждый партнер отдельно и конфиденциально рассказывает свою версию (текстом или голосовым).\n"
        "2. ИИ анализирует обе стороны, никого не обвиняя.\n"
        "3. Каждый получает персональный разбор и рекомендации, а пара — общий спокойный итог.\n"
        "4. Исходные записи и тексты надежно шифруются и удаляются сразу после анализа.\n\n"
        "<i>Сервис предназначен для лиц старше 18 лет и не является психотерапией.</i>"
    )
    is_admin_user = is_admin(telegram_id)
    await message.answer(welcome_text, parse_mode=ParseMode.HTML, reply_markup=get_miniapp_keyboard(is_admin_user=is_admin_user))


# ==============================================================================
# Обработчики панели администратора (/admin)
# ==============================================================================

@router.message(Command("admin"))
async def handle_admin_command(message: Message, command: CommandObject):
    telegram_id = message.from_user.id
    secret_arg = (command.args or "").strip()
    admin_secret = getattr(settings, "ADMIN_SECRET_KEY", "") or ""

    # Вход по секретному ключу (если ключ задан и совпадает)
    if secret_arg and admin_secret and secret_arg == admin_secret:
        _authorized_admin_ids.add(telegram_id)
        await message.answer("✅ <b>Вы успешно авторизованы как администратор!</b>", parse_mode=ParseMode.HTML)

    if not is_admin(telegram_id):
        await message.answer(
            "⛔ <b>Доступ запрещён</b>\n\n"
            "Команда доступна только администраторам проекта.\n"
            f"Ваш Telegram ID: <code>{telegram_id}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    text = format_admin_stats_text()
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=get_admin_main_keyboard())


@router.callback_query(F.data == "admin_stats")
async def handle_admin_stats_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    text = format_admin_stats_text()
    try:
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=get_admin_main_keyboard())
    except Exception:
        pass
    await callback.answer("Сводка обновлена 🔄")


@router.callback_query(F.data == "admin_couples")
async def handle_admin_couples_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    couples = db.get_all_couples(limit=6)
    if not couples:
        await callback.message.edit_text(
            "👥 <b>Список пар в сервисе</b>\n\n<i>Пока нет созданных пар.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="« Назад к сводке", callback_data="admin_stats")]]
            ),
        )
        await callback.answer()
        return

    text = "👥 <b>Список зарегистрированных пар:</b>\n\n"
    buttons = []

    for i, c in enumerate(couples, 1):
        c_id = c["id"]
        code = c.get("invite_code", "------")
        p1 = c.get("partner_1_id")
        p2 = c.get("partner_2_id")
        free_left = c.get("free_sessions_left", 0)

        p1_user = db.get_user(p1) if p1 else None
        p2_user = db.get_user(p2) if p2 else None
        p1_name = p1_user["first_name"] if p1_user else f"ID {p1}"
        p2_name = (p2_user["first_name"] if p2_user else f"ID {p2}") if p2 else "ждём..."

        text += (
            f"<b>{i}. Код: <code>{code}</code></b>\n"
            f"• Партнёры: {p1_name} & {p2_name}\n"
            f"• Баланс разборов: <b>{free_left}</b>\n\n"
        )

        buttons.append([
            InlineKeyboardButton(text=f"🎁 +3 для #{code}", callback_data=f"admin_add:{c_id}:3"),
            InlineKeyboardButton(text=f"🎁 +10 для #{code}", callback_data=f"admin_add:{c_id}:10"),
        ])

    buttons.append([InlineKeyboardButton(text="« Назад к сводке", callback_data="admin_stats")])

    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_add:"))
async def handle_admin_add_sessions(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка формата данных")
        return

    couple_id = parts[1]
    try:
        count = int(parts[2])
    except ValueError:
        count = 3

    couple = db.add_free_sessions(couple_id, count)
    if not couple:
        await callback.answer("Пара не найдена", show_alert=True)
        return

    code = couple.get("invite_code", "")
    new_balance = couple.get("free_sessions_left", 0)
    await callback.answer(f"✅ Начислено +{count} разборов! Баланс: {new_balance}", show_alert=True)

    # Оповещаем партнеров о подарке от сервиса
    notify_text = (
        f"🎁 <b>Вам начислен подарок!</b>\n\n"
        f"Администратор сервиса добавил вашей паре <b>+{count} бесплатных разборов</b> ссор.\n"
        f"Текущий баланс: <b>{new_balance}</b> разборов."
    )
    for p_id in (couple.get("partner_1_id"), couple.get("partner_2_id")):
        if p_id:
            try:
                await bot.send_message(chat_id=p_id, text=notify_text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.warning("Could not notify partner %s about added sessions: %s", p_id, e)

    # Обновляем список пар
    await handle_admin_couples_callback(callback)


@router.callback_query(F.data == "admin_close")
async def handle_admin_close_callback(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


# ==============================================================================
# Прием позиции по конфликту (Голосовые и Текстовые сообщения)
# ==============================================================================

# Кэш состояния уточняющих вопросов для коротких версий (< 25 слов или < 10 сек аудио)
# Ключ: f"{session_id}:{telegram_id}"
CLARIFICATION_REQUESTED: Dict[str, bool] = {}
CLARIFICATION_SAVED_TEXT: Dict[str, str] = {}


@router.message(F.voice | F.text)
async def handle_conflict_input(message: Message):
    telegram_id = message.from_user.id
    first_name = message.from_user.first_name or "Партнер"

    # 0. Защита от флуда: не более 20 сообщений в минуту на пользователя
    allowed, retry_after = db.check_rate_limit(f"bot_msg:{telegram_id}", max_requests=20, window_seconds=60)
    if not allowed:
        await message.answer("Слишком много сообщений. Пожалуйста, подождите минуту перед следующей отправкой.")
        return

    # Проверяем, зарегистрирован ли пользователь
    user = db.get_user(telegram_id)
    if not user:
        user = db.upsert_user(telegram_id, first_name)

    # 0.1 Проверка принятия условий и возраста 18+
    if not user.get("accepted_legal_at"):
        await message.answer(
            "Прежде чем использовать сервис, необходимо подтвердить возраст 18+ "
            "и согласиться с правилами сервиса в приложении.\n\n"
            "Сервис не является психотерапией и служит помощником для спокойной коммуникации в паре.",
            reply_markup=get_miniapp_keyboard(),
        )
        return

    # 1. Проверяем наличие пары
    couple = db.get_user_couple(telegram_id)
    if not couple or not couple.get("partner_2_id"):
        await message.answer(
            "Для использования Буфера Ссор необходимо объединиться в пару со своей половинкой.\n"
            "Откройте приложение, чтобы получить ссылку-приглашение.",
            reply_markup=get_miniapp_keyboard(),
        )
        return

    # 2. Проверяем активную сессию конфликта
    session = db.get_active_session(couple["id"])
    if not session:
        await message.answer(
            "Сейчас нет активного разбора ссоры.\n"
            "Вы можете запустить новый разбор в приложении в любое удобное время.",
            reply_markup=get_miniapp_keyboard(),
        )
        return

    session_id = session["id"]

    # 3. Если статус analyzing — анализ уже идет
    if session["status"] == "analyzing":
        await message.answer(
            "Обе версии уже получены! ИИ-медиатор прямо сейчас анализирует ситуацию. "
            "Пожалуйста, подождите завершения — результат скоро появится в приложении.",
            reply_markup=get_miniapp_keyboard(),
        )
        return

    # 4. Проверяем, не отправлял ли уже этот пользователь свою версию
    if db.has_user_submitted_input(session_id, telegram_id):
        # Находим имя второго партнера
        other_id = couple["partner_2_id"] if telegram_id == couple["partner_1_id"] else couple["partner_1_id"]
        other_user = db.get_user(other_id)
        other_name = other_user["first_name"] if other_user else "партнера"

        await message.answer(
            f"Ваша версия уже принята и сохранена в зашифрованном виде. Ожидаем ответа <b>{other_name}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_miniapp_keyboard(),
        )
        return

    # 5. Обработка входящего сообщения (голосовое или текст)
    kind: str
    encrypted_payload: bytes

    if message.voice:
        provider = get_provider()
        if not provider.supports_audio:
            await message.answer("Голосовые пока недоступны, отправь, пожалуйста, текстом.")
            return

        # Проверка длительности
        if message.voice.duration > settings.MAX_VOICE_DURATION_SECONDS:
            await message.answer(
                f"Голосовое сообщение слишком длинное (максимум {settings.MAX_VOICE_DURATION_SECONDS // 60} минут). "
                "Пожалуйста, запишите более компактное сообщение с сутью ситуации."
            )
            return

        # Проверка размера файла
        if message.voice.file_size and message.voice.file_size > settings.MAX_VOICE_SIZE_BYTES:
            await message.answer("Файл голосового сообщения превышает 10 МБ. Пожалуйста, отправьте более короткую запись.")
            return

        # Скачиваем ТОЛЬКО в оперативную память (BytesIO)
        voice_io = io.BytesIO()
        try:
            await bot.download(message.voice, destination=voice_io)
            raw_audio = voice_io.getvalue()
        except Exception as e:
            logger.error("Ошибка скачивания голосового сообщения: %s", e)
            await message.answer("Не удалось загрузить голосовое сообщение. Попробуйте отправить текстом или повторить.")
            return
        finally:
            voice_io.close()

        # Шифруем байты Fernet
        encrypted_payload = crypto.encrypt_bytes(raw_audio)
        kind = "audio"

    elif message.text:
        # Шифруем текст Fernet
        encrypted_payload = crypto.encrypt_text(message.text)
        kind = "text"
    else:
        await message.answer("Пожалуйста, отправьте текстовое или голосовое сообщение.")
        return

    # Проверка на короткую версию (< 25 слов или < 10 сек аудио)
    clarification_key = f"{session_id}:{telegram_id}"
    is_short = False
    if message.voice:
        if message.voice.duration < 10:
            is_short = True
    elif message.text:
        words = len(message.text.split())
        if words < 25:
            is_short = True

    # Если версия короткая и уточняющий вопрос ещё не задавался — задаем его ОДИН раз
    if is_short and not CLARIFICATION_REQUESTED.get(clarification_key, False):
        CLARIFICATION_REQUESTED[clarification_key] = True
        if message.text:
            CLARIFICATION_SAVED_TEXT[clarification_key] = message.text
        # Сохраняем черновик в pending_inputs
        db.save_pending_input(
            session_id=session_id,
            author_telegram_id=telegram_id,
            kind=kind,
            payload_encrypted=encrypted_payload,
        )
        logger.info("Sent clarifying question for short version: session=%s, user=%s", session_id, telegram_id)
        await message.answer("Расскажи чуть подробнее: что именно произошло и чего ты хотел(а) в тот момент?")
        return

    # Если ранее был сохранен черновик и сейчас пришло дополнение текстом
    if message.text and clarification_key in CLARIFICATION_SAVED_TEXT:
        prev_text = CLARIFICATION_SAVED_TEXT.pop(clarification_key, "")
        combined_text = f"{prev_text}\n\n{message.text}"
        encrypted_payload = crypto.encrypt_text(combined_text)
        kind = "text"
        db.delete_pending_input_for_author(session_id, telegram_id)
    elif clarification_key in CLARIFICATION_REQUESTED:
        db.delete_pending_input_for_author(session_id, telegram_id)
        CLARIFICATION_SAVED_TEXT.pop(clarification_key, None)

    # 6. Сохраняем зашифрованные данные в pending_inputs
    db.save_pending_input(
        session_id=session_id,
        author_telegram_id=telegram_id,
        kind=kind,
        payload_encrypted=encrypted_payload,
    )
    logger.info("Saved encrypted pending_input for session_id=%s, kind=%s", session_id, kind)

    # 7. Определяем партнеров и статус
    other_id = couple["partner_2_id"] if telegram_id == couple["partner_1_id"] else couple["partner_1_id"]
    other_user = db.get_user(other_id)
    other_name = other_user["first_name"] if other_user else "Партнер"

    inputs_count = db.count_pending_inputs(session_id)

    if inputs_count == 1:
        # Первый партнер ответил — подтверждаем ему и пушим второго
        await message.answer(
            f"Твоя позиция принята и надежно зашифрована 🔒\n"
            f"Ждём ответа <b>{other_name}</b>. Как только обе стороны выскажутся, ИИ начнет разбор.",
            parse_mode=ParseMode.HTML,
        )

        try:
            await bot.send_message(
                chat_id=other_id,
                text=(
                    f"🕊️ <b>{first_name}</b> хочет спокойно разобраться в ситуации и помириться.\n\n"
                    "Расскажи мне свою версию (текстом или голосовым сообщением прямо сюда в чат).\n"
                    "Она полностью конфиденциальна: твой партнер НЕ увидит и НЕ услышит твой ответ."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=get_miniapp_keyboard(),
            )
        except Exception as e:
            logger.warning("Не удалось отправить уведомление второму партнеру (%s): %s", other_id, e)

    elif inputs_count >= 2:
        # Оба партнера ответили — переводим статус в analyzing
        db.update_session_status(session_id, status="analyzing")

        # Оповещаем текущего (второго) партнера
        await message.answer(
            "Твоя позиция принята и надежно зашифрована 🔒\n\n"
            "Обе версии получены! ИИ-медиатор начинает конфиденциальный анализ. "
            "Скоро пришлём уведомление о готовности разбора ⏳",
            reply_markup=get_miniapp_keyboard(),
        )

        # Оповещаем первого партнера
        try:
            await bot.send_message(
                chat_id=other_id,
                text=(
                    f"<b>{first_name}</b> поделился(-ась) своей версией.\n\n"
                    "Обе версии получены! ИИ-медиатор начинает конфиденциальный анализ. "
                    "Скоро пришлём уведомление о готовности разбора ⏳"
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=get_miniapp_keyboard(),
            )
        except Exception as e:
            logger.warning("Не удалось оповестить первого партнера о начале анализа: %s", e)

        # Запускаем анализ (на данном этапе — асинхронная заглушка)
        asyncio.create_task(analyze_session(session_id))


# ==============================================================================
# Вспомогательные функции для вызова из FastAPI эндпоинтов
# ==============================================================================

async def notify_initiator_prompt(initiator_id: int):
    """Оповещение инициатора при старте разбора из Mini App"""
    try:
        await bot.send_message(
            chat_id=initiator_id,
            text=(
                "🕊️ Разбор конфликта запущен.\n\n"
                "Расскажи текстом или голосовым, что случилось и что тебя задело. "
                "Твой партнёр НЕ увидит и НЕ услышит это напрямую."
            ),
        )
    except Exception as e:
        logger.warning("Не удалось отправить промпт инициатору (%s): %s", initiator_id, e)


async def send_white_flag(to_telegram_id: int):
    """Отправка сигнала «Белый флаг»"""
    await bot.send_message(
        chat_id=to_telegram_id,
        text="🕊️ Твоя половинка сейчас злится, но любит тебя и хочет помириться.",
        reply_markup=get_miniapp_keyboard(),
    )


async def send_hint_message(to_telegram_id: int, hint_type: str):
    """
    Отправка деликатного намека от имени бота (без указания, кто отправил).
    """
    hint_texts = {
        "hug": "Иногда простое тёплое объятие без лишних слов способно снять накопившееся напряжение. Попробуйте обнять близкого человека сегодня 🤗",
        "silence": "Сейчас в воздухе чувствуется эмоциональное напряжение. Иногда полезнее всего дать друг другу полчаса тишины и личного пространства, чтобы остыть 🤫",
        "talk_evening": "Сложные разговоры лучше отложить до спокойного вечернего чая. Когда спадут первые эмоции, вы сможете спокойно услышать друг друга ☕",
        "support": "Каждому из нас бывает непросто. Тёплые слова заботы и поддержки сейчас будут особенно кстати 🤍",
    }
    text = hint_texts.get(
        hint_type,
        "Маленький знак внимания и теплоты способен растопить любой холод в отношениях."
    )
    await bot.send_message(chat_id=to_telegram_id, text=text, reply_markup=get_miniapp_keyboard())


# ==============================================================================
# Фоновая задача: проверка сессий, ожидающих ответа более 48 часов
# ==============================================================================

async def expired_sessions_cleaner_loop():
    """
    Периодический воркер (каждые 15 минут):
    Находит сессии waiting_partner_2 старше 48 часов, переводит в expired,
    удаляет исходники и оповещает инициатора.
    """
    while True:
        try:
            expired_sessions = db.get_expired_sessions()
            for s in expired_sessions:
                s_id = s["id"]
                initiator_id = s["initiator_id"]

                # Переводим в expired и удаляем pending_inputs
                db.expire_session(s_id)

                try:
                    await bot.send_message(
                        chat_id=initiator_id,
                        text=(
                            "⏳ Время ожидания ответа партнера (48 часов) истекло.\n"
                            "Временные зашифрованные исходники были безвозвратно удалены в целях конфиденциальности.\n\n"
                            "Вы можете начать новый разбор в приложении, когда оба будете готовы."
                        ),
                        reply_markup=get_miniapp_keyboard(),
                    )
                except Exception as ex:
                    logger.warning("Не удалось оповестить инициатора о просроченной сессии %s: %s", s_id, ex)

            # Также вызываем общую очистку по expires_at в pending_inputs
            db.cleanup_expired_pending_inputs()

            # Очистка по политике retention (обнуление старых сессий и сырых данных)
            db.purge_expired_data(
                days_retention=settings.RESULTS_RETENTION_DAYS,
                hours_raw_ttl=settings.RAW_INPUT_TTL_HOURS,
            )

        except Exception as e:
            logger.error("Ошибка в воркере expired_sessions_cleaner_loop: %s", e)

        await asyncio.sleep(900)  # 15 минут
