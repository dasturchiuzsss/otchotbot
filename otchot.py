import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Router, F, Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID, HELPER_ID
from database import (
	add_sales_report, get_user_assigned_group, update_report_status_in_db,
	check_user_blocked, get_user_by_telegram_id, get_group_google_sheet,
	get_user_reports_count, get_reports_by_user, get_all_users
)
from keyboards import (
	get_cancel_report_inline_keyboard, get_main_menu_reply_keyboard,
	get_report_confirmation_keyboard, get_report_confirmed_keyboard,
	get_group_report_keyboard, get_edit_selection_keyboard,
	get_rejection_reason_keyboard, get_contact_helper_keyboard,
	get_yes_no_additional_phone_inline_keyboard
)
from google_sheets_integration import save_report_to_sheets

# Router yaratish
otchot_router = Router()

# FSM holatlari
class ReportState(StatesGroup):
	waiting_for_client_name = State()
	waiting_for_phone_number = State()
	waiting_for_additional_phone_question = State()
	waiting_for_additional_phone_number = State()
	waiting_for_product_type = State()
	waiting_for_client_location_text = State()
	waiting_for_contract_id = State()
	waiting_for_contract_amount = State()
	waiting_for_product_image = State()
	waiting_for_confirmation = State()
	waiting_for_edit_selection = State()

# Konstantalar
REPORT_CAPTION_TEMPLATE = """📝 Yangi Hisobot:

👤 Mijoz: {client_name}

📱 Telefon: {phone_number}
{additional_phone_line}
🛍️ Mahsulot: {product_type}

📍 Manzil: {client_location}

📄 Shartnoma ID: {contract_id}

💰 Shartnoma summasi: {contract_amount}

👨‍💼 Sotuvchi: {sender_full_name}

{status_line}"""

# Yordamchi funksiyalar
def format_amount(amount_str: str) -> str:
	"""
	Summani formatlash funksiyasi
	Input: "500000", "5,000,000", "5.000.000"
	Output: "500.000"
	"""
	if not amount_str:
		return amount_str
	
	# Faqat raqamlarni qoldirish
	clean_amount = re.sub(r'[^\d]', '', str(amount_str))
	
	if not clean_amount:
		return amount_str
	
	# Raqamni 3 xonali guruhlarga bo'lish (chapdan o'ngga)
	formatted = ""
	for i, digit in enumerate(reversed(clean_amount)):
		if i > 0 and i % 3 == 0:
			formatted = "." + formatted
		formatted = digit + formatted
	
	return formatted

def validate_phone_number(phone: str) -> bool:
	"""Telefon raqamini validatsiya qilish"""
	if not phone:
		return False
	
	# Kamida 9 ta raqam bo'lishi kerak
	digits_only = re.sub(r'[^\d]', '', phone)
	return len(digits_only) >= 9

def validate_text_field(text: str, min_length: int = 2) -> bool:
	"""Matn maydonlarini validatsiya qilish"""
	return bool(text and text.strip() and len(text.strip()) >= min_length)

def get_seller_contact_keyboard(seller_telegram_id: int) -> InlineKeyboardMarkup:
	"""Sotuvchi bilan bog'lanish klaviaturasi"""
	buttons = [
		[
			InlineKeyboardButton(
				text="💬 Sotuvchi bilan bog'lanish",
				url=f"tg://user?id={seller_telegram_id}"
			)
		],
		[
			InlineKeyboardButton(
				text="🔙 Orqaga",
				callback_data="back_to_group_report"
			)
		]
	]
	return InlineKeyboardMarkup(inline_keyboard=buttons)

async def get_seller_detailed_profile(telegram_id: int) -> Optional[Dict[str, Any]]:
	"""
	Sotuvchi batafsil profil ma'lumotlarini olish
	"""
	try:
		# Foydalanuvchi ma'lumotlarini olish
		user_info = await get_user_by_telegram_id(telegram_id)
		if not user_info:
			return None
		
		user_id, telegram_id, full_name, reg_date, is_blocked, group_name = user_info
		
		# Hisobotlar statistikasini olish
		total_reports = await get_user_reports_count(telegram_id)
		recent_reports = await get_reports_by_user(telegram_id, 10)
		
		# Tasdiqlangan va kutilayotgan hisobotlar soni
		confirmed_count = 0
		pending_count = 0
		rejected_count = 0
		
		for report in recent_reports:
			status = report[11]  # status field
			if status == "confirmed":
				confirmed_count += 1
			elif status == "pending":
				pending_count += 1
			elif status == "rejected":
				rejected_count += 1
		
		# Registration sanasini formatlash
		reg_date_formatted = "Noma'lum"
		if reg_date:
			try:
				# Agar sana timestamp formatida bo'lsa
				if " " in reg_date:
					reg_date_formatted = reg_date.split(' ')[0]
				else:
					reg_date_formatted = reg_date
			except:
				reg_date_formatted = reg_date
		
		# So'nggi faollik sanasini hisoblash
		last_activity = "Hech qachon"
		if recent_reports:
			try:
				last_report = recent_reports[0]
				last_submission = last_report[10]  # submission_timestamp
				if last_submission:
					if isinstance(last_submission, str):
						last_activity = last_submission.split(' ')[0] if ' ' in last_submission else last_submission
					else:
						last_activity = str(last_submission)[:10]
			except:
				last_activity = "Noma'lum"
		
		return {
			'telegram_id': telegram_id,
			'full_name': full_name,
			'group_name': group_name,
			'reg_date': reg_date_formatted,
			'is_blocked': is_blocked,
			'total_reports': total_reports,
			'confirmed_count': confirmed_count,
			'pending_count': pending_count,
			'rejected_count': rejected_count,
			'recent_reports': recent_reports[:5],  # So'nggi 5 ta hisobot
			'last_activity': last_activity
		}
	
	except Exception as e:
		logging.error(f"Sotuvchi batafsil profil ma'lumotlarini olishda xatolik: {e}")
		return None

def format_seller_profile_message(profile_data: Dict[str, Any]) -> str:
	"""
	Sotuvchi profil xabarini formatlash
	"""
	if not profile_data:
		return "❌ Sotuvchi ma'lumotlari topilmadi."
	
	# Holat belgilash
	status_text = "🔒 BLOKLANGAN" if profile_data['is_blocked'] else "✅ FAOL"
	status_color = "🔴" if profile_data['is_blocked'] else "🟢"
	
	# Statistika hisoblash
	total = profile_data['total_reports']
	confirmed = profile_data['confirmed_count']
	pending = profile_data['pending_count']
	rejected = profile_data['rejected_count']
	
	# Tasdiqlash foizi
	success_rate = 0
	if total > 0:
		success_rate = round((confirmed / total) * 100, 1)
	
	profile_text = f"""👨‍💼 SOTUVCHI PROFILI

{status_color} **ASOSIY MA'LUMOTLAR**
━━━━━━━━━━━━━━━━━━━━━━━
📝 Ism: **{profile_data['full_name']}**
🆔 Telegram ID: `{profile_data['telegram_id']}`
👥 Guruh: **{profile_data['group_name']}**
📅 Ro'yxatdan o'tgan: **{profile_data['reg_date']}**
🔘 Holat: **{status_text}**
📊 So'nggi faollik: **{profile_data['last_activity']}**

📈 **HISOBOTLAR STATISTIKASI**
━━━━━━━━━━━━━━━━━━━━━━━
📋 Jami hisobotlar: **{total} ta**
✅ Tasdiqlangan: **{confirmed} ta**
⏳ Kutilayotgan: **{pending} ta**
❌ Rad etilgan: **{rejected} ta**
🎯 Tasdiqlash foizi: **{success_rate}%**

📋 **SO'NGGI HISOBOTLAR**
━━━━━━━━━━━━━━━━━━━━━━━"""
	
	# So'nggi hisobotlarni qo'shish
	recent_reports = profile_data.get('recent_reports', [])
	if recent_reports:
		for i, report in enumerate(recent_reports, 1):
			try:
				# Report tuple structure
				report_id, _, client_name, phone_number, _, contract_id, product_type, _, _, submission_date, _, status, _, _, _, _ = report
				
				# Status icon
				if status == "confirmed":
					status_icon = "✅"
				elif status == "pending":
					status_icon = "⏳"
				elif status == "rejected":
					status_icon = "❌"
				else:
					status_icon = "❓"
				
				# Mahsulot nomini qisqartirish
				product_short = product_type[:30] + "..." if len(product_type) > 30 else product_type
				
				# Mijoz ismini qisqartirish
				client_short = client_name[:20] + "..." if len(client_name) > 20 else client_name
				
				profile_text += f"""
**{i}.** {status_icon} **{product_short}**
   👤 Mijoz: {client_short}
   📄 Shartnoma: `{contract_id}`
   📅 Sana: {submission_date}"""
			
			except Exception as e:
				logging.error(f"Hisobot ma'lumotlarini formatlashda xatolik: {e}")
				continue
	else:
		profile_text += "\n❌ Hozircha hisobotlar yo'q"
	
	# Qo'shimcha ma'lumotlar
	profile_text += f"""

💡 **QO'SHIMCHA MA'LUMOTLAR**
━━━━━━━━━━━━━━━━━━━━━━━
📞 Sotuvchi bilan to'g'ridan-to'g'ri bog'lanish uchun quyidagi tugmani bosing
🔗 Profil ma'lumotlari real vaqtda yangilanadi
📊 Statistika so'nggi barcha hisobotlar asosida hisoblangan"""
	
	return profile_text

async def find_user_by_name(full_name: str) -> Optional[int]:
	"""
	Ism bo'yicha foydalanuvchi telegram ID'sini topish
	"""
	try:
		all_users = await get_all_users()
		for user in all_users:
			if user[2] == full_name:  # full_name
				return user[1]  # telegram_id
		return None
	except Exception as e:
		logging.error(f"Foydalanuvchini topishda xatolik: {e}")
		return None

async def delete_previous_messages(bot: Bot, chat_id: int, state: FSMContext):
	"""
	Oldingi bot va foydalanuvchi xabarlarini o'chirish
	"""
	data = await state.get_data()
	bot_prompt_id = data.get("last_bot_prompt_id")
	user_reply_id = data.get("last_user_reply_id")
	
	# Bot xabarini o'chirish
	if bot_prompt_id:
		try:
			await bot.delete_message(chat_id, bot_prompt_id)
		except (TelegramBadRequest, Exception) as e:
			logging.warning(f"Bot xabarini o'chirishda xatolik {bot_prompt_id}: {e}")
	
	# Foydalanuvchi xabarini o'chirish
	if user_reply_id:
		try:
			await bot.delete_message(chat_id, user_reply_id)
		except (TelegramBadRequest, Exception) as e:
			logging.warning(f"Foydalanuvchi xabarini o'chirishda xatolik {user_reply_id}: {e}")
	
	# ID'larni tozalash
	await state.update_data(last_bot_prompt_id=None, last_user_reply_id=None)

async def process_step(message: Message, state: FSMContext, bot: Bot, next_state: State, prompt_text: str,
                       keyboard_markup=None):
	"""
	Keyingi bosqichga o'tish uchun umumiy funksiya
	"""
	# Foydalanuvchi xabar ID'sini saqlash
	await state.update_data(last_user_reply_id=message.message_id)
	
	# Oldingi xabarlarni o'chirish
	await delete_previous_messages(bot, message.chat.id, state)
	
	# Yangi xabar yuborish
	sent_message = await message.answer(
		prompt_text,
		reply_markup=keyboard_markup or get_cancel_report_inline_keyboard()
	)
	
	# Holatni o'rnatish va bot xabar ID'sini saqlash
	await state.set_state(next_state)
	await state.update_data(last_bot_prompt_id=sent_message.message_id)

async def show_error_and_retry(message: Message, state: FSMContext, bot: Bot, error_text: str):
	"""
	Xatolik xabarini ko'rsatish va qayta urinish
	"""
	await state.update_data(last_user_reply_id=message.message_id)
	await delete_previous_messages(bot, message.chat.id, state)
	
	error_prompt = await message.answer(
		error_text,
		reply_markup=get_cancel_report_inline_keyboard()
	)
	await state.update_data(last_bot_prompt_id=error_prompt.message_id)

# HISOBOT TOPSHIRISH JARAYONI

@otchot_router.message(F.text == "📝 Hisobot topshirish")
async def start_report_submission(message: Message, state: FSMContext, bot: Bot):
	"""
	Hisobot topshirish jarayonini boshlash
	"""
	user_id = message.from_user.id
	
	# Foydalanuvchi bloklanganligini tekshirish
	if await check_user_blocked(user_id):
		await message.answer(
			"🚫 Sizning hisobingiz vaqtincha bloklangan.\n"
			"Qo'shimcha ma'lumot uchun admin bilan bog'laning."
		)
		return
	
	# Guruh tayinlanganligini tekshirish
	assigned_group = await get_user_assigned_group(user_id)
	if not assigned_group:
		await message.answer(
			"⚠️ Sizga hali guruh tayinlanmagan.\n"
			"Admin bilan bog'lanib, guruhga qo'shilishingizni so'rang."
		)
		return
	
	# Jarayonni boshlash
	await state.clear()
	sent_message = await message.answer(
		"👤 Mijozning to'liq ismini kiriting:\n\n"
		"💡 Masalan: Abdullayev Akmal Akbarovich",
		reply_markup=get_cancel_report_inline_keyboard()
	)
	await state.set_state(ReportState.waiting_for_client_name)
	await state.update_data(last_bot_prompt_id=sent_message.message_id)
	
	logging.info(f"Foydalanuvchi {user_id} hisobot topshirish jarayonini boshladi")

@otchot_router.callback_query(F.data == "cancel_report_submission")
async def cancel_report_submission_handler(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""
	Hisobot topshirish jarayonini bekor qilish
	"""
	current_state = await state.get_state()
	if current_state is None:
		try:
			await callback_query.message.edit_reply_markup(reply_markup=None)
		except Exception:
			pass
		await callback_query.answer("Jarayon allaqachon bekor qilingan yoki yakunlangan.")
		return
	
	# Xabarlarni tozalash
	await delete_previous_messages(bot, callback_query.message.chat.id, state)
	await state.clear()
	
	try:
		await callback_query.message.edit_reply_markup(reply_markup=None)
	except Exception:
		pass
	
	await callback_query.message.answer(
		"🚫 Hisobot topshirish jarayoni bekor qilindi.",
		reply_markup=get_main_menu_reply_keyboard()
	)
	await callback_query.answer()
	
	logging.info(f"Foydalanuvchi {callback_query.from_user.id} hisobot topshirishni bekor qildi")

# MA'LUMOTLARNI QAYTA ISHLASH

@otchot_router.message(ReportState.waiting_for_client_name)
async def process_client_name(message: Message, state: FSMContext, bot: Bot):
	"""Mijoz ismini qayta ishlash"""
	client_name = message.text.strip() if message.text else ""
	
	if not validate_text_field(client_name, 3):
		await show_error_and_retry(
			message, state, bot,
			"⚠️ Iltimos, mijozning to'liq ismini kiriting (kamida 3 belgi).\n\n"
			"💡 Masalan: Abdullayev Akmal Akbarovich\n\n"
			"Qaytadan kiriting:"
		)
		return
	
	await state.update_data(client_name=client_name)
	await process_step(
		message, state, bot,
		ReportState.waiting_for_phone_number,
		"📱 Mijozning telefon raqamini kiriting:\n\n"
		"💡 Masalan: +998901234567 yoki 998901234567"
	)
	
	logging.info(f"Mijoz ismi qayta ishlandi: {client_name}")

@otchot_router.message(ReportState.waiting_for_phone_number)
async def process_phone_number(message: Message, state: FSMContext, bot: Bot):
	"""Telefon raqamini qayta ishlash"""
	phone_number = message.text.strip() if message.text else ""
	
	if not validate_phone_number(phone_number):
		await show_error_and_retry(
			message, state, bot,
			"⚠️ Iltimos, to'g'ri telefon raqamini kiriting.\n\n"
			"💡 Masalan: +998901234567 yoki 998901234567\n\n"
			"Qaytadan kiriting:"
		)
		return
	
	await state.update_data(phone_number=phone_number)
	await process_step(
		message, state, bot,
		ReportState.waiting_for_additional_phone_question,
		"📱 Mijozning qo'shimcha telefon raqami bormi?\n\n"
		"💡 Agar bor bo'lsa, uni ham qo'shishingiz mumkin.",
		get_yes_no_additional_phone_inline_keyboard()
	)
	
	logging.info(f"Telefon raqami qayta ishlandi: {phone_number}")

@otchot_router.callback_query(ReportState.waiting_for_additional_phone_question, F.data == "add_phone_yes")
async def ask_additional_phone(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""Qo'shimcha telefon raqamini so'rash"""
	await callback_query.message.edit_text(
		"📱 Qo'shimcha telefon raqamini kiriting:\n\n"
		"💡 Masalan: +998901234567 yoki 998901234567",
		reply_markup=get_cancel_report_inline_keyboard()
	)
	await state.set_state(ReportState.waiting_for_additional_phone_number)
	await callback_query.answer()

@otchot_router.callback_query(ReportState.waiting_for_additional_phone_question, F.data == "add_phone_no")
async def skip_additional_phone(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""Qo'shimcha telefon raqamini o'tkazib yuborish"""
	await state.update_data(additional_phone_number=None)
	await callback_query.message.edit_text(
		"🛍️ Mahsulot nomini kiriting:\n\n"
		"💡 Masalan: Samsung Galaxy A54 128GB yoki iPhone 15 Pro",
		reply_markup=get_cancel_report_inline_keyboard()
	)
	await state.set_state(ReportState.waiting_for_product_type)
	await callback_query.answer()

@otchot_router.message(ReportState.waiting_for_additional_phone_number)
async def process_additional_phone_number(message: Message, state: FSMContext, bot: Bot):
	"""Qo'shimcha telefon raqamini qayta ishlash"""
	additional_phone = message.text.strip() if message.text else ""
	
	if not validate_phone_number(additional_phone):
		await show_error_and_retry(
			message, state, bot,
			"⚠️ Iltimos, to'g'ri telefon raqamini kiriting.\n\n"
			"💡 Masalan: +998901234567 yoki 998901234567\n\n"
			"Qaytadan kiriting:"
		)
		return
	
	await state.update_data(additional_phone_number=additional_phone)
	await process_step(
		message, state, bot,
		ReportState.waiting_for_product_type,
		"🛍️ Mahsulot nomini kiriting:\n\n"
		"💡 Masalan: Samsung Galaxy A54 128GB yoki iPhone 15 Pro"
	)
	
	logging.info(f"Qo'shimcha telefon raqami qayta ishlandi: {additional_phone}")

@otchot_router.message(ReportState.waiting_for_product_type)
async def process_product_type(message: Message, state: FSMContext, bot: Bot):
	"""Mahsulot turini qayta ishlash"""
	product_type = message.text.strip() if message.text else ""
	
	if not validate_text_field(product_type, 2):
		await show_error_and_retry(
			message, state, bot,
			"⚠️ Iltimos, mahsulot nomini to'g'ri kiriting (kamida 2 belgi).\n\n"
			"💡 Masalan: Samsung Galaxy A54 128GB\n\n"
			"Qaytadan kiriting:"
		)
		return
	
	await state.update_data(product_type=product_type)
	await process_step(
		message, state, bot,
		ReportState.waiting_for_client_location_text,
		"📍 Mijozning to'liq manzilini kiriting:\n\n"
		"💡 Masalan: Toshkent shahar, Chilonzor tumani, Bunyodkor ko'chasi 12-uy"
	)
	
	logging.info(f"Mahsulot turi qayta ishlandi: {product_type}")

@otchot_router.message(ReportState.waiting_for_client_location_text, F.text)
async def process_client_location_text(message: Message, state: FSMContext, bot: Bot):
	"""Mijoz manzilini qayta ishlash"""
	client_location_text = message.text.strip() if message.text else ""
	
	if not validate_text_field(client_location_text, 10):
		await show_error_and_retry(
			message, state, bot,
			"⚠️ Iltimos, mijoz manzilini to'liqroq kiriting (kamida 10 belgi).\n\n"
			"💡 Masalan: Toshkent shahar, Chilonzor tumani, Bunyodkor ko'chasi 12-uy\n\n"
			"Qaytadan kiriting:"
		)
		return
	
	await state.update_data(client_location=client_location_text)
	await process_step(
		message, state, bot,
		ReportState.waiting_for_contract_id,
		"📄 Shartnoma ID raqamini kiriting:\n\n"
		"💡 Masalan: SH-2024-001 yoki 240115001"
	)
	
	logging.info(f"Mijoz manzili qayta ishlandi: {client_location_text}")

@otchot_router.message(ReportState.waiting_for_contract_id)
async def process_contract_id(message: Message, state: FSMContext, bot: Bot):
	"""Shartnoma ID'sini qayta ishlash"""
	contract_id = message.text.strip() if message.text else ""
	
	if not validate_text_field(contract_id, 3):
		await show_error_and_retry(
			message, state, bot,
			"⚠️ Iltimos, shartnoma ID raqamini kiriting (kamida 3 belgi).\n\n"
			"💡 Masalan: SH-2024-001 yoki 240115001\n\n"
			"Qaytadan kiriting:"
		)
		return
	
	await state.update_data(contract_id=contract_id)
	await process_step(
		message, state, bot,
		ReportState.waiting_for_contract_amount,
		"💰 Shartnoma summasini kiriting:\n\n"
		"💡 Masalan: 5000000 yoki 5,000,000 yoki 5.000.000\n"
		"📝 Raqamlarni istalgan formatda kiritishingiz mumkin"
	)
	
	logging.info(f"Shartnoma ID qayta ishlandi: {contract_id}")

@otchot_router.message(ReportState.waiting_for_contract_amount)
async def process_contract_amount(message: Message, state: FSMContext, bot: Bot):
	"""Shartnoma summasini qayta ishlash"""
	contract_amount_raw = message.text.strip() if message.text else ""
	
	# Kamida bitta raqam bo'lishi kerak
	if not contract_amount_raw or not any(char.isdigit() for char in contract_amount_raw):
		await show_error_and_retry(
			message, state, bot,
			"⚠️ Iltimos, shartnoma summasini kiriting.\n\n"
			"💡 Masalan: 5000000 yoki 5,000,000 yoki 5.000.000\n\n"
			"Qaytadan kiriting:"
		)
		return
	
	# Summani formatlash
	formatted_amount = format_amount(contract_amount_raw)
	
	# Foydalanuvchiga formatlangan summani ko'rsatish
	if formatted_amount != contract_amount_raw:
		try:
			confirmation_message = await message.answer(
				f"💰 Kiritilgan summa: {contract_amount_raw}\n"
				f"📊 Formatlangan summa: {formatted_amount}\n\n"
				f"✅ Summa to'g'ri formatlandi va saqlandi!"
			)
			# 2 soniyadan keyin xabarni o'chirish
			import asyncio
			await asyncio.sleep(2)
			await bot.delete_message(message.chat.id, confirmation_message.message_id)
		except Exception:
			pass
	
	await state.update_data(contract_amount=formatted_amount)
	await process_step(
		message, state, bot,
		ReportState.waiting_for_product_image,
		"🖼️ Mahsulot rasmini yuboring:\n\n"
		"💡 Faqat rasm formatida yuborishingiz kerak (JPG, PNG)"
	)
	
	logging.info(f"Shartnoma summasi qayta ishlandi: {contract_amount_raw} -> {formatted_amount}")

@otchot_router.message(ReportState.waiting_for_product_image, F.photo)
async def process_product_image(message: Message, state: FSMContext, bot: Bot):
	"""Mahsulot rasmini qayta ishlash"""
	await state.update_data(last_user_reply_id=message.message_id)
	await delete_previous_messages(bot, message.chat.id, state)
	
	# Eng yuqori sifatli rasmni olish
	photo_file_id = message.photo[-1].file_id
	await state.update_data(product_image_id=photo_file_id)
	
	# Foydalanuvchi ma'lumotlarini olish
	user_data = await state.get_data()
	user_info = await get_user_by_telegram_id(message.from_user.id)
	registered_name = user_info[2] if user_info else message.from_user.full_name
	
	# Qo'shimcha telefon matnini tayyorlash
	additional_phone_text = ""
	if user_data.get('additional_phone_number'):
		additional_phone_text = f"\n📱 Qo'shimcha telefon: {user_data.get('additional_phone_number')}"
	
	# Tasdiqlash matnini yaratish
	confirmation_text = f"""📋 HISOBOT TASDIQLANISHI

Kiritilgan ma'lumotlarni tekshiring:

👤 Mijoz: {user_data.get('client_name', 'Noma\'lum')}
📱 Telefon: {user_data.get('phone_number', 'Noma\'lum')}{additional_phone_text}
🛍️ Mahsulot: {user_data.get('product_type', 'Noma\'lum')}
📍 Manzil: {user_data.get('client_location', 'Noma\'lum')}
📄 Shartnoma ID: {user_data.get('contract_id', 'Noma\'lum')}
💰 Shartnoma summasi: {user_data.get('contract_amount', 'Noma\'lum')} so'm
👨‍💼 Sotuvchi: {registered_name}

❓ Barcha ma'lumotlar to'g'rimi?"""
	
	await state.set_state(ReportState.waiting_for_confirmation)
	await message.answer_photo(
		photo=photo_file_id,
		caption=confirmation_text,
		reply_markup=get_report_confirmation_keyboard()
	)
	
	logging.info(f"Mahsulot rasmi qayta ishlandi: {message.from_user.id}")

@otchot_router.message(ReportState.waiting_for_product_image)
async def incorrect_product_image(message: Message, state: FSMContext, bot: Bot):
	"""Noto'g'ri fayl formatini qayta ishlash"""
	await show_error_and_retry(
		message, state, bot,
		"⚠️ Iltimos, faqat rasm yuboring!\n\n"
		"💡 JPG yoki PNG formatidagi rasm yuborishingiz kerak.\n\n"
		"Qaytadan rasm yuboring:"
	)

# TASDIQLASH VA TAHRIRLASH

@otchot_router.callback_query(ReportState.waiting_for_confirmation, F.data == "confirm_report")
async def confirm_report_submission(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""Hisobotni tasdiqlash va guruhga yuborish"""
	user_id = callback_query.from_user.id
	
	# Foydalanuvchi ma'lumotlarini olish
	user_info = await get_user_by_telegram_id(user_id)
	registered_name = user_info[2] if user_info else callback_query.from_user.full_name
	
	# Tayinlangan guruhni tekshirish
	assigned_group = await get_user_assigned_group(user_id)
	if not assigned_group:
		await callback_query.answer("⚠️ Sizga guruh tayinlanmagan. Admin bilan bog'laning.", show_alert=True)
		await state.clear()
		return
	
	group_id, group_name, topic_id, google_sheet_id = assigned_group
	user_data = await state.get_data()
	
	# Qo'shimcha telefon qatorini tayyorlash
	additional_phone_line = ""
	if user_data.get('additional_phone_number'):
		additional_phone_line = f"📱 Qo'shimcha telefon: {user_data.get('additional_phone_number')}\n"
	
	# Guruh uchun hisobot matnini tayyorlash
	status_line = "Holati: ⏳ Kutilmoqda"
	report_caption = REPORT_CAPTION_TEMPLATE.format(
		client_name=user_data.get('client_name', 'Noma\'lum'),
		phone_number=user_data.get('phone_number', 'Noma\'lum'),
		additional_phone_line=additional_phone_line,
		product_type=user_data.get('product_type', 'Noma\'lum'),
		client_location=user_data.get('client_location', 'Noma\'lum'),
		contract_id=user_data.get('contract_id', 'Noma\'lum'),
		contract_amount=user_data.get('contract_amount', 'Noma\'lum') + " so'm",
		sender_full_name=registered_name,
		status_line=status_line
	)
	
	try:
		# Guruhga hisobotni yuborish
		group_message_sent = await bot.send_photo(
			chat_id=group_id,
			photo=user_data.get('product_image_id'),
			caption=report_caption,
			parse_mode=ParseMode.HTML,
			message_thread_id=topic_id,
			reply_markup=get_group_report_keyboard()
		)
		
		# Ma'lumotlar bazasiga saqlash (faqat asosiy telefon raqami)
		group_msg_id_to_save = group_message_sent.message_id if group_message_sent else None
		report_id = await add_sales_report(user_id, user_data, group_msg_id_to_save, google_sheet_id)
		
		# Foydalanuvchiga muvaffaqiyat xabarini yuborish
		await callback_query.message.edit_caption(
			caption="✅ Hisobotingiz muvaffaqiyatli yuborildi!\n\n"
			        "🎯 Hisobotingiz tekshirilish uchun yuborildi.\n"
			        "📊 Tasdiqlangandan so'ng Google Sheets'ga saqlanadi.",
			reply_markup=None
		)
		
		await callback_query.message.answer(
			f"🎉 Hisobotingiz '{group_name}' guruhiga yuborildi!\n\n"
			f"📋 Hisobot ID: #{report_id}\n"
			f"⏰ Yuborilgan vaqt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
			f"✅ Hisobotingiz tez orada ko'rib chiqiladi.",
			reply_markup=get_main_menu_reply_keyboard()
		)
		
		logging.info(f"Hisobot muvaffaqiyatli yuborildi: {group_name} - {user_id}")
	
	except Exception as e:
		logging.error(f"Hisobotni guruhga yuborishda xatolik: {e}")
		await callback_query.answer("❌ Hisobotni yuborishda xatolik yuz berdi!", show_alert=True)
		return
	
	await state.clear()
	await callback_query.answer("✅ Hisobot muvaffaqiyatli yuborildi!")

@otchot_router.callback_query(ReportState.waiting_for_confirmation, F.data == "edit_report")
async def edit_report(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""Hisobotni tahrirlash"""
	await callback_query.message.edit_caption(
		caption="✏️ Qaysi ma'lumotni o'zgartirmoqchisiz?\n\n"
		        "Kerakli tugmani bosing:",
		reply_markup=get_edit_selection_keyboard()
	)
	await state.set_state(ReportState.waiting_for_edit_selection)
	await callback_query.answer()

@otchot_router.callback_query(ReportState.waiting_for_confirmation, F.data == "cancel_report")
async def cancel_report_final(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""Hisobotni yakuniy bekor qilish"""
	await state.clear()
	await callback_query.message.edit_caption(
		caption="🚫 Hisobot bekor qilindi.\n\n"
		        "Ma'lumotlar saqlanmadi.",
		reply_markup=None
	)
	await callback_query.message.answer(
		"🏠 Asosiy menyuga qaytdingiz.",
		reply_markup=get_main_menu_reply_keyboard()
	)
	await callback_query.answer()
	
	logging.info(f"Hisobot bekor qilindi: {callback_query.from_user.id}")

# TAHRIRLASH JARAYONI

@otchot_router.callback_query(ReportState.waiting_for_edit_selection, F.data.startswith("edit_"))
async def handle_edit_selection(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""Tahrirlash tanlovini qayta ishlash"""
	edit_parts = callback_query.data.split("_")
	
	# Edit turini aniqlash
	if len(edit_parts) >= 3:
		if edit_parts[1] == "client" and edit_parts[2] == "name":
			edit_type = "client_name"
		elif edit_parts[1] == "contract" and edit_parts[2] == "id":
			edit_type = "contract_id"
		elif edit_parts[1] == "contract" and edit_parts[2] == "amount":
			edit_type = "contract_amount"
		elif edit_parts[1] == "additional" and edit_parts[2] == "phone":
			edit_type = "additional_phone"
		else:
			edit_type = edit_parts[1]
	else:
		edit_type = edit_parts[1]
	
	# Tahrirlash turi bo'yicha holat va xabarni belgilash
	edit_configs = {
		"client_name": {
			"state": ReportState.waiting_for_client_name,
			"prompt": "👤 Mijozning yangi ismini kiriting:\n\n💡 Masalan: Abdullayev Akmal Akbarovich"
		},
		"phone": {
			"state": ReportState.waiting_for_phone_number,
			"prompt": "📱 Yangi telefon raqamini kiriting:\n\n💡 Masalan: +998901234567"
		},
		"additional_phone": {
			"state": ReportState.waiting_for_additional_phone_number,
			"prompt": "📱 Yangi qo'shimcha telefon raqamini kiriting:\n\n💡 Masalan: +998901234567"
		},
		"product": {
			"state": ReportState.waiting_for_product_type,
			"prompt": "🛍️ Yangi mahsulot nomini kiriting:\n\n💡 Masalan: Samsung Galaxy A54 128GB"
		},
		"location": {
			"state": ReportState.waiting_for_client_location_text,
			"prompt": "📍 Yangi manzilni kiriting:\n\n💡 Masalan: Toshkent shahar, Chilonzor tumani"
		},
		"contract_id": {
			"state": ReportState.waiting_for_contract_id,
			"prompt": "📄 Yangi shartnoma ID'sini kiriting:\n\n💡 Masalan: SH-2024-001"
		},
		"contract_amount": {
			"state": ReportState.waiting_for_contract_amount,
			"prompt": "💰 Yangi shartnoma summasini kiriting:\n\n💡 Masalan: 5000000 yoki 5,000,000"
		},
		"image": {
			"state": ReportState.waiting_for_product_image,
			"prompt": "🖼️ Yangi mahsulot rasmini yuboring:\n\n💡 Faqat rasm formatida (JPG, PNG)"
		}
	}
	
	config = edit_configs.get(edit_type)
	if not config:
		await callback_query.answer("❌ Noto'g'ri tanlov!", show_alert=True)
		return
	
	await state.set_state(config["state"])
	await callback_query.message.edit_caption(
		caption=config["prompt"],
		reply_markup=get_cancel_report_inline_keyboard()
	)
	await callback_query.answer()

@otchot_router.callback_query(ReportState.waiting_for_edit_selection, F.data == "back_to_confirmation")
async def back_to_confirmation(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""Tasdiqlash sahifasiga qaytish"""
	user_data = await state.get_data()
	user_info = await get_user_by_telegram_id(callback_query.from_user.id)
	registered_name = user_info[2] if user_info else callback_query.from_user.full_name
	
	# Qo'shimcha telefon matnini tayyorlash
	additional_phone_text = ""
	if user_data.get('additional_phone_number'):
		additional_phone_text = f"\n📱 Qo'shimcha telefon: {user_data.get('additional_phone_number')}"
	
	confirmation_text = f"""📋 HISOBOT TASDIQLANISHI

Kiritilgan ma'lumotlarni tekshiring:

👤 Mijoz: {user_data.get('client_name', 'Noma\'lum')}
📱 Telefon: {user_data.get('phone_number', 'Noma\'lum')}{additional_phone_text}
🛍️ Mahsulot: {user_data.get('product_type', 'Noma\'lum')}
📍 Manzil: {user_data.get('client_location', 'Noma\'lum')}
📄 Shartnoma ID: {user_data.get('contract_id', 'Noma\'lum')}
💰 Shartnoma summasi: {user_data.get('contract_amount', 'Noma\'lum')} so'm
👨‍💼 Sotuvchi: {registered_name}

❓ Barcha ma'lumotlar to'g'rimi?"""
	
	await state.set_state(ReportState.waiting_for_confirmation)
	await callback_query.message.edit_caption(
		caption=confirmation_text,
		reply_markup=get_report_confirmation_keyboard()
	)
	await callback_query.answer()

# GURUH HISOBOTLARINI BOSHQARISH

@otchot_router.callback_query(F.data == "confirm_report_action")
async def confirm_report_handler(callback_query: CallbackQuery, bot: Bot):
	"""Guruhda hisobotni tasdiqlash"""
	user_id = callback_query.from_user.id
	msg = callback_query.message
	
	# Faqat helper tasdiqlashi mumkin
	if user_id != HELPER_ID:
		await callback_query.answer("🚫 Sizda bu amalni bajarish uchun ruxsat yo'q.", show_alert=True)
		return
	
	if not msg or not msg.caption:
		await callback_query.answer("❌ Xatolik: Asl xabarni topib bo'lmadi.", show_alert=True)
		return
	
	# Allaqachon tasdiqlangan hisobotni tekshirish
	if "Holati: ✅ Tasdiqlandi" in msg.caption:
		await callback_query.answer("ℹ️ Bu hisobot allaqachon tasdiqlangan.", show_alert=True)
		return
	
	# Hisobot holatini yangilash
	filtered_lines = [line.strip() for line in msg.caption.splitlines() if line.strip()]
	
	if filtered_lines and filtered_lines[-1].startswith("Holati:"):
		filtered_lines[-1] = "Holati: ✅ Tasdiqlandi"
	else:
		filtered_lines.append("Holati: ✅ Tasdiqlandi")
	
	updated_caption = "\n".join(filtered_lines)
	
	try:
		# Guruh xabarini yangilash
		await bot.edit_message_caption(
			chat_id=msg.chat.id,
			message_id=msg.message_id,
			caption=updated_caption,
			reply_markup=get_report_confirmed_keyboard()
		)
		
		# Ma'lumotlar bazasida holatni yangilash
		await update_report_status_in_db(msg.message_id, "confirmed", user_id)
		
		# Google Sheets'ga saqlash
		await save_report_to_google_sheets(msg)
		
		await callback_query.answer("✅ Hisobot muvaffaqiyatli tasdiqlandi va Google Sheets'ga saqlandi!",
		                            show_alert=True)
	
	except Exception as e:
		logging.error(f"Hisobotni tasdiqlashda xatolik: {e}")
		await callback_query.answer("❌ Xatolik: Hisobotni tasdiqlashda muammo yuz berdi.", show_alert=True)

async def save_report_to_google_sheets(msg):
	"""Hisobotni Google Sheets'ga saqlash"""
	try:
		group_sheet_info = await get_group_google_sheet(msg.chat.id)
		if not group_sheet_info:
			logging.info("Bu guruh uchun Google Sheet tayinlanmagan.")
			return
		
		sheet_id, sheet_name, spreadsheet_id, worksheet_name = group_sheet_info
		
		# Hisobot ma'lumotlarini ajratib olish
		report_data = {}
		for line in msg.caption.splitlines():
			if "Mijoz:" in line:
				report_data['client_name'] = line.split(":", 1)[1].strip()
			elif "Telefon:" in line and "Qo'shimcha" not in line:
				report_data['phone_number'] = line.split(":", 1)[1].strip()
			elif "Mahsulot:" in line:
				report_data['product_type'] = line.split(":", 1)[1].strip()
			elif "Manzil:" in line:
				report_data['client_location'] = line.split(":", 1)[1].strip()
			elif "Shartnoma ID:" in line:
				report_data['contract_id'] = line.split(":", 1)[1].strip()
			elif "Shartnoma summasi:" in line:
				amount_text = line.split(":", 1)[1].strip()
				# "so'm" so'zini olib tashlash
				amount_text = amount_text.replace(" so'm", "").strip()
				report_data['contract_amount'] = amount_text
			elif "Sotuvchi:" in line:
				report_data['sender_full_name'] = line.split(":", 1)[1].strip()
		
		report_data['status'] = 'Tasdiqlandi'
		
		# Google Sheets'ga saqlash
		success = save_report_to_sheets(spreadsheet_id, worksheet_name, report_data)
		if success:
			logging.info(f"Hisobot muvaffaqiyatli Google Sheets'ga saqlandi: {sheet_name}")
		else:
			logging.error(f"Google Sheets'ga saqlashda xatolik: {sheet_name}")
	
	except Exception as e:
		logging.error(f"Google Sheets'ga saqlashda xatolik: {e}")

@otchot_router.callback_query(F.data == "reject_report_action")
async def reject_report_handler(callback_query: CallbackQuery, bot: Bot):
	"""Guruhda hisobotni rad etish"""
	user_id = callback_query.from_user.id
	msg = callback_query.message
	
	# Faqat helper rad etishi mumkin
	if user_id != HELPER_ID:
		await callback_query.answer("🚫 Sizda bu amalni bajarish uchun ruxsat yo'q.", show_alert=True)
		return
	
	if not msg or not msg.caption:
		await callback_query.answer("❌ Xatolik: Asl xabarni topib bo'lmadi.", show_alert=True)
		return
	
	# Sotuvchi ma'lumotlarini topish
	sender_name = None
	for line in msg.caption.splitlines():
		if "Sotuvchi:" in line:
			sender_name = line.split(":", 1)[1].strip()
			break
	
	try:
		# Guruh xabarini o'chirish
		await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
		
		# Ma'lumotlar bazasida holatni yangilash
		await update_report_status_in_db(msg.message_id, "rejected", user_id)
		
		# Sotuvchiga xabar yuborish
		if sender_name:
			sender_telegram_id = await find_user_by_name(sender_name)
			if sender_telegram_id:
				await bot.send_message(
					chat_id=sender_telegram_id,
					text=f"❌ Sizning hisobotingiz rad etildi.\n\n"
					     f"📞 Rad etilish sababi haqida ma'lumot olish uchun quyidagi tugmani bosing:",
					reply_markup=get_rejection_reason_keyboard(user_id)
				)
		
		await callback_query.answer("❌ Hisobot rad etildi va o'chirildi!", show_alert=True)
		logging.info(f"Hisobot rad etildi: helper {user_id}")
	
	except Exception as e:
		logging.error(f"Hisobotni rad etishda xatolik: {e}")
		await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

@otchot_router.callback_query(F.data.startswith("contact_helper_"))
async def contact_helper(callback_query: CallbackQuery, bot: Bot):
	"""Helper bilan bog'lanish"""
	helper_id = int(callback_query.data.split("_")[-1])
	
	await callback_query.message.edit_text(
		f"📞 Hisobotingiz rad etilish sababi haqida ma'lumot olish uchun helper bilan bog'laning:\n\n"
		f"💬 Quyidagi tugmani bosib, to'g'ridan-to'g'ri helper bilan suhbat boshlashingiz mumkin.",
		reply_markup=get_contact_helper_keyboard(helper_id)
	)
	await callback_query.answer()

# SOTUVCHI MA'LUMOTLARINI TO'LIQ KO'RISH

@otchot_router.callback_query(F.data == "view_seller_info")
async def view_seller_info(callback_query: CallbackQuery, bot: Bot):
	"""
	Sotuvchi ma'lumotlarini to'liq ko'rish - Helper bilan bog'lanishga o'xshash
	"""
	msg = callback_query.message
	
	if not msg or not msg.caption:
		await callback_query.answer("❌ Xatolik: Ma'lumot topilmadi.", show_alert=True)
		return
	
	# Sotuvchi ismini ajratib olish
	seller_name = None
	for line in msg.caption.splitlines():
		if "Sotuvchi:" in line:
			seller_name = line.split(":", 1)[1].strip()
			break
	
	if not seller_name:
		await callback_query.answer("❌ Sotuvchi ma'lumoti topilmadi.", show_alert=True)
		return
	
	# Sotuvchi telegram ID'sini topish
	seller_telegram_id = await find_user_by_name(seller_name)
	
	if not seller_telegram_id:
		await callback_query.answer(f"👨‍💼 Sotuvchi: {seller_name}\n❌ Profil ma'lumotlari topilmadi.", show_alert=True)
		return
	
	try:
		# Sotuvchi batafsil profil ma'lumotlarini olish
		profile_data = await get_seller_detailed_profile(seller_telegram_id)
		
		if not profile_data:
			await callback_query.answer(f"👨‍💼 Sotuvchi: {seller_name}\n❌ Profil ma'lumotlarini olishda xatolik.",
			                            show_alert=True)
			return
		
		# Profil xabarini formatlash
		profile_message = format_seller_profile_message(profile_data)
		
		# Yangi xabar yuborish (helper bilan bog'lanishga o'xshab)
		await callback_query.message.answer(
			text=profile_message,
			reply_markup=get_seller_contact_keyboard(seller_telegram_id),
			parse_mode=ParseMode.MARKDOWN
		)
		
		await callback_query.answer("👨‍💼 Sotuvchi profili ko'rsatildi")
		logging.info(f"Sotuvchi profili ko'rsatildi: {seller_name} ({seller_telegram_id})")
	
	except Exception as e:
		logging.error(f"Sotuvchi profili ko'rsatishda xatolik: {e}")
		await callback_query.answer("❌ Profil ma'lumotlarini olishda xatolik yuz berdi.", show_alert=True)

@otchot_router.callback_query(F.data == "back_to_group_report")
async def back_to_group_report(callback_query: CallbackQuery, bot: Bot):
	"""
	Sotuvchi profilidan guruh hisobotiga qaytish
	"""
	try:
		# Xabarni o'chirish
		await callback_query.message.delete()
		await callback_query.answer("🔙 Guruh hisobotiga qaytildi")
	
	except Exception as e:
		logging.error(f"Guruh hisobotiga qaytishda xatolik: {e}")
		await callback_query.answer("Xabar o'chirildi", show_alert=True)

@otchot_router.callback_query(F.data == "status_confirmed_noop")
async def confirmed_noop_handler(callback_query: CallbackQuery):
	"""Tasdiqlangan hisobot tugmasini bosish"""
	await callback_query.answer("ℹ️ Bu hisobot allaqachon tasdiqlangan.")

# LOGGING SOZLAMALARI
logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
	handlers=[
		logging.StreamHandler(),
		logging.FileHandler('otchot.log', encoding='utf-8')
	]
)

# MODUL MA'LUMOTLARI
logging.info("📝 Otchot router muvaffaqiyatli yuklandi")
logging.info(
	"🔄 Hisobot jarayoni: Mijoz → Telefon → Qo'shimcha telefon → Mahsulot → Manzil → Shartnoma ID → Summa → Rasm → Tasdiqlash")
logging.info("💰 Summa formatlash: 500000 → 500.000")
logging.info("📱 Qo'shimcha telefon: Guruhga yuboriladi, Google Sheets'ga saqlanmaydi")
logging.info("👨‍💼 Sotuvchi profili: To'liq batafsil ma'lumotlar")
logging.info("🔗 Sotuvchi bilan bog'lanish: Helper kabi ishlaydi")
logging.info("🔧 Optimallashtirilgan va to'liq tangilangan versiya")
