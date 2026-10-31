#!/usr/bin/env python3
"""
Утилита scripts/list_models.py (Этап 3.5).
Отображает список всех доступных моделей для выбранного LLM-провайдера (GigaChat / Gemini),
проверяет наличие установленной модели и выводит информацию о балансе.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Добавляем backend в sys.path
backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from config.settings import settings
from providers import get_provider
from providers.gigachat import GigaChatProvider


async def print_gigachat_models():
    print("\n" + "=" * 60)
    print("🤖 GIGACHAT (СБЕР) — ДОСТУПНЫЕ МОДЕЛИ И БАЛАНС")
    print("=" * 60)
    provider = GigaChatProvider()
    print(f"Scope: {provider.scope}")
    print(f"CA Bundle: {provider._effective_ca or 'Default'}")
    print(f"Insecure SSL: {'ДА (отключен)' if provider.insecure else 'НЕТ (безопасно)'}")
    print(f"Выбранная модель (GIGACHAT_MODEL): {provider.default_model}\n")

    try:
        models = await provider.get_available_models()
        print(f"Найдено моделей: {len(models)}")
        found_target = False
        for i, m in enumerate(models, 1):
            is_cur = " (ТЕКУЩАЯ В .ENV)" if m == provider.default_model else ""
            if m == provider.default_model:
                found_target = True
            print(f"  {i}. {m}{is_cur}")

        if found_target:
            print(f"\n✅ Модель '{provider.default_model}' доступна и готова к работе.")
        else:
            print(f"\n⚠️ ВНИМАНИЕ: Модель '{provider.default_model}' НЕ НАЙДЕНА среди доступных!")
            print(f"Рекомендуется указать одну из: {', '.join(models)}")

        # Проверка баланса
        async with provider._create_client() as giga:
            try:
                bal = await giga.aget_balance()
                print("\n💰 Баланс токенов:")
                for b in bal.balance:
                    print(f"  - {b.usage}: {b.value:,.0f} токенов")
            except Exception as be:
                print(f"Не удалось получить баланс: {be}")

    except Exception as e:
        print(f"❌ Ошибка подключения к GigaChat: {e}")


async def print_gemini_models():
    print("\n" + "=" * 60)
    print("🤖 GOOGLE GEMINI — ДОСТУПНЫЕ МОДЕЛИ")
    print("=" * 60)
    provider = get_provider(provider_name="gemini")
    print(f"Выбранная модель (GEMINI_MODEL): {settings.GEMINI_MODEL}\n")

    try:
        models = await provider.get_available_models()
        print(f"Найдено моделей: {len(models)}")
        found_target = False
        for i, m in enumerate(models, 1):
            is_cur = " (ТЕКУЩАЯ В .ENV)" if m == settings.GEMINI_MODEL else ""
            if m == settings.GEMINI_MODEL:
                found_target = True
            print(f"  {i}. {m}{is_cur}")

        if found_target:
            print(f"\n✅ Модель '{settings.GEMINI_MODEL}' доступна.")
        else:
            print(f"\n⚠️ Модель '{settings.GEMINI_MODEL}' не найдена в списке.")

    except Exception as e:
        print(f"❌ Ошибка подключения к Gemini: {e}")


async def main():
    parser = argparse.ArgumentParser(description="Список моделей GigaChat и Gemini")
    parser.add_argument(
        "--provider",
        type=str,
        default=settings.LLM_PROVIDER,
        choices=["gigachat", "gemini", "all"],
        help="Провайдер ИИ (по умолчанию из .env)",
    )
    args = parser.parse_args()

    if args.provider in ["gigachat", "all"]:
        await print_gigachat_models()
    if args.provider in ["gemini", "all"]:
        await print_gemini_models()
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
