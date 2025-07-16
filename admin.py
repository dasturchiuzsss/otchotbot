import logging
import re
from datetime import datetime, timedelta, date

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from config import HELPER_ID, ADMIN_ID
from database import (
	get_all_users, delete_user_from_db, get_all_sales_reports, delete_sales_report,
	add_telegram_group, get_all_telegram_groups, delete_telegram_group,
	add_google_sheet, get_all_google_sheets, delete_google_sheet, get_google_sheet_by_id,
	get_users_paginated, get_user_by_telegram_id, get_reports_by_user,
	block_user, unblock_user, check_user_blocked, update_user_name, get_user_reports_count,
	update_user_group, get_telegram_group_by_id, get_database_stats,
	get_reports_count_by_date, get_total_users_count, get_total_reports_count,
	get_confirmed_reports_count, get_pending_reports_count, get_current_password,
	update_password, update_group_google_sheet
)
from keyboards import (
	get_main_menu_reply_keyboard, get_admin_cancel_inline_keyboard,
	get_admin_menu_inline_keyboard, get_workers_list_keyboard,
	get_worker_management_keyboard, get_groups_list_keyboard,
	get_worker_groups_keyboard, get_google_sheets_keyboard,
	get_reports_stats_keyboard, get_worker_sales_back_keyboard,
	get_sheets_list_keyboard, get_sheet_management_keyboard,
	get_google_sheets_selection_keyboard, get_password_change_keyboard,
	get_settings_keyboard
)
from google_sheets_integration import (
	test_google_sheets_connection, get_reports_statistics,
	save_report_to_sheets, get_worksheet
)

admin_router = Router()

class AdminStates(StatesGroup):
	waiting_for_group_link = State()
	waiting_for_group_name = State()
	waiting_for_group_sheet_selection = State()
	waiting_for_group_id_to_delete = State()
	waiting_for_sheet_name = State()
	waiting_for_google_sheet_url = State()
	waiting_for_google_sheet_worksheet_name = State()
	waiting_for_new_password = State()
	waiting_for_password_confirmation = State()

def is_admin(user_id: int) -> bool:
	return user_id == ADMIN_ID

def format_workers_list(workers: list) -> str:
	if not workers:
		return "📂 Ishchilar ro'yxati:\n\nHozircha ishchilar yo'q"
	
	text = "📂 Ishchilar ro'yxati:\n\n"
	
	for i, worker in enumerate(workers, 1):
		user_id, telegram_id, full_name, reg_date, is_blocked, group_name = worker
		
		status_icon = "🔒" if is_blocked else "✅"
		
		text += f"{i}. {status_icon} {full_name}\n"
		text += f"   📱 ID: {telegram_id}\n"
		text += f"   👥 Guruh: {group_name}\n"
		text += f"   📅 {reg_date.split(' ')[0]}\n\n"
	
	text += "💡 Ishchi tanlash uchun raqamli tugmalardan foydalaning"
	return text

def format_groups_list(groups: list) -> str:
	if not groups:
		return "🏢 GURUHLAR\n\nHozircha guruhlar yo'q"
	
	text = "🏢 GURUHLAR\n\n"
	for i, group in enumerate(groups, 1):
		db_id, group_id, group_name, topic_id, google_sheet_id, sheet_name = group
		text += f"{i}. 📁 {group_name}\n"
		text += f"   🆔 ID: {group_id}\n"
		text += f"   📋 Mavzu: {topic_id if topic_id else 'Yo\'q'}\n"
		text += f"   📊 Google Sheet: {sheet_name}\n\n"
	
	text += f"📊 Jami: {len(groups)} ta guruh"
	return text

def format_sheets_list(sheets: list) -> str:
	if not sheets:
		return "📊 GOOGLE SHEETS\n\nHozircha sheetlar yo'q"
	
	text = "📊 GOOGLE SHEETS\n\n"
	for i, sheet in enumerate(sheets, 1):
		sheet_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet
		text += f"{i}. 📊 {sheet_name}\n"
		text += f"   🆔 ID: {spreadsheet_id[:20]}...\n"
		text += f"   📋 Varaq: {worksheet_name}\n"
		text += f"   🔘 Holat: {'Faol' if is_active else 'Nofaol'}\n\n"
	
	text += f"📈 Jami: {len(sheets)} ta sheet"
	return text

def format_worker_sales(worker_name: str, reports: list) -> str:
	if not reports:
		return f"📊 {worker_name} SOTUVLARI\n\nHozircha sotuvlar yo'q"
	
	text = f"📊 {worker_name} SOTUVLARI\n\n"
	
	for i, report in enumerate(reports[:10], 1):
		report_id, user_telegram_id, client_name, phone_number, additional_phone_number, contract_id, product_type, client_location, product_image_id, submission_date, submission_timestamp, status, confirmed_by_helper_id, confirmation_timestamp, group_message_id, google_sheet_id = report
		
		status_icon = "✅" if status == "confirmed" else "⏳"
		
		text += (
			f"{i}. {status_icon} ID: {report_id}\n"
			f"   👤 Mijoz: {client_name}\n"
			f"   📱 Tel: {phone_number}\n"
			f"   📄 Shartnoma: {contract_id}\n"
			f"   📅 Sana: {submission_date}\n\n"
		)
	
	text += f"📈 Jami: {len(reports)} ta hisobot"
	if len(reports) > 10:
		text += " (so'nggi 10 tasi)"
	
	return text

@admin_router.message(Command("admin"))
async def handle_admin_command(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Sizda bu buyruqdan foydalanish uchun ruxsat yo'q.")
		return
	
	await state.clear()
	await message.answer(
		"👨‍💻 ADMIN PANEL\n\nKerakli bo'limni tanlang:",
		reply_markup=get_admin_menu_inline_keyboard()
	)
	logging.info(f"Admin {message.from_user.id} admin panelga kirdi")

@admin_router.callback_query(F.data == "admin_workers")
async def show_workers(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	workers, total_pages, total_count = await get_users_paginated(1, 20)
	
	if not workers:
		text = "📂 Ishchilar ro'yxati:\n\nHozircha ishchilar yo'q"
		keyboard = get_admin_menu_inline_keyboard()
	else:
		text = format_workers_list(workers)
		text += f"\n\n📊 Jami: {total_count} ta ishchi"
		keyboard = get_workers_list_keyboard(workers)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=keyboard)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=keyboard)
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("worker_select_"))
async def show_worker_details(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	worker = await get_user_by_telegram_id(telegram_id)
	
	if not worker:
		await callback_query.answer("❌ Ishchi topilmadi!", show_alert=True)
		return
	
	user_id, telegram_id, full_name, reg_date, is_blocked, group_name = worker
	reports_count = await get_user_reports_count(telegram_id)
	
	status_text = "🔒 BLOKLANGAN" if is_blocked else "✅ FAOL"
	
	text = (
		f"👤 ISHCHI MA'LUMOTLARI\n\n"
		f"📝 Ism: {full_name}\n"
		f"🆔 Telegram ID: {telegram_id}\n"
		f"👥 Guruh: {group_name}\n"
		f"📅 Ro'yxatga olindi: {reg_date.split(' ')[0]}\n"
		f"📊 Jami hisobotlar: {reports_count} ta\n"
		f"🔘 Holat: {status_text}\n\n"
		f"💡 Kerakli amalni tanlang:"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_worker_management_keyboard(telegram_id))
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_worker_management_keyboard(telegram_id))
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("worker_sales_"))
async def show_worker_sales(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	worker = await get_user_by_telegram_id(telegram_id)
	reports = await get_reports_by_user(telegram_id, 10)
	
	if not worker:
		await callback_query.answer("❌ Ishchi topilmadi!", show_alert=True)
		return
	
	full_name = worker[2]
	text = format_worker_sales(full_name, reports)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_worker_sales_back_keyboard(telegram_id))
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_worker_sales_back_keyboard(telegram_id))
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("worker_block_"))
async def toggle_worker_block(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	is_blocked = await check_user_blocked(telegram_id)
	
	if is_blocked:
		success = await unblock_user(telegram_id)
		message = "🔓 Ishchi blokdan chiqarildi!" if success else "❌ Xatolik yuz berdi!"
	else:
		success = await block_user(telegram_id)
		message = "🔒 Ishchi bloklandi!" if success else "❌ Xatolik yuz berdi!"
	
	await callback_query.answer(message, show_alert=True)
	
	if success:
		await show_worker_details(callback_query, state)

@admin_router.callback_query(F.data.startswith("worker_group_"))
async def change_worker_group(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	groups = await get_all_telegram_groups()
	
	if not groups:
		await callback_query.answer("❌ Guruhlar mavjud emas!", show_alert=True)
		return
	
	text = "👥 Ishchi uchun guruh tanlang:"
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_worker_groups_keyboard(groups, telegram_id))
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_worker_groups_keyboard(groups, telegram_id))
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("assign_worker_"))
async def assign_worker_to_group(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	parts = callback_query.data.split("_")
	worker_telegram_id = int(parts[2])
	group_id = int(parts[3])
	
	success = await update_user_group(worker_telegram_id, group_id)
	
	if success:
		group_info = await get_telegram_group_by_id(group_id)
		group_name = group_info[2] if group_info else "Noma'lum"
		await callback_query.answer(f"✅ Ishchi '{group_name}' guruhiga tayinlandi!", show_alert=True)
		logging.info(f"Worker {worker_telegram_id} assigned to group {group_id} by admin")
	else:
		await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
	
	await show_worker_details(callback_query, state)

@admin_router.callback_query(F.data.startswith("worker_delete_"))
async def delete_worker(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	worker = await get_user_by_telegram_id(telegram_id)
	
	if not worker:
		await callback_query.answer("❌ Ishchi topilmadi!", show_alert=True)
		return
	
	success = await delete_user_from_db(telegram_id)
	
	if success:
		await callback_query.answer("✅ Ishchi o'chirildi!", show_alert=True)
		logging.info(f"Worker {telegram_id} deleted by admin")
		await show_workers(callback_query, state)
	else:
		await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

@admin_router.callback_query(F.data == "admin_groups")
async def show_groups(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	groups = await get_all_telegram_groups()
	text = format_groups_list(groups)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_groups_list_keyboard(groups))
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_groups_list_keyboard(groups))
	await callback_query.answer()

@admin_router.callback_query(F.data == "group_add")
async def add_group_start(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_group_link)
	text = (
		"➕ GURUH QO'SHISH\n\n"
		"Guruh yoki mavzuning havolasini kiriting:\n\n"
		"📝 Masalan:\n"
		"• https://t.me/c/1234567890/123 (mavzu bilan)\n"
		"• https://t.me/c/1234567890 (mavzusiz)\n"
		"• -1001234567890 (raqamli ID)\n\n"
		"💡 Guruh ID'sini olish uchun botni guruhga qo'shing va /admin buyrug'ini yuboring"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard())
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard())
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_group_link)
async def process_group_link(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	link = message.text.strip()
	group_id = None
	topic_id = None
	
	match_channel_topic = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
	match_channel_no_topic = re.match(r"https://t\.me/c/(\d+)", link)
	match_numeric_id = re.match(r"^-?\d+$", link)
	
	if match_channel_topic:
		group_id = int("-100" + match_channel_topic.group(1))
		topic_id = int(match_channel_topic.group(2))
	elif match_channel_no_topic:
		group_id = int("-100" + match_channel_no_topic.group(1))
		topic_id = None
	elif match_numeric_id:
		group_id = int(link)
		topic_id = None
	else:
		await message.answer(
			"❌ XATO\n\n"
			"Noto'g'ri havola kiritildi\n\n"
			"To'g'ri formatlar:\n"
			"• https://t.me/c/GROUP_ID/TOPIC_ID\n"
			"• https://t.me/c/GROUP_ID\n"
			"• -1001234567890",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	if group_id:
		await state.update_data(temp_group_id=group_id, temp_topic_id=topic_id)
		await state.set_state(AdminStates.waiting_for_group_name)
		await message.answer(
			f"✅ TASDIQLASH\n\n"
			f"Guruh ID: {group_id}\n"
			f"Mavzu ID: {topic_id if topic_id else 'Yo\'q'}\n\n"
			f"Endi bu guruh uchun nom kiriting:\n"
			f"(Masalan: 'Asosiy Sotuv Hisoboti')",
			reply_markup=get_admin_cancel_inline_keyboard()
		)

@admin_router.message(AdminStates.waiting_for_group_name)
async def process_group_name(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	group_name = message.text.strip()
	if not group_name or len(group_name) < 3:
		await message.answer(
			"⚠️ XATO\n\n"
			"Guruh nomini to'g'ri kiriting (kamida 3 belgi)",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	await state.update_data(temp_group_name=group_name)
	
	sheets = await get_all_google_sheets()
	if not sheets:
		await message.answer(
			"⚠️ XATO\n\n"
			"Hozircha Google Sheets mavjud emas.\n"
			"Avval Google Sheet qo'shing.",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	await state.set_state(AdminStates.waiting_for_group_sheet_selection)
	await message.answer(
		f"📊 GOOGLE SHEET TANLASH\n\n"
		f"'{group_name}' guruhi uchun Google Sheet tanlang:\n\n"
		f"Bu guruhga yuborilgan hisobotlar tanlangan Google Sheets'ga saqlanadi.",
		reply_markup=get_google_sheets_selection_keyboard(sheets)
	)

@admin_router.callback_query(AdminStates.waiting_for_group_sheet_selection, F.data.startswith("select_sheet_"))
async def process_group_sheet_selection(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	data = await state.get_data()
	group_id = data.get("temp_group_id")
	topic_id = data.get("temp_topic_id")
	group_name = data.get("temp_group_name")
	
	sheet_info = await get_google_sheet_by_id(sheet_id)
	if not sheet_info:
		await callback_query.answer("❌ Google Sheet topilmadi!", show_alert=True)
		return
	
	sheet_name = sheet_info[1]
	
	success = await add_telegram_group(group_id, group_name, topic_id, sheet_id)
	
	if success:
		text = (
			f"✅ MUVAFFAQIYAT\n\n"
			f"Guruh '{group_name}' muvaffaqiyatli qo'shildi\n\n"
			f"📊 Guruh ID: {group_id}\n"
			f"📝 Mavzu ID: {topic_id if topic_id else 'Yo\'q'}\n"
			f"📈 Google Sheet: {sheet_name}\n\n"
			f"Bu guruhga yuborilgan hisobotlar '{sheet_name}' Google Sheets'ga saqlanadi."
		)
		logging.info(f"Group {group_name} ({group_id}) added with Google Sheet {sheet_name} by admin")
	else:
		text = (
			"❌ XATO\n\n"
			"Guruhni qo'shishda xatolik yuz berdi yoki bu guruh allaqachon mavjud"
		)
	
	await state.clear()
	await callback_query.message.edit_text(text)
	
	groups = await get_all_telegram_groups()
	await callback_query.message.answer(
		format_groups_list(groups),
		reply_markup=get_groups_list_keyboard(groups)
	)
	await callback_query.answer()

@admin_router.callback_query(F.data == "group_delete")
async def delete_group_start(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	groups = await get_all_telegram_groups()
	if not groups:
		await callback_query.answer("❌ O'chiriladigan guruhlar yo'q!", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_group_id_to_delete)
	text = (
		"🗑️ GURUH O'CHIRISH\n\n"
		"O'chirmoqchi bo'lgan guruh ID'sini kiriting:\n\n"
	)
	
	for i, group in enumerate(groups, 1):
		db_id, group_id, group_name, topic_id, google_sheet_id, sheet_name = group
		text += f"{i}. {group_name} - ID: {group_id}\n"
	
	text += "\n💡 Faqat guruh ID'sini kiriting (masalan: -1001234567890)"
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard())
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard())
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_group_id_to_delete)
async def process_group_delete(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	try:
		group_id = int(message.text.strip())
	except ValueError:
		await message.answer(
			"❌ XATO\n\n"
			"Faqat raqamli guruh ID'sini kiriting\n"
			"Masalan: -1001234567890",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	group_info = await get_telegram_group_by_id(group_id)
	if not group_info:
		await message.answer(
			"❌ XATO\n\n"
			"Bunday ID'li guruh topilmadi",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	group_name = group_info[2]
	success = await delete_telegram_group(group_id)
	
	if success:
		text = f"✅ MUVAFFAQIYAT\n\nGuruh '{group_name}' o'chirildi"
		logging.info(f"Group {group_name} ({group_id}) deleted by admin")
	else:
		text = "❌ XATO\n\nGuruhni o'chirishda xatolik yuz berdi"
	
	await state.clear()
	await message.answer(text)
	
	groups = await get_all_telegram_groups()
	await message.answer(
		format_groups_list(groups),
		reply_markup=get_groups_list_keyboard(groups)
	)

@admin_router.callback_query(F.data == "admin_sheets")
async def show_google_sheets_menu(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheets = await get_all_google_sheets()
	
	text = (
		"📈 GOOGLE SHEETS BOSHQARUVI\n\n"
		f"📊 Jami faol sheetlar: {len(sheets)} ta\n\n"
		"Kerakli amalni tanlang:"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_google_sheets_keyboard())
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_google_sheets_keyboard())
	await callback_query.answer()

@admin_router.callback_query(F.data == "sheets_list")
async def show_sheets_list(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheets = await get_all_google_sheets()
	text = format_sheets_list(sheets)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_sheets_list_keyboard(sheets))
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_sheets_list_keyboard(sheets))
	await callback_query.answer()

@admin_router.callback_query(F.data == "sheets_add")
async def add_sheet_start(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_sheet_name)
	text = (
		"➕ GOOGLE SHEET QO'SHISH\n\n"
		"Avval Google Sheet uchun nom kiriting:\n\n"
		"📝 Masalan:\n"
		"• Asosiy Hisobotlar\n"
		"• Toshkent Filiali\n"
		"• Samarqand Bo'limi\n\n"
		"💡 Bu nom guruhlar ro'yxatida ko'rinadi"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard())
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard())
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_sheet_name)
async def process_sheet_name(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	sheet_name = message.text.strip()
	if not sheet_name or len(sheet_name) < 3:
		await message.answer(
			"⚠️ XATO\n\n"
			"Sheet nomini to'g'ri kiriting (kamida 3 belgi)",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	await state.update_data(temp_sheet_name=sheet_name)
	await state.set_state(AdminStates.waiting_for_google_sheet_url)
	
	await message.answer(
		f"🔗 GOOGLE SHEET HAVOLASI\n\n"
		f"'{sheet_name}' uchun Google Sheet havolasini kiriting:\n\n"
		f"📝 Masalan:\n"
		f"https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit#gid=SHEET_ID\n\n"
		f"💡 Sheet'ni service account email bilan ulashing:\n"
		f"web-malumotlari@aqueous-argon-454316-h5.iam.gserviceaccount.com",
		reply_markup=get_admin_cancel_inline_keyboard()
	)

@admin_router.message(AdminStates.waiting_for_google_sheet_url)
async def process_google_sheet_url(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	url = message.text.strip()
	match = re.search(r"https://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
	
	if match:
		spreadsheet_id = match.group(1)
		await state.update_data(temp_spreadsheet_id=spreadsheet_id)
		await state.set_state(AdminStates.waiting_for_google_sheet_worksheet_name)
		
		await message.answer(
			f"✅ TASDIQLASH\n\n"
			f"Google Sheet ID qabul qilindi:\n"
			f"{spreadsheet_id}\n\n"
			f"Endi ishchi varaq nomini kiriting:\n"
			f"(masalan: 'Sheet1' yoki 'Hisobotlar')",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
	else:
		await message.answer(
			"❌ XATO\n\n"
			"Noto'g'ri Google Sheet havolasi\n\n"
			"To'g'ri format:\n"
			"https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit",
			reply_markup=get_admin_cancel_inline_keyboard()
		)

@admin_router.message(AdminStates.waiting_for_google_sheet_worksheet_name)
async def process_google_sheet_worksheet_name(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	worksheet_name = message.text.strip()
	if not worksheet_name:
		await message.answer(
			"⚠️ XATO\n\n"
			"Ishchi varaq nomini kiriting\n"
			"Qaytadan kiriting",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	data = await state.get_data()
	sheet_name = data.get("temp_sheet_name")
	spreadsheet_id = data.get("temp_spreadsheet_id")
	
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if worksheet:
			success = await add_google_sheet(sheet_name, spreadsheet_id, worksheet_name)
			if success:
				text = (
					f"✅ MUVAFFAQIYAT\n\n"
					f"Google Sheet '{sheet_name}' muvaffaqiyatli qo'shildi\n\n"
					f"📊 Nom: {sheet_name}\n"
					f"📄 ID: {spreadsheet_id}\n"
					f"📋 Varaq: {worksheet_name}\n\n"
					f"Endi bu Sheet'ni guruhlarga tayinlashingiz mumkin."
				)
				logging.info(f"Google Sheet added: {sheet_name} ({spreadsheet_id}/{worksheet_name})")
			else:
				text = "❌ XATO\n\nMa'lumotlar bazasiga saqlashda xatolik yoki bu Sheet allaqachon mavjud"
		else:
			text = (
				"❌ ULANISH XATOSI\n\n"
				"Google Sheet'ga ulanib bo'lmadi.\n\n"
				"Tekshiring:\n"
				"• Sheet ID to'g'ri ekanligini\n"
				"• Service account'ga ruxsat berilganligini\n"
				"• Varaq nomi to'g'ri ekanligini"
			)
	except Exception as e:
		text = f"❌ XATO\n\nUlanishda xatolik: {str(e)}"
		logging.error(f"Google Sheets connection error: {e}")
	
	await state.clear()
	await message.answer(text)
	
	await show_sheets_list(message, state)

@admin_router.callback_query(F.data.startswith("sheet_select_"))
async def show_sheet_details(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet_info
	
	text = (
		f"📊 GOOGLE SHEET MA'LUMOTLARI\n\n"
		f"📝 Nom: {sheet_name}\n"
		f"📄 Spreadsheet ID: {spreadsheet_id[:20]}...\n"
		f"📋 Worksheet: {worksheet_name}\n"
		f"🔘 Holat: {'Faol' if is_active else 'Nofaol'}\n\n"
		f"💡 Kerakli amalni tanlang:"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_sheet_management_keyboard(sheet_id))
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_sheet_management_keyboard(sheet_id))
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("sheet_test_"))
async def test_sheet(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet_info
	
	success, message_text = test_google_sheets_connection(spreadsheet_id, worksheet_name)
	
	if success:
		await callback_query.answer("✅ Test muvaffaqiyatli bajarildi! Test ma'lumotlari qo'shildi.", show_alert=True)
		logging.info(f"Google Sheets test successful: {sheet_name} ({spreadsheet_id}/{worksheet_name})")
	else:
		await callback_query.answer(f"❌ Test muvaffaqiyatsiz: {message_text}", show_alert=True)
		logging.error(f"Google Sheets test failed: {message_text}")

@admin_router.callback_query(F.data.startswith("sheet_stats_"))
async def show_sheet_stats(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet_info
	
	try:
		stats = get_reports_statistics(spreadsheet_id, worksheet_name)
		if stats:
			text = (
				f"📊 {sheet_name} STATISTIKASI\n\n"
				f"📈 Jami hisobotlar: {stats.get('total_reports', 0)} ta\n"
				f"👥 Sotuvchilar: {len(stats.get('sellers_stats', {}))} ta\n"
				f"🛍️ Mahsulotlar: {len(stats.get('product_stats', {}))} ta\n"
				f"📍 Hududlar: {len(stats.get('location_stats', {}))} ta\n"
				f"📅 Yan. sanasi: {stats.get('last_updated', 'Noma\'lum')}\n\n"
			)
			
			top_sellers = stats.get('top_sellers', {})
			if top_sellers:
				text += "🏆 TOP SOTUVCHILAR:\n"
				for i, (seller, count) in enumerate(list(top_sellers.items())[:5], 1):
					text += f"{i}. {seller}: {count} ta\n"
		else:
			text = f"📊 {sheet_name} STATISTIKASI\n\nMa'lumotlar topilmadi"
	except Exception as e:
		text = f"📊 {sheet_name} STATISTIKASI\n\nXatolik: {str(e)}"
		logging.error(f"Error getting sheet stats: {e}")
	
	await callback_query.answer(text, show_alert=True)

@admin_router.callback_query(F.data.startswith("sheet_delete_"))
async def delete_sheet(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_name = sheet_info[1]
	success = await delete_google_sheet(sheet_id)
	
	if success:
		await callback_query.answer(f"✅ '{sheet_name}' Google Sheet o'chirildi!", show_alert=True)
		logging.info(f"Google Sheet deleted: {sheet_name} by admin")
		await show_sheets_list(callback_query, state)
	else:
		await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

@admin_router.callback_query(F.data == "admin_change_password")
async def show_password_menu(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	current_password = await get_current_password()
	
	text = (
		"🔐 PAROL BOSHQARUVI\n\n"
		f"📋 Joriy parol: {current_password}\n\n"
		"⚠️ DIQQAT:\n"
		"• Parol o'zgarishi faqat yangi foydalanuvchilarga ta'sir qiladi\n"
		"• Mavjud foydalanuvchilar eski parol bilan kirishda davom etadilar\n"
		"• Yangi foydalanuvchilar yangi parol bilan ro'yxatdan o'tadilar\n\n"
		"Kerakli amalni tanlang:"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_password_change_keyboard())
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_password_change_keyboard())
	await callback_query.answer()

@admin_router.callback_query(F.data == "change_password_start")
async def start_password_change(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_new_password)
	text = (
		"🔐 YANGI PAROL KIRITING\n\n"
		"Yangi parolni kiriting:\n\n"
		"📝 Tavsiyalar:\n"
		"• Kamida 4 belgi\n"
		"• Oson eslab qoladigan\n"
		"• Xavfsiz bo'lishi kerak\n\n"
		"💡 Masalan: 2025, admin123, secure2024"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard())
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard())
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_new_password)
async def process_new_password(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	new_password = message.text.strip()
	if not new_password or len(new_password) < 4:
		await message.answer(
			"⚠️ XATO\n\n"
			"Parol kamida 4 belgi bo'lishi kerak.\n"
			"Qaytadan kiriting:",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	current_password = await get_current_password()
	if new_password == current_password:
		await message.answer(
			"⚠️ XATO\n\n"
			"Yangi parol joriy parol bilan bir xil.\n"
			"Boshqa parol kiriting:",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	await state.update_data(new_password=new_password)
	await state.set_state(AdminStates.waiting_for_password_confirmation)
	
	await message.answer(
		f"🔐 PAROLNI TASDIQLASH\n\n"
		f"Yangi parol: {new_password}\n\n"
		f"Parolni tasdiqlash uchun qaytadan kiriting:",
		reply_markup=get_admin_cancel_inline_keyboard()
	)

@admin_router.message(AdminStates.waiting_for_password_confirmation)
async def process_password_confirmation(message: Message, state: FSMContext):
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	confirmation = message.text.strip()
	data = await state.get_data()
	new_password = data.get("new_password")
	
	if confirmation != new_password:
		await message.answer(
			"❌ XATO\n\n"
			"Parollar mos kelmadi.\n"
			"Qaytadan tasdiqlash parolini kiriting:",
			reply_markup=get_admin_cancel_inline_keyboard()
		)
		return
	
	success = await update_password(new_password)
	
	if success:
		text = (
			f"✅ MUVAFFAQIYAT\n\n"
			f"Parol muvaffaqiyatli o'zgartirildi!\n\n"
			f"📋 Yangi parol: {new_password}\n\n"
			f"⚠️ ESLATMA:\n"
			f"• Yangi foydalanuvchilar '{new_password}' parol bilan ro'yxatdan o'tadilar\n"
			f"• Mavjud foydalanuvchilar eski parol bilan kirishda davom etadilar\n"
			f"• Bu o'zgarish darhol kuchga kiradi"
		)
		logging.info(f"Admin password changed to: {new_password}")
	else:
		text = "❌ XATO\n\nParolni o'zgartirishda xatolik yuz berdi"
	
	await state.clear()
	await message.answer(text)
	
	await show_password_menu(message, state)

@admin_router.callback_query(F.data == "view_current_password")
async def view_current_password(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	current_password = await get_current_password()
	await callback_query.answer(f"🔐 Joriy parol: {current_password}", show_alert=True)

@admin_router.callback_query(F.data == "admin_reports")
async def show_reports_menu(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	try:
		await callback_query.message.edit_text(
			"📊 HISOBOTLAR\n\nKerakli bo'limni tanlang:",
			reply_markup=get_reports_stats_keyboard()
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"📊 HISOBOTLAR\n\nKerakli bo'limni tanlang:",
			reply_markup=get_reports_stats_keyboard()
		)
	await callback_query.answer()

@admin_router.callback_query(F.data == "reports_general")
async def show_general_reports(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	stats = await get_database_stats()
	
	today = date.today()
	week_ago = today - timedelta(days=7)
	week_reports = await get_reports_count_by_date(week_ago.isoformat(), today.isoformat())
	
	month_ago = today - timedelta(days=30)
	month_reports = await get_reports_count_by_date(month_ago.isoformat(), today.isoformat())
	
	text = (
		"📊 UMUMIY STATISTIKA\n\n"
		f"👥 Jami ishchilar: {stats.get('total_users', 0)} ta\n"
		f"📝 Jami hisobotlar: {stats.get('total_reports', 0)} ta\n"
		f"✅ Tasdiqlangan: {stats.get('confirmed_reports', 0)} ta\n"
		f"⏳ Kutilayotgan: {stats.get('pending_reports', 0)} ta\n"
		f"📅 Bugungi hisobotlar: {stats.get('today_reports', 0)} ta\n"
		f"📈 Haftalik hisobotlar: {week_reports} ta\n"
		f"📊 Oylik hisobotlar: {month_reports} ta\n"
		f"🎯 Tasdiqlash foizi: {stats.get('confirmation_rate', 0)}%"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_reports_stats_keyboard())
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_reports_stats_keyboard())
	await callback_query.answer()

@admin_router.callback_query(F.data == "admin_settings")
async def show_settings_menu(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	try:
		await callback_query.message.edit_text(
			"⚙️ SOZLAMALAR\n\nKerakli bo'limni tanlang:",
			reply_markup=get_settings_keyboard()
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"⚙️ SOZLAMALAR\n\nKerakli bo'limni tanlang:",
			reply_markup=get_settings_keyboard()
		)
	await callback_query.answer()

@admin_router.callback_query(F.data == "admin_menu")
async def back_to_admin_menu(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.clear()
	try:
		await callback_query.message.edit_text(
			"👨‍💻 ADMIN PANEL\n\nKerakli bo'limni tanlang:",
			reply_markup=get_admin_menu_inline_keyboard()
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"👨‍💻 ADMIN PANEL\n\nKerakli bo'limni tanlang:",
			reply_markup=get_admin_menu_inline_keyboard()
		)
	await callback_query.answer()

@admin_router.callback_query(F.data == "admin_exit")
async def exit_admin_panel(callback_query: CallbackQuery, state: FSMContext):
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.clear()
	try:
		await callback_query.message.edit_text(
			"🏠 ASOSIY MENYU\n\nAdmin paneldan chiqildi",
			reply_markup=None
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"🏠 ASOSIY MENYU\n\nAdmin paneldan chiqildi",
			reply_markup=None
		)
	
	await callback_query.message.answer(
		"Asosiy menyuga qaytdingiz.",
		reply_markup=get_main_menu_reply_keyboard()
	)
	await callback_query.answer()

@admin_router.callback_query(F.data == "cancel_admin_action")
async def cancel_admin_action_handler(callback_query: CallbackQuery, state: FSMContext):
	await state.clear()
	try:
		await callback_query.message.edit_text(
			"🚫 BEKOR QILINDI\n\nAdmin jarayoni bekor qilindi",
			reply_markup=None
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"🚫 BEKOR QILINDI\n\nAdmin jarayoni bekor qilindi",
			reply_markup=None
		)
	
	await callback_query.message.answer(
		"Admin panelga qaytish uchun /admin buyrug'ini yuboring.",
		reply_markup=get_main_menu_reply_keyboard()
	)
	await callback_query.answer()

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logging.info("Admin router initialized successfully")
