import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Установите переменную окружения BOT_TOKEN")

from aiogram.client.session.aiohttp import AiohttpSession

session = AiohttpSession(proxy="http://127.0.0.1:10801")
from aiogram.client.default import DefaultBotProperties

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=session,
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

class ProfileSetup(StatesGroup):
    waiting_stack = State()
    waiting_city = State()
    waiting_course = State()


class SearchState(StatesGroup):
    waiting_query = State()


# Главное меню


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔍 Поиск стажировок"),
                KeyboardButton(text="📋 Все стажировки"),
            ],
            [
                KeyboardButton(text="🏢 По компаниям"),
                KeyboardButton(text="⭐ Избранное"),
            ],
            [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="🔔 Подписки")],
        ],
        resize_keyboard=True,
    )


#/start


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = await db.get_or_create_user(
        telegram_id=message.from_user.id,
        name=message.from_user.full_name,
    )
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я — <b>IT-Intern Bot</b>, агрегатор IT-стажировок.\n\n"
        "Что умею:\n"
        "• 🔍 Искать стажировки по стеку и городу\n"
        "• 🏢 Смотреть вакансии по компаниям\n"
        "• ⭐ Сохранять в избранное\n"
        "• 🔔 Уведомлять о новых стажировках\n\n"
        "Начни с настройки профиля — /profile",
        reply_markup=main_menu_kb(),
    )


#/profile - настройка профиля


@router.message(Command("profile"))
@router.message(F.text == "👤 Мой профиль")
async def cmd_profile(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    if user and user.get("stack"):
        text = (
            "👤 <b>Ваш профиль:</b>\n\n"
            f"📌 Стек: {user['stack'] or '—'}\n"
            f"🏙 Город: {user['city'] or '—'}\n"
            f"🎓 Курс: {user['course'] or '—'}\n\n"
            "Хотите обновить? Нажмите кнопку ниже."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Обновить профиль", callback_data="update_profile"
                    )
                ],
            ]
        )
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer(
            "Давайте настроим ваш профиль!\n\n"
            "Какие технологии вас интересуют?\n"
            "<i>Например: Python, Django, SQL</i>"
        )
        await state.set_state(ProfileSetup.waiting_stack)


@router.callback_query(F.data == "update_profile")
async def cb_update_profile(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Какие технологии вас интересуют?\n" "<i>Например: Python, Django, SQL</i>"
    )
    await state.set_state(ProfileSetup.waiting_stack)
    await callback.answer()


@router.message(ProfileSetup.waiting_stack)
async def process_stack(message: Message, state: FSMContext):
    await state.update_data(stack=message.text.strip())
    await message.answer(
        "🏙 В каком городе ищете стажировку?\n"
        "<i>Например: Москва (или «любой» для удалёнки)</i>"
    )
    await state.set_state(ProfileSetup.waiting_city)


@router.message(ProfileSetup.waiting_city)
async def process_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await message.answer(
        "🎓 На каком вы курсе? (1-6, магистратура = 5-6)\n"
        "<i>Или отправьте «—» чтобы пропустить</i>"
    )
    await state.set_state(ProfileSetup.waiting_course)


@router.message(ProfileSetup.waiting_course)
async def process_course(message: Message, state: FSMContext):
    data = await state.get_data()
    course = None
    if message.text.strip().isdigit():
        course = int(message.text.strip())

    await db.get_or_create_user(message.from_user.id, message.from_user.full_name)
    await db.update_user_profile(
        telegram_id=message.from_user.id,
        stack=data["stack"],
        city=data["city"],
        course=course,
    )
    await state.clear()
    await message.answer(
        "✅ Профиль сохранён!\n\n"
        f"📌 Стек: {data['stack']}\n"
        f"🏙 Город: {data['city']}\n"
        f"🎓 Курс: {course or '—'}\n\n"
        "Теперь можете искать стажировки — 🔍",
        reply_markup=main_menu_kb(),
    )


# Поиск стажировок


@router.message(Command("search"))
@router.message(F.text == "🔍 Поиск стажировок")
async def cmd_search(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    if user and user.get("stack"):
        # Предлагаем искать по профилю или ввести вручную
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"🔍 По моему стеку ({user['stack']})",
                        callback_data="search_by_profile",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✍️ Ввести запрос вручную", callback_data="search_manual"
                    )
                ],
            ]
        )
        await message.answer("Как будем искать?", reply_markup=kb)
    else:
        await message.answer(
            "Введите технологии через запятую:\n" "<i>Например: Python, SQL</i>"
        )
        await state.set_state(SearchState.waiting_query)


@router.callback_query(F.data == "search_by_profile")
async def cb_search_by_profile(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    results = await db.search_internships(
        stack=user.get("stack"),
        city=user.get("city"),
    )
    await send_search_results(
        callback.message, results, f"По вашему стеку: {user['stack']}"
    )
    await callback.answer()


@router.callback_query(F.data == "search_manual")
async def cb_search_manual(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Введите технологии через запятую:\n" "<i>Например: Go, Kubernetes</i>"
    )
    await state.set_state(SearchState.waiting_query)
    await callback.answer()


@router.message(SearchState.waiting_query)
async def process_search(message: Message, state: FSMContext):
    query = message.text.strip()
    results = await db.search_internships(stack=query)
    await send_search_results(message, results, f"По запросу: {query}")
    await state.clear()


async def send_search_results(message: Message, results: list[dict], title: str):
    if not results:
        await message.answer(
            f"😔 <b>{title}</b>\n\nНичего не найдено. Попробуйте другие ключевые слова."
        )
        return

    await message.answer(f"📋 <b>{title}</b>\nНайдено: {len(results)}\n")

    for item in results[:10]:
        text = format_internship(item)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⭐ В избранное", callback_data=f"fav_{item['id']}"
                    ),
                    InlineKeyboardButton(
                        text="🔗 Подробнее", url=item["url"] or "https://example.com"
                    ),
                ],
            ]
        )
        await message.answer(text, reply_markup=kb)
        await asyncio.sleep(0.3)  # антиспам


def format_internship(item: dict) -> str:
    remote_tag = " 🏠 удалёнка" if item.get("remote") else ""
    salary = item.get("salary") or "не указана"
    deadline = item.get("deadline") or "не указан"
    return (
        f"🏢 <b>{item['company']}</b>\n"
        f"💼 {item['title']}{remote_tag}\n"
        f"🛠 {item.get('stack', '—')}\n"
        f"📍 {item.get('city', '—')}\n"
        f"💰 {salary}\n"
        f"⏰ Дедлайн: {deadline}\n"
        f"\n{item.get('description', '')}"
    )


# Все стажировки


@router.message(F.text == "📋 Все стажировки")
async def cmd_all(message: Message):
    results = await db.get_all_internships()
    if not results:
        await message.answer("База пуста 😔")
        return

    # Краткий список
    lines = [f"📋 <b>Все стажировки ({len(results)}):</b>\n"]
    for i, item in enumerate(results, 1):
        remote = " 🏠" if item.get("remote") else ""
        lines.append(f"{i}. <b>{item['company']}</b> — {item['title']}{remote}")

    lines.append("\nНажмите на вакансию для подробностей:")

    # Кнопки по 2 в ряд
    buttons = []
    row = []
    for item in results:
        row.append(
            InlineKeyboardButton(
                text=f"{item['company']}: {item['title'][:20]}",
                callback_data=f"detail_{item['id']}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons[:20])  # макс 20 рядов

    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("detail_"))
async def cb_detail(callback: CallbackQuery):
    internship_id = int(callback.data.split("_")[1])
    item = await db.get_internship(internship_id)
    if not item:
        await callback.answer("Стажировка не найдена", show_alert=True)
        return

    text = format_internship(item)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ В избранное", callback_data=f"fav_{item['id']}"
                ),
                InlineKeyboardButton(
                    text="🔗 Подробнее", url=item["url"] or "https://example.com"
                ),
            ],
        ]
    )
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


#По компаниям


@router.message(F.text == "🏢 По компаниям")
async def cmd_companies(message: Message):
    companies = await db.get_companies()
    if not companies:
        await message.answer("Компаний пока нет 😔")
        return

    buttons = []
    row = []
    for c in companies:
        row.append(InlineKeyboardButton(text=c, callback_data=f"company_{c[:30]}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("🏢 Выберите компанию:", reply_markup=kb)


@router.callback_query(F.data.startswith("company_"))
async def cb_company(callback: CallbackQuery):
    company = callback.data[8:]
    results = await db.search_internships()  # все
    filtered = [r for r in results if r["company"].startswith(company)]
    await send_search_results(callback.message, filtered, f"Стажировки в {company}")
    await callback.answer()


#Избранное


@router.callback_query(F.data.startswith("fav_"))
async def cb_add_fav(callback: CallbackQuery):
    internship_id = int(callback.data.split("_")[1])
    await db.get_or_create_user(callback.from_user.id, callback.from_user.full_name)
    added = await db.add_favorite(callback.from_user.id, internship_id)
    if added:
        await callback.answer("⭐ Добавлено в избранное!", show_alert=False)
    else:
        await callback.answer("Уже в избранном", show_alert=False)


@router.message(F.text == "⭐ Избранное")
async def cmd_favorites(message: Message):
    items = await db.get_favorites(message.from_user.id)
    if not items:
        await message.answer(
            "У вас пока нет избранных стажировок.\nИспользуйте ⭐ при просмотре вакансий."
        )
        return

    await message.answer(f"⭐ <b>Ваше избранное ({len(items)}):</b>\n")
    for item in items:
        text = format_internship(item)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Удалить", callback_data=f"unfav_{item['id']}"
                    ),
                    InlineKeyboardButton(
                        text="🔗 Подробнее", url=item["url"] or "https://example.com"
                    ),
                ],
            ]
        )
        await message.answer(text, reply_markup=kb)
        await asyncio.sleep(0.3)


@router.callback_query(F.data.startswith("unfav_"))
async def cb_remove_fav(callback: CallbackQuery):
    internship_id = int(callback.data.split("_")[1])
    await db.remove_favorite(callback.from_user.id, internship_id)
    await callback.answer("Удалено из избранного", show_alert=False)


# Подписки


@router.message(F.text == "🔔 Подписки")
async def cmd_subscriptions(message: Message):
    user = await db.get_user(message.from_user.id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Подписаться на новые", callback_data="sub_add"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Отписаться от всех", callback_data="sub_remove"
                )
            ],
        ]
    )
    text = (
        "🔔 <b>Подписки на новые стажировки</b>\n\n"
        "Подпишитесь, и бот пришлёт уведомление, когда появятся новые вакансии "
        "по вашему стеку."
    )
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "sub_add")
async def cb_sub_add(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user or not user.get("stack"):
        await callback.answer("Сначала настройте профиль (/profile)", show_alert=True)
        return

    await db.add_subscription(
        callback.from_user.id,
        stack_filter=user["stack"],
        city_filter=user.get("city"),
    )
    await callback.answer(
        f"✅ Подписка оформлена!\nСтек: {user['stack']}", show_alert=True
    )


@router.callback_query(F.data == "sub_remove")
async def cb_sub_remove(callback: CallbackQuery):
    await db.remove_subscription(callback.from_user.id)
    await callback.answer("Все подписки удалены", show_alert=True)


#/help


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📚 <b>Команды бота:</b>\n\n"
        "/start — начать работу\n"
        "/profile — настроить профиль (стек, город, курс)\n"
        "/search — поиск стажировок\n"
        "/help — справка\n\n"
        "Или используйте кнопки меню внизу 👇",
        reply_markup=main_menu_kb(),
    )


#Запуск


async def main():
    await db.init_db()
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
