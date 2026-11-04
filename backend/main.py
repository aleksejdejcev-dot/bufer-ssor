"""
Главный модуль FastAPI приложения «Буфер Ссор».
Предоставляет REST API для Telegram Mini App и вебхук для Telegram-бота (aiogram 3).

ПРАВИЛА БЕЗОПАСНОСТИ:
1. Валидация подписи initData от Telegram WebApp (HMAC-SHA256, проверка auth_date не старше 24ч).
2. telegram_id извлекается ТОЛЬКО из проверенной подписи initData. Доверять телу запроса запрещено.
3. Все эндпоинты, кроме /health, /me и /legal/accept, отдают 403, пока accepted_legal_at пуст.
4. Сырые тексты/аудио никогда не возвращаются в API. При completed сессии возвращается ТОЛЬКО
   карточка текущего партнера и общий итог shared_summary. Карточка второго партнера скрыта.
"""

import time
import json
import uuid
import secrets
import logging
import asyncio
from datetime import datetime
from typing import Optional, Literal
from urllib.parse import parse_qsl, urlencode
import hmac
import hashlib
from collections import deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from aiogram.types import Update

from config import settings
from config.ui_texts import get_script_hints
from rate_limiter import generate_crockford_code, normalize_invite_code
import db
from repo import get_repo
from retention_scheduler import retention_worker_loop
from bot import (
    bot,
    dp,
    setup_bot_commands,
    notify_initiator_prompt,
    send_white_flag,
    send_hint_message,
    send_subscription_success,
    send_subscription_refund_notice,
)
from yookassa_service import (
    create_yookassa_payment,
    get_yookassa_payment,
    get_yookassa_refund,
    get_plan,
    PLANS,
)

# Настройка логирования без персональных данных
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

# Кэш username бота для формирования инвайт-ссылок
bot_username_cache: Optional[str] = None


# ==============================================================================
# In-Memory Rate Limiter (защита чувствительных эндпоинтов)
# ==============================================================================

class InMemoryRateLimiter:
    """Скользящее окно для ограничения частоты запросов по telegram_id"""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._history: dict[int, deque[float]] = {}

    def check(self, user_id: int):
        now = time.time()
        requests = self._history.setdefault(user_id, deque())

        # Удаляем запросы, вышедшие за пределы временного окна
        while requests and requests[0] <= now - self.window_seconds:
            requests.popleft()

        if len(requests) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - requests[0])) + 1
            logger.warning("Rate limit exceeded for telegram_id=%s (retry in %ss)", user_id, retry_after)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Слишком много запросов. Попробуйте снова через {retry_after} сек.",
                headers={"Retry-After": str(retry_after)},
            )
        requests.append(now)


conflict_limiter = InMemoryRateLimiter(max_requests=3, window_seconds=300)      # 3 запроса в 5 мин
white_flag_limiter = InMemoryRateLimiter(max_requests=5, window_seconds=600)    # 5 сигналов в 10 мин
hint_limiter = InMemoryRateLimiter(max_requests=5, window_seconds=600)          # 5 намеков в 10 мин
invite_limiter = InMemoryRateLimiter(max_requests=5, window_seconds=300)        # 5 инвайтов в 5 мин
mood_limiter = InMemoryRateLimiter(max_requests=15, window_seconds=60)          # 15 обновлений в мин


# ==============================================================================
# Фоновый воркер взаимодействия с Telegram Bot API (Автономный Long Polling)
# ==============================================================================

async def _telegram_startup_worker():
    """
    Фоновый воркер подключения к Telegram Bot API и запуска Long Polling.
    Работает асинхронно, не блокируя запуск HTTP-сервера FastAPI (lifespan).
    При сбоях сети или недоступности Telegram API выполняет повторные попытки с backoff.
    Никогда не вызывает sys.exit() и не прерывает работу основного сервиса.
    """
    global bot_username_cache

    # 1. Попытка получить информацию о боте (get_me) с ретраями
    backoff = 3
    max_backoff = 60
    while True:
        try:
            bot_info = await asyncio.wait_for(bot.get_me(), timeout=10.0)
            bot_username_cache = bot_info.username
            logger.info("Telegram bot initialized successfully: @%s", bot_username_cache)
            try:
                await setup_bot_commands(bot)
            except Exception as cmd_err:
                logger.warning("Failed to setup bot commands on init: %s", cmd_err)
            break
        except asyncio.CancelledError:
            logger.info("Telegram startup worker cancelled during get_me")
            return
        except Exception as e:
            err_msg = str(e)
            if "unauthorized" in err_msg.lower():
                logger.error(
                    "Telegram bot token unauthorized: %s. Please check TELEGRAM_BOT_TOKEN in .env",
                    e,
                )
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    return
                continue
            logger.warning("Failed to fetch bot info (%s). Retrying in %ds...", e, backoff)
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                return
            backoff = min(backoff * 2, max_backoff)

    # 2. Очистка вебхука перед стартом опроса (drop_pending_updates=True) и запуск Long Polling
    while True:
        try:
            logger.info("Deleting Telegram webhook before long polling (drop_pending_updates=True)...")
            await asyncio.wait_for(bot.delete_webhook(drop_pending_updates=True), timeout=10.0)
            logger.info("Telegram webhook removed. Starting background long polling...")
            await dp.start_polling(bot, handle_signals=False, allowed_updates=["message", "callback_query"])
            break
        except asyncio.CancelledError:
            logger.info("Telegram polling cancelled")
            break
        except Exception as e:
            logger.warning("Failed during Telegram polling start (%s). Retrying in 5s...", e)
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break


# ==============================================================================
# Жизненный цикл приложения (Lifespan)
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Запускаем фоновый планировщик очистки данных (Retention Scheduler с pg_try_advisory_lock)
    retention_interval = getattr(settings, "RETENTION_INTERVAL_SECONDS", 3600)
    retention_task = asyncio.create_task(
        retention_worker_loop(
            repo=get_repo(),
            interval_seconds=retention_interval,
            results_retention_days=settings.RESULTS_RETENTION_DAYS,
            payment_retention_years=settings.PAYMENT_RETENTION_YEARS,
        )
    )

    # 2. Запускаем автономный фоновый Long Polling воркер Telegram
    polling_task = asyncio.create_task(_telegram_startup_worker())

    # Мгновенно передаем управление Uvicorn для открытия HTTP-порта 8000
    yield

    # Корректное завершение фоновых задач (Shutdown)
    logger.info("Stopping Telegram long polling and background tasks...")
    try:
        await asyncio.wait_for(dp.stop_polling(), timeout=10.0)
    except Exception as e:
        logger.debug("dp.stop_polling exception on shutdown: %s", e)

    for task in (polling_task, retention_task):
        task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(polling_task, retention_task, return_exceptions=True), timeout=15.0
        )
    except asyncio.TimeoutError:
        logger.error("Background tasks did not stop within shutdown timeout")

    try:
        await bot.session.close()
    except Exception as e:
        logger.debug("bot.session.close exception on shutdown: %s", e)

    logger.info("App shutdown complete")


app = FastAPI(
    title="Буфер Ссор API",
    description="Бэкенд Telegram Mini App и бота-медиатора",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT == "development" else None,
)

cors_origins = []
for u in (getattr(settings, "MINI_APP_URL", None), getattr(settings, "MINIAPP_URL", None)):
    if u and u.startswith("http"):
        cors_origins.append(u.rstrip("/"))
if not cors_origins:
    cors_origins.append("https://bufer-ssor.ru")
if settings.WEBHOOK_BASE_URL:
    cors_origins.append(settings.WEBHOOK_BASE_URL.rstrip("/"))
if settings.ENVIRONMENT == "development":
    cors_origins.extend(["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "http://127.0.0.1:3000", "*"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ==============================================================================
# Аутентификация через Telegram WebApp initData (HMAC-SHA256)
# ==============================================================================

def verify_telegram_init_data(raw_init_data: str) -> dict:
    """
    Проверяет криптографическую подпись initData от Telegram Mini App
    в соответствии с официальным алгоритмом Telegram:
    - HMAC-SHA256(bot_token, "WebAppData") -> secret_key
    - HMAC-SHA256(secret_key, data_check_string) -> hash
    - Проверка срока действия auth_date <= 24 часов
    """
    if not raw_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Отсутствует заголовок X-Telegram-Init-Data",
        )

    parsed = dict(parse_qsl(raw_init_data, keep_blank_values=True))
    if "hash" not in parsed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Некорректный initData: отсутствует параметр hash",
        )

    received_hash = parsed.pop("hash")

    # Сортировка ключей по алфавиту и сборка строки проверки: key=value\n...
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    # Секретный ключ Telegram
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=settings.TELEGRAM_BOT_TOKEN.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()

    # Вычисление проверочного хеша
    calculated_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        logger.warning("Invalid Telegram WebApp HMAC signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительная подпись данных Telegram",
        )

    # Проверка auth_date не старше 24 часов (86400 секунд)
    try:
        auth_date = int(parsed.get("auth_date", 0))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный auth_date")

    now_ts = int(time.time())
    if now_ts - auth_date > 86400:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Срок действия сессии Telegram истек (старше 24 часов)",
        )

    # Извлекаем объект user из initData
    user_json = parsed.get("user")
    if not user_json:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="В initData отсутствует объект user",
        )

    try:
        user_data = json.loads(user_json)
        return user_data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не удалось распарсить JSON пользователя",
        ) from e


async def get_current_user(
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    Зависимость: валидирует initData и возвращает профиль пользователя из БД.
    НИКОГДА не доверяет telegram_id из тела запроса.
    """
    raw_init = x_telegram_init_data
    if not raw_init and authorization and authorization.startswith("tma "):
        raw_init = authorization[4:].strip()

    if not raw_init:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация через Telegram Mini App (X-Telegram-Init-Data)",
        )

    tg_user = verify_telegram_init_data(raw_init)
    telegram_id = int(tg_user["id"])
    first_name = tg_user.get("first_name", "Партнер")

    # Синхронизируем пользователя с БД
    user = db.upsert_user(telegram_id=telegram_id, first_name=first_name)
    return user


async def require_legal_accepted(user: dict = Depends(get_current_user)) -> dict:
    """
    Зависимость-шлюз: проверяет, что пользователь подтвердил 18+ и условия сервиса.
    Все бизнес-эндпоинты (кроме /me и /legal/accept) отдают 403, если согласие не получено.
    """
    if not user.get("accepted_legal_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуется подтвердить возраст 18+ и согласиться с условиями сервиса",
        )
    return user


# ==============================================================================
# Pydantic Модели запросов
# ==============================================================================

class LegalAcceptRequest(BaseModel):
    confirm_18_plus: bool = Field(..., description="Подтверждение возраста 18+")
    accept_terms: bool = Field(True, description="Согласие с условиями использования")


class MoodRequest(BaseModel):
    mood: int = Field(..., ge=1, le=10, description="Оценка настроения от 1 до 10")


class HintRequest(BaseModel):
    hint_type: Literal["hug", "silence", "talk_evening", "support"] = Field(
        ..., description="Тип деликатного намека"
    )


class PaymentCreateRequest(BaseModel):
    plan: str = Field("month_sub", description="Идентификатор тарифа подписки")


# ==============================================================================
# Публичные эндпоинты: Healthcheck и Webhook Telegram
# ==============================================================================

@app.get("/health")
async def healthcheck():
    """Проверка жизнеспособности сервиса (без раскрытия моделей и деталей)"""
    return {
        "status": "ok",
        "llm_provider": settings.LLM_PROVIDER,
    }


# ==============================================================================
# Telegram Webhook (ОТКЛЮЧЕН: бот полностью переведен на автономный Long Polling)
# ==============================================================================
# @app.post("/api/webhook")
# async def telegram_webhook(
#     request: Request,
#     secret_token: Optional[str] = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
# ):
#     """Прием входящих апдейтов от Telegram Bot API с валидацией секрета"""
#     if secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
#         logger.warning("Webhook received invalid secret token")
#         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret")
#
#     try:
#         update_data = await request.json()
#         update = Update.model_validate(update_data, context={"bot": bot})
#         await dp.feed_update(bot=bot, update=update)
#         return {"ok": True}
#     except Exception as e:
#         logger.error("Error processing telegram webhook update: %s", e)
#         return {"ok": False}


@app.post("/api/webhook/yookassa")
async def yookassa_webhook(request: Request):
    """
    Входящий вебхук от ЮKassa.
    Для защиты от подделки статус платежа запрашивается напрямую через API ЮKassa с Basic Auth.
    """
    try:
        event_data = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    event_type = event_data.get("event")
    event_obj = event_data.get("object", {})

    if event_type == "payment.succeeded":
        payment_id = event_obj.get("id")

        if not payment_id:
            return {"status": "ignored", "reason": "no_payment_id"}

        # Проверка безопасности: запрашиваем актуальный статус напрямую в ЮKassa
        try:
            actual_payment = await get_yookassa_payment(payment_id)
        except Exception as e:
            logger.error("Не удалось верифицировать статус платежа %s в ЮKassa: %s", payment_id, e)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to verify payment")

        if actual_payment.get("status") != "succeeded":
            logger.warning(
                "Поддельный или неактуальный вебхук: в ЮKassa платеж %s имеет статус %s",
                payment_id,
                actual_payment.get("status"),
            )
            return {"status": "ignored", "reason": "payment_not_succeeded"}

        metadata = actual_payment.get("metadata", {})
        couple_id = metadata.get("couple_id")
        plan_name = metadata.get("plan", "month_sub")
        plan_info = PLANS.get(plan_name, PLANS["month_sub"])
        days = plan_info.get("days", 30)

        # Атомарно активируем подписку (с защитой от повторных вебхуков)
        activated = db.activate_subscription_for_couple(
            couple_id=couple_id,
            payment_id=payment_id,
            days=days,
            payer_id=int(metadata["telegram_id"]) if metadata.get("telegram_id") else None,
        )

        if activated:
            logger.info("Подписка успешно активирована для плательщика %s (до %s)", metadata.get("telegram_id"), activated.get("subscription_until"))
            valid_until_str = str(activated.get("subscription_until", ""))[:10]
            try:
                raw_sub = activated.get("subscription_until")
                if raw_sub:
                    dt = datetime.fromisoformat(raw_sub)
                    valid_until_str = dt.strftime("%d.%m.%Y")
            except Exception:
                pass

            p1_id = activated.get("partner_1_id")
            p2_id = activated.get("partner_2_id")

            if p1_id:
                asyncio.create_task(send_subscription_success(p1_id, valid_until_str))
            if p2_id:
                asyncio.create_task(send_subscription_success(p2_id, valid_until_str))
        else:
            logger.info("Платеж %s уже был обработан ранее (идемпотентный пропуск)", payment_id)

        return {"status": "ok"}

    elif event_type == "refund.succeeded":
        refund_id = event_obj.get("id")
        payment_id = event_obj.get("payment_id")

        if not refund_id or not payment_id:
            logger.warning("ЮKassa refund webhook: отсутствует refund_id или payment_id")
            return {"status": "ignored", "reason": "missing_refund_or_payment_id"}

        try:
            actual_refund = await get_yookassa_refund(refund_id)
        except Exception as e:
            logger.error("Не удалось верифицировать возврат %s в ЮKassa: %s", refund_id, e)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to verify refund")

        if actual_refund.get("status") != "succeeded" or actual_refund.get("payment_id") != payment_id:
            logger.warning("Несовпадение статуса или платежа в вебхуке возврата %s", refund_id)
            return {"status": "ignored", "reason": "refund_not_succeeded_or_payment_mismatch"}

        payment_record = db.get_payment(payment_id)
        if not payment_record:
            logger.warning("Платеж %s для возврата %s не найден в базе данных", payment_id, refund_id)
            return {"status": "ok", "reason": "payment_not_found"}

        product_name = payment_record.get("product", "month_sub")
        plan_info = PLANS.get(product_name, PLANS["month_sub"])
        days = plan_info.get("days", 30)
        couple_id = payment_record.get("couple_id")

        revoked = db.revoke_subscription_for_couple(
            payment_id=payment_id,
            refund_id=refund_id,
            days=days,
        )

        if revoked and not revoked.get("already_refunded"):
            logger.info("Возврат обработан: payment_id=%s, couple_id=%s", payment_id, couple_id)

            p1_id = revoked.get("partner_1_id")
            p2_id = revoked.get("partner_2_id")

            if p1_id:
                asyncio.create_task(send_subscription_refund_notice(p1_id))
            if p2_id:
                asyncio.create_task(send_subscription_refund_notice(p2_id))
        else:
            logger.info("Возврат для платежа %s уже был обработан ранее (идемпотентный пропуск)", payment_id)

        return {"status": "ok"}

    else:
        logger.info("ЮKassa webhook: событие %s пропущено", event_type)
        return {"status": "ok", "action": "ignored"}


# ==============================================================================
# Эндпоинты профиля и согласий
# ==============================================================================

@app.get("/me")
async def get_my_profile(user: dict = Depends(get_current_user)):
    """
    Возвращает профиль текущего пользователя, данные о его паре и активной сессии.
    Доступен даже если accepted_legal_at еще не заполнен (чтобы фронт знал, показывать ли дисклеймер).
    """
    telegram_id = user["telegram_id"]
    couple = db.get_user_couple(telegram_id)

    couple_info = None
    active_session_info = None
    subscription_until = db.get_subscription_until_for_user(telegram_id)

    if couple:
        is_p1 = (couple["partner_1_id"] == telegram_id)
        other_id = couple.get("partner_2_id") if is_p1 else couple["partner_1_id"]
        other_user = db.get_user(other_id) if other_id else None

        couple_info = {
            "id": couple["id"],
            "invite_code": couple["invite_code"],
            "has_partner": bool(couple.get("partner_2_id")),
            "partner_name": other_user["first_name"] if other_user else None,
            "is_partner_1": is_p1,
            "free_sessions_left": couple.get("free_sessions_left", 0),
            "subscription_until": subscription_until or couple.get("subscription_until"),
            "my_mood": couple.get("mood_p1") if is_p1 else couple.get("mood_p2"),
            "partner_mood": couple.get("mood_p2") if is_p1 else couple.get("mood_p1"),
        }

        # Проверяем активную сессию
        session = db.get_active_session(couple["id"])
        if session:
            active_session_info = {
                "id": session["id"],
                "status": session["status"],
                "created_at": session["created_at"],
                "i_submitted": db.has_user_submitted_input(session["id"], telegram_id),
            }

    return {
        "user": {
            "telegram_id": user["telegram_id"],
            "first_name": user["first_name"],
            "accepted_legal_at": user.get("accepted_legal_at"),
            "couple_id": user.get("couple_id"),
        },
        "couple": couple_info,
        "free_sessions_left": couple.get("free_sessions_left", 2) if couple else 2,
        "subscription_until": subscription_until or (couple.get("subscription_until") if couple else None),
        "active_session": active_session_info,
    }


@app.post("/legal/accept")
async def accept_legal_terms(
    payload: LegalAcceptRequest,
    user: dict = Depends(get_current_user),
):
    """
    Фиксация согласия с условиями сервиса и подтверждение возраста 18+.
    """
    if not payload.confirm_18_plus:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сервис предназначен только для лиц старше 18 лет",
        )

    updated_user = db.accept_legal(user["telegram_id"])
    return {
        "status": "accepted",
        "accepted_legal_at": updated_user["accepted_legal_at"],
    }


# ==============================================================================
# Эндпоинты пары (couples)
# ==============================================================================

@app.post("/couple/invite")
async def create_couple_invite(user: dict = Depends(require_legal_accepted)):
    """
    Создает пару и генерирует уникальную инвайт-ссылку для второго партнера (Crockford base32).
    """
    telegram_id = user["telegram_id"]
    allowed, retry_after = db.check_rate_limit(f"invite:{telegram_id}", max_requests=5, window_seconds=3600)
    if not allowed:
        minutes = max(1, (retry_after + 59) // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много попыток создания инвайта. Подождите {minutes} мин.",
            headers={"Retry-After": str(retry_after)},
        )

    # Проверяем, не состоит ли пользователь уже в полноценной паре
    existing = db.get_user_couple(telegram_id)
    if existing and existing.get("partner_2_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Вы уже состоите в активной паре. Разорвите текущую связку перед созданием новой.",
        )

    # Если уже создавал пару, но партнер 2 еще не присоединился — возвращаем существующий код
    if existing and not existing.get("partner_2_id") and existing["partner_1_id"] == telegram_id:
        invite_code = existing["invite_code"]
    else:
        invite_code = generate_crockford_code(length=8, formatted=True)
        couple = db.create_couple(partner_1_id=telegram_id, invite_code=invite_code)
        invite_code = couple["invite_code"]

    bot_name = bot_username_cache or "BufferSsorBot"
    invite_link = f"https://t.me/{bot_name}?start=pair_{invite_code}"

    return {
        "invite_code": invite_code,
        "invite_link": invite_link,
    }


@app.delete("/history")
async def delete_couple_history(user: dict = Depends(require_legal_accepted)):
    """
    Удаляет всю историю сессий пары, персональные карточки, общий итог и чекины настроения.
    Профили пользователей и связь в паре остаются.
    """
    couple = db.get_user_couple(user["telegram_id"])
    if not couple:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пара не найдена")

    db.delete_history(couple["id"], initiated_by=user["telegram_id"])
    return {"status": "history_deleted", "couple_id": couple["id"]}


@app.post("/maintenance/retention")
async def trigger_retention_purge(
    secret: Optional[str] = Header(None, alias="X-Maintenance-Secret"),
):
    """
    Очистка незавершённых исходников по TTL и результатов завершённых разборов по сроку хранения.
    """
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET
    if expected_secret and secret != expected_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    res = db.purge_expired_data(
        days_retention=settings.RESULTS_RETENTION_DAYS,
        hours_raw_ttl=settings.RAW_INPUT_TTL_HOURS,
    )
    return {"status": "ok", "purged": res}


@app.delete("/couple")
async def delete_my_couple(user: dict = Depends(require_legal_accepted)):
    """
    Удаление пары, связанных сессий, исходников и профилей обоих участников.
    Платёжный учёт и личная подписка плательщика сохраняются отдельно.
    """
    couple = db.get_user_couple(user["telegram_id"])
    if not couple:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пара не найдена")

    db.delete_couple_data(couple["id"], initiated_by=user["telegram_id"])
    return {"status": "deleted"}


# ==============================================================================
# Эндпоинты подписки и платежей (YooKassa)
# ==============================================================================

@app.post("/payment/create")
async def create_payment_order(
    payload: PaymentCreateRequest,
    user: dict = Depends(require_legal_accepted),
):
    """
    Создает платежную сессию в ЮKassa для оформления персональной подписки.
    """
    telegram_id = user["telegram_id"]
    couple = db.get_user_couple(telegram_id)

    try:
        plan_info = get_plan(payload.plan)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    try:
        idempotence_key = str(uuid.uuid4())
        metadata = {
            "couple_id": couple["id"] if couple else None,
            "telegram_id": telegram_id,
            "plan": payload.plan,
        }
        yoo_data = await create_yookassa_payment(
            amount=plan_info["amount"],
            currency=plan_info["currency"],
            description=plan_info["title"],
            metadata=metadata,
            idempotence_key=idempotence_key,
        )

        payment_id = yoo_data["id"]
        confirmation_url = yoo_data.get("confirmation", {}).get("confirmation_url", "")
        if not confirmation_url:
            raise RuntimeError("ЮKassa не вернула confirmation_url")

        # Сохраняем pending запись в БД
        db.create_payment(
            couple_id=couple["id"] if couple else None,
            user_id=telegram_id,
            payment_id=payment_id,
            amount=plan_info["amount"],
            currency=plan_info["currency"],
            product=payload.plan,
        )

        return {
            "payment_id": payment_id,
            "confirmation_url": confirmation_url,
        }
    except Exception as e:
        logger.exception("Ошибка при создании платежа: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Не удалось создать платеж: {e}",
        )


# ==============================================================================
# Эндпоинты конфликта и сессий (conflict_sessions)
# ==============================================================================

@app.post("/conflict/start")
async def start_conflict_session(user: dict = Depends(require_legal_accepted)):
    """
    Инициация сессии разбора конфликта:
    1. Проверяет наличие второго партнера в паре.
    2. Проверяет лимиты (free_sessions_left > 0 или активная подписка).
    3. Создает сессию со статусом waiting_partner_2.
    4. Отправляет Партнеру А сообщение от бота с приглашением рассказать свою версию.
    """
    telegram_id = user["telegram_id"]
    couple = db.get_user_couple(telegram_id)
    if not couple or not couple.get("partner_2_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для начала разбора необходимо, чтобы к паре присоединился второй партнер",
        )

    # Защита от флуда: 3 запроса в час на пару
    allowed, retry_after = db.check_rate_limit(f"conflict:{couple['id']}", max_requests=3, window_seconds=3600)
    if not allowed:
        minutes = max(1, (retry_after + 59) // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Не более 3 сессий в час на пару. Подождите {minutes} мин.",
            headers={"Retry-After": str(retry_after)},
        )

    # Атомарно проверяем доступ, списываем бесплатный разбор и создаем сессию.
    session = db.create_conflict_session_with_access(couple_id=couple["id"], initiator_id=telegram_id)
    if not session:
        couple = db.get_couple_by_id(couple["id"]) or couple
        if not db.check_couple_access(couple)[0]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Бесплатные разборы закончились. Оформите подписку в приложении.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В вашей паре уже есть активный разбор. Завершите его перед началом нового.",
        )

    # Бот пишет Партнеру А приглашение рассказать позицию
    asyncio.create_task(notify_initiator_prompt(telegram_id))

    return {
        "status": "started",
        "session_id": session["id"],
        "session_status": session["status"],
    }


@app.get("/conflict/{session_id}")
async def get_conflict_session(
    session_id: str,
    user: dict = Depends(require_legal_accepted),
):
    """
    Получение статуса и результатов сессии разбора.
    
    СТРОЖАЙШЕЕ ПРАВИЛО КОНФИДЕНЦИАЛЬНОСТИ:
    - Если сессия completed: возвращается ТОЛЬКО персональная карточка ТЕКУЩЕГО партнера
      и общий итог shared_summary.
    - Карточка другого партнера НИКОГДА не отдается.
    - Исходные тексты/аудио НИКОГДА не отдаются.
    """
    session = db.get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена")

    couple = db.get_couple_by_id(session["couple_id"])
    if not couple:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пара сессии не найдена")

    telegram_id = user["telegram_id"]
    if telegram_id not in (couple["partner_1_id"], couple.get("partner_2_id")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этой сессии запрещен")

    status_val = session["status"]

    if status_val == "purged_by_retention":
        return {
            "id": session["id"],
            "status": "completed",
            "risk_level": session.get("risk_level"),
            "created_at": session["created_at"],
            "completed_at": session.get("completed_at"),
            "personal_advice": None,
            "shared_summary": None,
        }

    if status_val != "completed":
        return {
            "id": session["id"],
            "status": status_val,
            "risk_level": session.get("risk_level"),
            "created_at": session["created_at"],
            "completed_at": session.get("completed_at"),
        }

    # После того как оба участника получили результат, его содержимое удаляется.
    if not (session.get("ai_advice_p1") or session.get("ai_advice_p2") or session.get("shared_summary")):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Результат разбора уже удалён после завершения. Данные пары и исходные сообщения не сохраняются.",
        )

    # Сессия completed: формируем строго персональную карточку
    is_partner_1 = (telegram_id == couple["partner_1_id"])
    my_advice = session.get("ai_advice_p1") if is_partner_1 else session.get("ai_advice_p2")

    return {
        "id": session["id"],
        "status": status_val,
        "risk_level": session.get("risk_level"),
        "created_at": session["created_at"],
        "completed_at": session.get("completed_at"),
        "personal_advice": my_advice,
        "shared_summary": session.get("shared_summary"),
        "script_hints": get_script_hints(),
    }


@app.post("/conflict/{session_id}/result-seen")
async def mark_conflict_result_seen(
    session_id: str,
    user: dict = Depends(require_legal_accepted),
):
    """Marks that a participant received the result and clears it after both did."""
    session = db.get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена")
    couple = db.get_couple_by_id(session["couple_id"])
    if not couple or user["telegram_id"] not in (couple["partner_1_id"], couple.get("partner_2_id")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этой сессии запрещен")
    db.mark_conflict_result_seen(session_id, user["telegram_id"])
    return {"status": "ok"}


# ==============================================================================
# Эндпоинты настроения и быстрых сигналов (White Flag / Hints)
# ==============================================================================

@app.post("/mood")
async def update_my_mood(
    payload: MoodRequest,
    user: dict = Depends(require_legal_accepted),
):
    """Обновление настроения пользователя (1-10)"""
    telegram_id = user["telegram_id"]
    mood_limiter.check(telegram_id)

    couple = db.get_user_couple(telegram_id)
    if not couple:
        invite_code = secrets.token_hex(3).upper()
        couple = db.create_couple(partner_1_id=telegram_id, invite_code=invite_code)

    is_p1 = (couple["partner_1_id"] == telegram_id)
    updated_couple = db.update_mood(couple["id"], is_partner_1=is_p1, mood=payload.mood)

    return {
        "status": "ok",
        "my_mood": payload.mood,
        "partner_mood": updated_couple.get("mood_p2") if is_p1 else updated_couple.get("mood_p1"),
    }


@app.post("/signal/white-flag")
async def send_signal_white_flag(user: dict = Depends(require_legal_accepted)):
    """
    Отправка сигнала перемирия «Белый флаг»:
    Партнер получает сообщение: «Твоя половинка сейчас злится, но любит тебя и хочет помириться».
    Лимит: 1 раз в час на пару.
    """
    telegram_id = user["telegram_id"]
    couple = db.get_user_couple(telegram_id)
    if not couple or not couple.get("partner_2_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Второй партнер еще не присоединился к паре",
        )

    allowed, retry_after = db.check_rate_limit(f"signal:{couple['id']}:white_flag", max_requests=1, window_seconds=3600)
    if not allowed:
        minutes = max(1, (retry_after + 59) // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Сигнал уже отправлен недавно, подождите {minutes} минут",
            headers={"Retry-After": str(retry_after)},
        )

    other_id = couple["partner_2_id"] if telegram_id == couple["partner_1_id"] else couple["partner_1_id"]

    try:
        await send_white_flag(other_id)
    except Exception as e:
        logger.error("Failed to send white flag to %s: %s", other_id, e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось отправить сигнал")

    return {"status": "sent"}


@app.post("/signal/hint")
async def send_signal_hint(
    payload: HintRequest,
    user: dict = Depends(require_legal_accepted),
):
    """
    Отправка деликатного намека:
    Бот мягко подсказывает партнеру от своего имени, не выдавая отправителя.
    Допустимые типы: hug, silence, talk_evening, support.
    Лимит: 1 раз в час на пару для каждого типа.
    """
    telegram_id = user["telegram_id"]
    couple = db.get_user_couple(telegram_id)
    if not couple or not couple.get("partner_2_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Второй партнер еще не присоединился к паре",
        )

    allowed, retry_after = db.check_rate_limit(f"signal:{couple['id']}:hint_{payload.hint_type}", max_requests=1, window_seconds=3600)
    if not allowed:
        minutes = max(1, (retry_after + 59) // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Сигнал уже отправлен недавно, подождите {minutes} минут",
            headers={"Retry-After": str(retry_after)},
        )

    other_id = couple["partner_2_id"] if telegram_id == couple["partner_1_id"] else couple["partner_1_id"]

    try:
        await send_hint_message(other_id, payload.hint_type)
    except Exception as e:
        logger.error("Failed to send hint to %s: %s", other_id, e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось отправить намек")

    return {"status": "sent"}


# ==============================================================================
# Раздача статики фронтенда (Telegram Mini App из frontend/dist)
# ==============================================================================
from pathlib import Path
from fastapi.staticfiles import StaticFiles

frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")

