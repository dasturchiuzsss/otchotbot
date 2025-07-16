import logging

from aiogram import Router, F, Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_ID, HELPER_ID
from database import add_sales_report, get_all_telegram_groups, update_report_status_in_db
from keyboards import (
	get_cancel_report_inline_keyboard,
	get_dynamic_group_selection_inline_keyboard,
	get_main_menu_reply_keyboard,
	get_report_confirmation_keyboard,
	get_report_confirmed_keyboard,
	get_yes_no_additional_phone_inline_keyboard,
)

otchot_router = Router()

class ReportState(StatesGroup):
	waiting_for_client_name = State()
	waiting_for_phone_number = State()
	waiting_for_additional_phone_prompt = State()
	waiting_for_additional_phone_number = State()
	waiting_for_contract_id = State()
	waiting_for_product_type = State()
	waiting_for_client_location_text = State()
	waiting_for_product_image = State()
	waiting_for_group_selection = State()

REPORT_CAPTION_TEMPLATE = """📝 Yangi Hisobot:

👤 Mijoz: {client_name}

📱 Telefon : {phone_number}

📱 Qo'shimcha : {additional_phone_number}

📄 Bitim ID: {contract_id}

🛍️ Mahsulot : {product_type}

📍 Manzil: {client_location}

👨‍💼 Sotuvchi : {sender_full_name}

{status_line}"""

async def delete_previous_messages(bot: Bot, chat_id: int, state: FSMContext):
	data = await state.get_data()
	bot_prompt_id = data.get("last_bot_prompt_id")
	user_reply_id = data.get("last_user_reply_id")
	
	try:
		if bot_prompt_id:
			await bot.delete_message(chat_id, bot_prompt_id)
	except TelegramBadRequest:
		logging.warning(f"Could not delete bot prompt message {bot_prompt_id} in chat {chat_id}")
	except Exception as e:
		logging.error(f"Error deleting bot_prompt_id {bot_prompt_id}: {e}")
	
	try:
		if user_reply_id:
			await bot.delete_message(chat_id, user_reply_id)
	except TelegramBadRequest:
		logging.warning(f"Could not delete user reply message {user_reply_id} in chat {chat_id}")
	except Exception as e:
		logging.error(f"Error deleting user_reply_id {user_reply_id}: {e}")
	
	await state.update_data(last_bot_prompt_id=None, last_user_reply_id=None)

@otchot_router.message(F.text == "📝 Hisobot topshirish")
async def start_report_submission(message: Message, state: FSMContext, bot: Bot):
	await state.clear()
	sent_message = await message.answer(
		"👤 Mijozning to'liq ismini kiriting:",
		reply_markup=get_cancel_report_inline_keyboard()
	)
	await state.set_state(ReportState.waiting_for_client_name)
	await state.update_data(last_bot_prompt_id=sent_message.message_id)

@otchot_router.callback_query(F.data == "cancel_report_submission")
async def cancel_report_submission_handler(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	current_state = await state.get_state()
	if current_state is None:
		try:
			await callback_query.message.edit_reply_markup(reply_markup=None)
		except Exception:
			pass
		await callback_query.answer("Jarayon allaqachon bekor qilingan yoki yakunlangan.")
		return
	
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

async def process_step(message: Message, state: FSMContext, bot: Bot, next_state: State, prompt_text: str,
                       keyboard_markup=None):
	await state.update_data(last_user_reply_id=message.message_id)
	await delete_previous_messages(bot, message.chat.id, state)
	
	sent_message = await message.answer(prompt_text,
	                                    reply_markup=keyboard_markup if keyboard_markup else get_cancel_report_inline_keyboard())
	await state.set_state(next_state)
	await state.update_data(last_bot_prompt_id=sent_message.message_id)

@otchot_router.message(ReportState.waiting_for_client_name)
async def process_client_name(message: Message, state: FSMContext, bot: Bot):
	client_name = message.text
	if not client_name or len(client_name) < 3:
		await state.update_data(last_user_reply_id=message.message_id)
		await delete_previous_messages(bot, message.chat.id, state)
		error_prompt = await message.answer(
			"⚠️ Iltimos, mijozning ismini to'g'ri kiriting (kamida 3 belgi). Qaytadan kiriting:",
			reply_markup=get_cancel_report_inline_keyboard()
		)
		await state.update_data(last_bot_prompt_id=error_prompt.message_id)
		return
	await state.update_data(client_name=client_name)
	await process_step(message, state, bot, ReportState.waiting_for_phone_number,
	                   "📱 Mijozning telefon raqamini kiriting:")

@otchot_router.message(ReportState.waiting_for_phone_number)
async def process_phone_number(message: Message, state: FSMContext, bot: Bot):
	phone_number = message.text
	if not phone_number or not any(char.isdigit() for char in phone_number):
		await state.update_data(last_user_reply_id=message.message_id)
		await delete_previous_messages(bot, message.chat.id, state)
		error_prompt = await message.answer(
			"⚠️ Telefon raqamini kiriting. Qaytadan kiriting:",
			reply_markup=get_cancel_report_inline_keyboard()
		)
		await state.update_data(last_bot_prompt_id=error_prompt.message_id)
		return
	await state.update_data(phone_number=phone_number)
	await state.update_data(last_user_reply_id=message.message_id)
	await delete_previous_messages(bot, message.chat.id, state)
	sent_message = await message.answer(
		"❓ Qo'shimcha telefon raqami bormi?",
		reply_markup=get_yes_no_additional_phone_inline_keyboard()
	)
	await state.set_state(ReportState.waiting_for_additional_phone_prompt)
	await state.update_data(last_bot_prompt_id=sent_message.message_id)

@otchot_router.callback_query(ReportState.waiting_for_additional_phone_prompt,
                              F.data.in_({"add_phone_yes", "add_phone_no"}))
async def process_additional_phone_prompt(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	data = await state.get_data()
	bot_inline_prompt_id = data.get("last_bot_prompt_id")
	if bot_inline_prompt_id:
		try:
			await bot.delete_message(callback_query.message.chat.id, bot_inline_prompt_id)
		except TelegramBadRequest:
			logging.warning(f"Could not delete bot inline prompt {bot_inline_prompt_id}")
		except Exception as e:
			logging.error(f"Error deleting bot_inline_prompt_id {bot_inline_prompt_id}: {e}")
	
	if callback_query.data == "add_phone_yes":
		sent_message = await callback_query.message.answer(
			"📱 Qo'shimcha telefon raqamini kiriting:",
			reply_markup=get_cancel_report_inline_keyboard()
		)
		await state.set_state(ReportState.waiting_for_additional_phone_number)
		await state.update_data(last_bot_prompt_id=sent_message.message_id)
	else:
		await state.update_data(additional_phone_number="Mavjud emas")
		sent_message = await callback_query.message.answer(
			"📄 Shartnoma ID raqamini kiriting:",
			reply_markup=get_cancel_report_inline_keyboard()
		)
		await state.set_state(ReportState.waiting_for_contract_id)
		await state.update_data(last_bot_prompt_id=sent_message.message_id)
	await callback_query.answer()

@otchot_router.message(ReportState.waiting_for_additional_phone_number)
async def process_additional_phone_number(message: Message, state: FSMContext, bot: Bot):
	additional_phone_number = message.text
	if not additional_phone_number or not any(char.isdigit() for char in additional_phone_number):
		await state.update_data(last_user_reply_id=message.message_id)
		await delete_previous_messages(bot, message.chat.id, state)
		error_prompt = await message.answer(
			"⚠️ Qo'shimcha telefon raqamini kiriting. Qaytadan kiriting:",
			reply_markup=get_cancel_report_inline_keyboard()
		)
		await state.update_data(last_bot_prompt_id=error_prompt.message_id)
		return
	await state.update_data(additional_phone_number=additional_phone_number)
	await process_step(message, state, bot, ReportState.waiting_for_contract_id, "📄 Shartnoma ID raqamini kiriting:")

@otchot_router.message(ReportState.waiting_for_contract_id)
async def process_contract_id(message: Message, state: FSMContext, bot: Bot):
	contract_id = message.text
	if not contract_id:
		await state.update_data(last_user_reply_id=message.message_id)
		await delete_previous_messages(bot, message.chat.id, state)
		error_prompt = await message.answer(
			"⚠️ Shartnoma ID raqamini kiriting. Qaytadan kiriting:",
			reply_markup=get_cancel_report_inline_keyboard()
		)
		await state.update_data(last_bot_prompt_id=error_prompt.message_id)
		return
	await state.update_data(contract_id=contract_id)
	await process_step(message, state, bot, ReportState.waiting_for_product_type, "🛍️ Mahsulot turini kiriting:")

@otchot_router.message(ReportState.waiting_for_product_type)
async def process_product_type(message: Message, state: FSMContext, bot: Bot):
	product_type = message.text
	if not product_type or len(product_type) < 2:
		await state.update_data(last_user_reply_id=message.message_id)
		await delete_previous_messages(bot, message.chat.id, state)
		error_prompt = await message.answer(
			"⚠️ Mahsulot turini to'g'ri kiriting (kamida 2 belgi). Qaytadan kiriting:",
			reply_markup=get_cancel_report_inline_keyboard()
		)
		await state.update_data(last_bot_prompt_id=error_prompt.message_id)
		return
	await state.update_data(product_type=product_type)
	await process_step(message, state, bot, ReportState.waiting_for_client_location_text,
	                   "📍 Mijozning joylashuvini (manzilini) matn ko'rinishida kiriting:")

@otchot_router.message(ReportState.waiting_for_client_location_text, F.text)
async def process_client_location_text(message: Message, state: FSMContext, bot: Bot):
	client_location_text = message.text
	if not client_location_text or len(client_location_text) < 5:
		await state.update_data(last_user_reply_id=message.message_id)
		await delete_previous_messages(bot, message.chat.id, state)
		error_prompt = await message.answer(
			"⚠️ Mijoz joylashuvini to'liqroq kiriting (kamida 5 belgi). Qaytadan kiriting:",
			reply_markup=get_cancel_report_inline_keyboard()
		)
		await state.update_data(last_bot_prompt_id=error_prompt.message_id)
		return
	await state.update_data(client_location=client_location_text)
	await process_step(message, state, bot, ReportState.waiting_for_product_image,
	                   "🖼️ Sotuv uchun mahsulot rasmini yuboring:")

@otchot_router.message(ReportState.waiting_for_product_image, F.photo)
async def process_product_image_and_ask_group(message: Message, state: FSMContext, bot: Bot):
	await state.update_data(last_user_reply_id=message.message_id)
	await delete_previous_messages(bot, message.chat.id, state)
	
	photo_file_id = message.photo[-1].file_id
	await state.update_data(product_image_id=photo_file_id)
	
	groups = await get_all_telegram_groups()
	if not groups:
		# Guruhlar sozlanmagan bo'lsa, foydalanuvchiga xabar beramiz
		await message.answer(
			"⚠️ Guruhlar hali sozlanmagan. Hisobotni yuborish uchun admin panelidan guruh qo'shing."
		)
		await state.clear()
		await message.answer(
			"🎉 Boshqa amal bajarishingiz mumkin.",
			reply_markup=get_main_menu_reply_keyboard()
		)
		return
	
	sent_message = await message.answer(
		"📤 Hisobotni qaysi guruhga yubormoqchisiz?",
		reply_markup=get_dynamic_group_selection_inline_keyboard(groups)
	)
	await state.set_state(ReportState.waiting_for_group_selection)
	await state.update_data(last_bot_prompt_id=sent_message.message_id)

@otchot_router.callback_query(ReportState.waiting_for_group_selection, F.data.startswith("select_group_"))
async def send_report_to_selected_group(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	await delete_previous_messages(bot, callback_query.message.chat.id, state)
	
	# Callback datadan guruh ID va mavzu ID ni ajratib olamiz
	parts = callback_query.data.split("_")
	
	selected_group_id = None
	selected_topic_id = None
	
	if len(parts) == 4:  # select_group_GROUP_ID_TOPIC_ID
		selected_group_id = int(parts[2])
		selected_topic_id = int(parts[3]) if parts[3] != '0' else None
	else:
		logging.error(f"Unexpected callback_query.data format: {callback_query.data}")
		await callback_query.message.answer(
			"❌ Xatolik: Guruh tanlashda muammo yuz berdi. Iltimos, qayta urinib ko'ring.")
		await state.clear()
		await callback_query.message.answer(
			"🎉 Boshqa amal bajarishingiz mumkin.",
			reply_markup=get_main_menu_reply_keyboard()
		)
		await callback_query.answer()
		return
	
	user_data = await state.get_data()
	
	status_line = "Holati: ⏳ Kutilmoqda"
	report_caption = REPORT_CAPTION_TEMPLATE.format(
		client_name=user_data.get('client_name', 'Noma\'lum'),
		phone_number=user_data.get('phone_number', 'Noma\'lum'),
		additional_phone_number=user_data.get('additional_phone_number', 'Mavjud emas'),
		contract_id=user_data.get('contract_id', 'Noma\'lum'),
		product_type=user_data.get('product_type', 'Noma\'lum'),
		client_location=user_data.get('client_location', 'Noma\'lum'),
		sender_full_name=callback_query.from_user.full_name,
		sender_username=callback_query.from_user.username if callback_query.from_user.username else 'N/A',
		status_line=status_line
	)
	
	group_message_sent = None
	try:
		group_message_sent = await bot.send_photo(
			chat_id=selected_group_id,
			photo=user_data.get('product_image_id'),
			caption=report_caption,
			parse_mode=ParseMode.HTML,
			message_thread_id=selected_topic_id,  # Mavzu ID'sini qo'shamiz
			reply_markup=get_report_confirmation_keyboard()
		)
		await callback_query.message.answer("✅ Hisobotingiz muvaffaqiyatli tanlangan guruhga yuborildi!")
	except Exception as e:
		logging.error(f"Error sending report to selected group {selected_group_id} (topic {selected_topic_id}): {e}")
		await callback_query.message.answer(f"❌ Xatolik yuz berdi: Hisobotni guruhga yuborishda muammo: {e}")
	
	group_msg_id_to_save = group_message_sent.message_id if group_message_sent else None
	await add_sales_report(callback_query.from_user.id, user_data, group_msg_id_to_save)
	
	await state.clear()
	await callback_query.message.answer(
		"🎉 Boshqa amal bajarishingiz mumkin.",
		reply_markup=get_main_menu_reply_keyboard()
	)
	await callback_query.answer()

@otchot_router.message(ReportState.waiting_for_product_image)
async def incorrect_product_image(message: Message, state: FSMContext, bot: Bot):
	await state.update_data(last_user_reply_id=message.message_id)
	await delete_previous_messages(bot, message.chat.id, state)
	error_prompt = await message.answer(
		"⚠️ Iltimos, faqat rasm yuboring. Qaytadan yuboring:",
		reply_markup=get_cancel_report_inline_keyboard()
	)
	await state.update_data(last_bot_prompt_id=error_prompt.message_id)

@otchot_router.callback_query(F.data == "confirm_report_action")
async def confirm_report_handler(callback_query: CallbackQuery, bot: Bot):
	user_id = callback_query.from_user.id
	msg = callback_query.message
	
	# Faqat HELPER_ID ga ruxsat beriladi
	if user_id != HELPER_ID:
		await callback_query.answer("🚫 Sizda bu amalni bajarish uchun ruxsat yo'q.", show_alert=True)
		return
	
	if not msg or not msg.caption:
		await callback_query.answer("❌ Xatolik: Asl xabarni topib bo'lmadi.", show_alert=True)
		return
	
	if "Holati: ✅ Tasdiqlandi" in msg.caption:
		await callback_query.answer("ℹ️ Bu hisobot allaqachon tasdiqlangan.", show_alert=True)
		return
	
	# Barcha qatorlarni ajratib olamiz va bo'sh qatorlarni olib tashlaymiz
	filtered_lines = [line.strip() for line in msg.caption.splitlines() if line.strip()]
	
	# Oxirgi qator "Holati:" bilan boshlanishini tekshiramiz va yangilaymiz
	if filtered_lines and filtered_lines[-1].startswith("Holati:"):
		filtered_lines[-1] = "Holati: ✅ Tasdiqlandi"
	else:
		# Agar status qatori topilmasa, uni oxiriga qo'shamiz
		filtered_lines.append("Holati: ✅ Tasdiqlandi")
	
	# Barcha qatorlarni bitta yangi qator bilan birlashtiramiz
	updated_caption = "\n".join(filtered_lines)
	
	try:
		await bot.edit_message_caption(
			chat_id=msg.chat.id,
			message_id=msg.message_id,
			caption=updated_caption,
			reply_markup=get_report_confirmed_keyboard()
		)
		# Tasdiqlagan foydalanuvchining ID'sini saqlaymiz
		await update_report_status_in_db(msg.message_id, "confirmed", user_id)
		await callback_query.answer("✅ Hisobot muvaffaqiyatli tasdiqlandi!", show_alert=True)
	except Exception as e:
		logging.error(f"Error editing message caption for confirmation: {e}")
		await callback_query.answer("❌ Xatolik: Hisobotni tasdiqlashda muammo yuz berdi.", show_alert=True)

@otchot_router.callback_query(F.data == "status_confirmed_noop")
async def confirmed_noop_handler(callback_query: CallbackQuery):
	await callback_query.answer("ℹ️ Bu hisobot allaqachon tasdiqlangan.")
