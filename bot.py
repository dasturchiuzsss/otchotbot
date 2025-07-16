import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, ADMIN_PASSWORD, HELPER_ID
from database import (
	init_db, add_user_to_db, check_user_exists, get_todays_sales_by_user,
	check_full_name_exists, get_all_telegram_groups, check_user_blocked,
	get_current_password
)
from otchot import otchot_router
from admin import admin_router
from keyboards import (
	get_main_menu_reply_keyboard, get_developer_contact_inline_keyboard,
	get_group_selection_keyboard
)

class RegistrationStates(StatesGroup):
	waiting_for_password = State()
	waiting_for_full_name = State()
	waiting_for_group_selection = State()

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(message)s')
main_router = Router()

def extract_first_name(full_text: str) -> str:
	words = full_text.strip().split()
	if words:
		return words[0]
	return full_text.strip()

@main_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
	await state.clear()
	user_id = message.from_user.id
	
	if await check_user_blocked(user_id):
		await message.answer(
			"🚫 Sizning hisobingiz vaqtincha bloklangan.\n"
			"Qo'shimcha ma'lumot uchun admin bilan bog'laning."
		)
		return
	
	if await check_user_exists(user_id):
		await message.answer(
			f"👋 Assalomu alaykum, {message.from_user.full_name}!\n"
			f"Xush kelibsiz! Kerakli bo'limni tanlang:",
			reply_markup=get_main_menu_reply_keyboard()
		)
		logging.info(f"Mavjud foydalanuvchi {user_id} ({message.from_user.full_name}) botga kirdi.")
	else:
		await state.set_state(RegistrationStates.waiting_for_password)
		await message.answer("👋 Assalomu alaykum! Botdan foydalanish uchun, iltimos, maxfiy kodni kiriting:")
		logging.info(
			f"Yangi foydalanuvchi {user_id} ({message.from_user.full_name}) ro'yxatdan o'tish jarayonini boshladi.")

@main_router.message(RegistrationStates.waiting_for_password)
async def handle_password(message: Message, state: FSMContext):
	current_password = await get_current_password()
	
	if message.text == current_password:
		user_id = message.from_user.id
		if await check_user_exists(user_id):
			await state.clear()
			await message.answer(
				f"👋 Assalomu alaykum, {message.from_user.full_name}!\nSiz allaqachon ro'yxatdan o'tgansiz. Botimizga xush kelibsiz!",
				reply_markup=get_main_menu_reply_keyboard()
			)
			logging.info(f"Foydalanuvchi {user_id} allaqachon ro'yxatdan o'tgan, asosiy menyuga yo'naltirildi.")
		else:
			await state.set_state(RegistrationStates.waiting_for_full_name)
			await message.answer(
				"✅ Parol to'g'ri! Endi, iltimos, ismingizni kiriting:\n\n"
				"<i>Eslatma: Faqat ismingizni yozing (familyasiz). Masalan: \"Hayotbek\" yoki \"Aziza\"</i>",
				parse_mode="HTML"
			)
			logging.info(f"Foydalanuvchi {user_id} to'g'ri parol kiritdi, ism so'ralmoqda.")
	else:
		await message.answer("❌ Parol noto'g'ri. Iltimos, qaytadan urinib ko'ring.")
		logging.warning(f"Foydalanuvchi {message.from_user.id} noto'g'ri parol kiritdi.")

@main_router.message(RegistrationStates.waiting_for_full_name)
async def handle_full_name(message: Message, state: FSMContext):
	input_text = message.text.strip()
	
	first_name = extract_first_name(input_text)
	
	if not first_name or len(first_name) < 2:
		await message.answer(
			"⚠️ Iltimos, ismingizni to'g'ri kiriting (kamida 2 belgi).\n\n"
			"<i>Faqat ismingizni yozing, familyasiz. Masalan: \"Hayotbek\"</i>",
			parse_mode="HTML"
		)
		return
	
	if len(input_text.split()) > 1:
		await message.answer(
			f"ℹ️ Siz \"{input_text}\" deb yozdingiz. Faqat birinchi so'z \"{first_name}\" qabul qilindi.\n\n"
			"Davom etishni xohlaysizmi?",
			parse_mode="HTML"
		)
	
	if await check_full_name_exists(first_name):
		await message.answer(
			f"⚠️ \"{first_name}\" ismi allaqachon ro'yxatdan o'tgan. Iltimos, boshqacharoq nom kiriting:\n\n"
			"<i>(Masalan: ismingizga raqam qo'shing: \"Hayotbek2\" yoki boshqa variant sinab ko'ring)</i>",
			parse_mode="HTML"
		)
		return
	
	await state.update_data(full_name=first_name)
	
	groups = await get_all_telegram_groups()
	if not groups:
		await message.answer(
			"⚠️ Hozircha hech qanday guruh sozlanmagan.\n"
			"Admin bilan bog'lanib, guruhlar qo'shilishini kuting."
		)
		await state.clear()
		return
	
	await state.set_state(RegistrationStates.waiting_for_group_selection)
	await message.answer(
		f"👥 Salom, {first_name}! Endi qaysi guruhda ishlashingizni tanlang:",
		reply_markup=get_group_selection_keyboard(groups)
	)

@main_router.callback_query(RegistrationStates.waiting_for_group_selection,
                            F.data.startswith("select_registration_group_"))
async def handle_group_selection(callback_query: CallbackQuery, state: FSMContext):
	group_id = int(callback_query.data.split("_")[-1])
	data = await state.get_data()
	full_name = data.get("full_name")
	
	user_id = callback_query.from_user.id
	await add_user_to_db(user_id, full_name, group_id)
	await state.clear()
	
	await callback_query.message.edit_text(
		f"🎉 Rahmat, {full_name}! Siz muvaffaqiyatli ro'yxatdan o'tdingiz.\n"
		f"Endi botning barcha imkoniyatlaridan foydalanishingiz mumkin!"
	)
	
	await callback_query.message.answer(
		"🏠 Asosiy menyu:",
		reply_markup=get_main_menu_reply_keyboard()
	)
	
	logging.info(
		f"Yangi foydalanuvchi {user_id} ({full_name}) muvaffaqiyatli ro'yxatdan o'tdi va {group_id} guruhiga tayinlandi.")
	await callback_query.answer()

@main_router.message(F.text == "🤖 Bot haqida")
async def handle_about_bot(message: Message):
	await message.answer(
		"🤖 **Hisobot Bot v2.0**\n\n"
		"Ushbu bot sotuv hisobotlarini qulay tarzda yuborish va kuzatib borish uchun mo'ljallangan.\n\n"
		"Asosiy funksiyalari:\n"
		"✅ Foydalanuvchilarni ro'yxatdan o'tkazish\n"
		"📝 Hisobotlarni qabul qilish va guruhga yuborish\n"
		"⏳ Hisobotlarni tasdiqlash tizimi\n"
		"📊 Shaxsiy sotuvlar statistikasini ko'rish\n"
		"📈 Ko'p Google Sheets bilan integratsiya\n"
		"🔐 Parolni o'zgartirish imkoniyati\n\n"
		"Savol va takliflar uchun dasturchiga murojaat qiling."
	)

@main_router.message(F.text == "👨‍💻 Dasturchi")
async def handle_developer_contact(message: Message, state: FSMContext):
	await message.answer(
		text=(
			"🛠️ <b>Dasturchiga murojaat</b>\n\n"
			"🛠️ Agar biron muammo, xatolik yoki taklif bo'lsa, iltimos, bu haqda to'liqroq ma'lumot bering.\n\n"
			"📸 Zarur bo'lsa, skrinshot yoki xabar nusxasini yuborishingiz mumkin.\n\n"
			"🔍 Masalani tezroq hal qilishimiz uchun aniq va tushunarli izoh yozing.\n\n"
			"📩 Dasturchiga yozish uchun quyidagi tugmani bosing 👇"
		),
		reply_markup=get_developer_contact_inline_keyboard(),
		parse_mode="HTML"
	)

@main_router.message(F.text == "📊 Sotuvlarim")
async def handle_my_sales(message: Message):
	user_id = message.from_user.id
	
	if await check_user_blocked(user_id):
		await message.answer(
			"🚫 Sizning hisobingiz vaqtincha bloklangan.\n"
			"Qo'shimcha ma'lumot uchun admin bilan bog'laning."
		)
		return
	
	sales_today = await get_todays_sales_by_user(user_id)
	
	if not sales_today:
		await message.answer("📊 Siz bugun hali hech qanday sotuv qayd etmabsiz.")
		return
	
	response_text = f"📊 Sizning bugungi sotuvlaringiz ({len(sales_today)} ta):\n\n"
	for i, sale in enumerate(sales_today):
		contract_id, product_type = sale
		response_text += f"{i + 1}. Shartnoma ID: <code>{contract_id}</code>, Mahsulot: {product_type}\n"
	
	await message.answer(response_text, parse_mode=ParseMode.HTML)

async def main():
	if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
		logging.error("🚫 BOT_TOKEN topilmadi yoki o'rnatilmagan. Iltimos, config.py faylini to'g'rilang.")
		return
	if HELPER_ID == 0:
		logging.warning(
			"⚠️ OGOHLANTIRISH: HELPER_ID config.py da o'rnatilmagan (0). Faqat ADMIN_ID hisobotlarni tasdiqlay oladi."
		)
	
	init_db()
	
	bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
	dp = Dispatcher()
	dp.include_router(main_router)
	dp.include_router(otchot_router)
	dp.include_router(admin_router)
	
	logging.info("🤖 Bot ishga tushmoqda...")
	try:
		await dp.start_polling(bot)
	except Exception as e:
		logging.error(f"🆘 Bot ishlayotganda xatolik: {e}")
	finally:
		await bot.session.close()
		logging.info("🛑 Bot to'xtatildi.")

if __name__ == "__main__":
	try:
		asyncio.run(main())
	except (KeyboardInterrupt, SystemExit):
		logging.info("🛑 Bot foydalanuvchi tomonidan to'xtatildi.")
