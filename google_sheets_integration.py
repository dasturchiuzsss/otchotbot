import gspread
from google.oauth2.service_account import Credentials
import logging
from datetime import datetime, date, timedelta
import json
import os
from typing import Dict, List, Tuple, Optional

SCOPES = [
	'https://www.googleapis.com/auth/spreadsheets',
	'https://www.googleapis.com/auth/drive'
]

GOOGLE_SHEETS_CREDENTIALS_FILE = "credentials.json"

COLUMN_HEADERS = [
	"№",
	"Mijoz ismi",
	"Telefon raqami",
	"Mahsulot nomi",
	"Jo'natma turi",
	"Mijoz manzili",
	"Shartnoma imzolangan sana",
	"Hisobot yuborilgan sana",
	"Yuborilgan sana",
	"Shartnoma raqami",
	"Shartnoma summasi",
	"Sotuvchi ismi"
]

def get_google_sheets_client():
	try:
		if not os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE):
			logging.error(f"❌ Credentials fayl topilmadi: {GOOGLE_SHEETS_CREDENTIALS_FILE}")
			return None
		
		credentials = Credentials.from_service_account_file(
			GOOGLE_SHEETS_CREDENTIALS_FILE,
			scopes=SCOPES
		)
		client = gspread.authorize(credentials)
		logging.info("✅ Google Sheets client muvaffaqiyatli yaratildi")
		return client
	
	except Exception as e:
		logging.error(f"❌ Google Sheets client yaratishda xato: {e}")
		return None

def get_worksheet(spreadsheet_id: str, worksheet_name: str):
	try:
		client = get_google_sheets_client()
		if not client:
			logging.error("❌ Google Sheets client yaratilmadi")
			return None
		
		spreadsheet = client.open_by_key(spreadsheet_id)
		logging.info(f"📄 Spreadsheet ochildi: {spreadsheet.title}")
		
		try:
			worksheet = spreadsheet.worksheet(worksheet_name)
			logging.info(f"📋 Worksheet topildi: '{worksheet_name}'")
			
			existing_headers = worksheet.row_values(1)
			if not existing_headers or len(existing_headers) < len(COLUMN_HEADERS):
				logging.info("🔧 Sarlavhalar yangilanmoqda...")
				worksheet.clear()
				worksheet.append_row(COLUMN_HEADERS)
				format_worksheet_headers(worksheet)
		
		except gspread.WorksheetNotFound:
			logging.info(f"➕ Yangi worksheet yaratilmoqda: '{worksheet_name}'")
			worksheet = spreadsheet.add_worksheet(
				title=worksheet_name,
				rows=1000,
				cols=len(COLUMN_HEADERS)
			)
			
			worksheet.append_row(COLUMN_HEADERS)
			format_worksheet_headers(worksheet)
			
			logging.info(f"✅ Yangi worksheet yaratildi va formatlandi: '{worksheet_name}'")
		
		return worksheet
	
	except Exception as e:
		logging.error(f"❌ Worksheet olishda xato: {e}")
		return None

def format_worksheet_headers(worksheet):
	try:
		header_range = f"A1:{chr(64 + len(COLUMN_HEADERS))}1"
		
		worksheet.format(header_range, {
			'backgroundColor': {
				'red': 0.2,
				'green': 0.4,
				'blue': 0.8
			},
			'textFormat': {
				'bold': True,
				'foregroundColor': {
					'red': 1.0,
					'green': 1.0,
					'blue': 1.0
				},
				'fontSize': 11
			},
			'horizontalAlignment': 'CENTER',
			'verticalAlignment': 'MIDDLE'
		})
		
		worksheet.columns_auto_resize(0, len(COLUMN_HEADERS) - 1)
		
		worksheet.format('A:A', {
			'horizontalAlignment': 'CENTER',
			'textFormat': {'bold': True}
		})
		
		worksheet.format('G:I', {
			'horizontalAlignment': 'CENTER'
		})
		
		logging.info("✅ Sarlavhalar muvaffaqiyatli formatlandi")
	
	except Exception as e:
		logging.error(f"❌ Sarlavhalarni formatlashda xato: {e}")

def get_next_row_number(worksheet) -> int:
	try:
		all_values = worksheet.get_all_values()
		
		if len(all_values) <= 1:
			return 1
		
		last_row = all_values[-1]
		if last_row and len(last_row) > 0 and last_row[0].isdigit():
			return int(last_row[0]) + 1
		else:
			return len(all_values)
	
	except Exception as e:
		logging.error(f"❌ Tartib raqamini aniqlashda xato: {e}")
		return 1

def save_report_to_sheets(spreadsheet_id: str, worksheet_name: str, report_data: dict) -> bool:
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if not worksheet:
			logging.error("❌ Worksheet topilmadi yoki yaratilmadi")
			return False
		
		row_number = get_next_row_number(worksheet)
		
		current_date = datetime.now().strftime('%d.%m.%Y')
		current_time = datetime.now().strftime('%H:%M')
		
		row_data = [
			str(row_number),  # A: № (Tartib raqami)
			report_data.get('client_name', ''),  # B: Mijoz ismi
			report_data.get('phone_number', ''),  # C: Telefon raqami
			report_data.get('product_type', ''),  # D: Mahsulot nomi
			'',  # E: Jo'natma turi (bo'sh)
			report_data.get('client_location', ''),  # F: Mijoz manzili
			current_date,  # G: Shartnoma imzolangan sana
			f"{current_date} {current_time}",  # H: Hisobot yuborilgan sana
			'',  # I: Yuborilgan sana (bo'sh)
			report_data.get('contract_id', ''),  # J: Shartnoma raqami
			report_data.get('contract_amount', ''),  # K: Shartnoma summasi
			report_data.get('sender_full_name', '')  # L: Sotuvchi ismi
		]
		
		worksheet.append_row(row_data)
		
		new_row_index = len(worksheet.get_all_values())
		format_new_row(worksheet, new_row_index, row_number)
		
		logging.info(
			f"✅ Hisobot #{row_number} muvaffaqiyatli saqlandi: "
			f"{report_data.get('sender_full_name', 'Noma\'lum')} - "
			f"{report_data.get('product_type', 'Noma\'lum mahsulot')} - "
			f"{report_data.get('contract_amount', 'Noma\'lum summa')}"
		)
		
		return True
	
	except Exception as e:
		logging.error(f"❌ Google Sheets'ga saqlashda xato: {e}")
		return False

def format_new_row(worksheet, row_index: int, row_number: int):
	try:
		row_range = f"A{row_index}:{chr(64 + len(COLUMN_HEADERS))}{row_index}"
		
		if row_number % 2 == 0:
			background_color = {'red': 0.95, 'green': 0.95, 'blue': 0.95}
		else:
			background_color = {'red': 1.0, 'green': 1.0, 'blue': 1.0}
		
		if row_number == 1:
			background_color = {'red': 0.9, 'green': 0.95, 'blue': 1.0}
		
		worksheet.format(row_range, {
			'backgroundColor': background_color,
			'borders': {
				'top': {'style': 'SOLID', 'width': 1},
				'bottom': {'style': 'SOLID', 'width': 1},
				'left': {'style': 'SOLID', 'width': 1},
				'right': {'style': 'SOLID', 'width': 1}
			}
		})
		
		worksheet.format(f'A{row_index}', {
			'horizontalAlignment': 'CENTER',
			'textFormat': {'bold': True}
		})
		
		worksheet.format(f'G{row_index}:I{row_index}', {
			'horizontalAlignment': 'CENTER'
		})
	
	except Exception as e:
		logging.error(f"❌ Qatorni formatlashda xato: {e}")

def test_google_sheets_connection(spreadsheet_id: str, worksheet_name: str) -> Tuple[bool, str]:
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if not worksheet:
			return False, "❌ Worksheet yaratib bo'lmadi yoki ulanish xatosi"
		
		test_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
		test_data = {
			'client_name': 'TEST - Abdullayev Akmal Akbarovich',
			'phone_number': '+998901234567',
			'contract_id': f'TEST-{test_timestamp}',
			'product_type': 'TEST - Samsung Galaxy A54 128GB',
			'client_location': 'TEST - Toshkent shahar, Chilonzor tumani, Bunyodkor ko\'chasi 12-uy',
			'contract_amount': 'TEST - 5,000,000 so\'m',
			'sender_full_name': 'TEST - Sotuvchi',
			'status': 'Tasdiqlandi'
		}
		
		success = save_report_to_sheets(spreadsheet_id, worksheet_name, test_data)
		
		if success:
			all_values = worksheet.get_all_values()
			last_row = all_values[-1] if len(all_values) > 1 else []
			
			success_message = (
				"✅ TEST MUVAFFAQIYATLI BAJARILDI!\n\n"
				"📋 Qo'shilgan test ma'lumotlari:\n"
				f"• Tartib raqami: #{last_row[0] if last_row else 'N/A'}\n"
				f"• Mijoz: {test_data['client_name']}\n"
				f"• Telefon: {test_data['phone_number']}\n"
				f"• Mahsulot: {test_data['product_type']}\n"
				f"• Shartnoma: {test_data['contract_id']}\n"
				f"• Summa: {test_data['contract_amount']}\n"
				f"• Manzil: {test_data['client_location']}\n"
				f"• Sotuvchi: {test_data['sender_full_name']}\n"
				f"• Sana: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
				f"📊 Jami qatorlar: {len(all_values)} (sarlavha bilan)\n"
				f"📈 Ma'lumotlar qatori: {len(all_values) - 1}\n\n"
				"🔗 Google Sheets'da tekshiring!"
			)
			
			return True, success_message
		else:
			return False, "❌ Test ma'lumotlarini qo'shishda xatolik yuz berdi"
	
	except Exception as e:
		error_msg = f"❌ Test qilishda xato: {str(e)}"
		logging.error(error_msg)
		return False, error_msg

def get_reports_statistics(spreadsheet_id: str, worksheet_name: str) -> Dict:
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if not worksheet:
			logging.error("❌ Worksheet topilmadi")
			return {}
		
		all_records = worksheet.get_all_records()
		
		if not all_records:
			logging.info("ℹ️ Google Sheets'da ma'lumotlar topilmadi")
			return {
				'total_reports': 0,
				'sellers_stats': {},
				'monthly_stats': {},
				'daily_stats': {},
				'product_stats': {},
				'location_stats': {},
				'last_updated': datetime.now().strftime('%d.%m.%Y %H:%M:%S')
			}
		
		total_reports = len(all_records)
		sellers_stats = {}
		monthly_stats = {}
		daily_stats = {}
		product_stats = {}
		location_stats = {}
		
		for record in all_records:
			seller = record.get('Sotuvchi ismi', '').strip()
			if seller and seller != '' and 'TEST' not in seller.upper():
				sellers_stats[seller] = sellers_stats.get(seller, 0) + 1
			
			product = record.get('Mahsulot nomi', '').strip()
			if product and product != '' and 'TEST' not in product.upper():
				product_stats[product] = product_stats.get(product, 0) + 1
			
			location = record.get('Mijoz manzili', '').strip()
			if location and 'TEST' not in location.upper():
				if 'shahar' in location.lower():
					city = location.split('shahar')[0].strip() + ' shahar'
				elif 'viloyat' in location.lower():
					city = location.split('viloyat')[0].strip() + ' viloyat'
				else:
					city = location.split(',')[0].strip() if ',' in location else 'Boshqa'
				
				location_stats[city] = location_stats.get(city, 0) + 1
			
			try:
				date_str = record.get('Hisobot yuborilgan sana', '').strip()
				if date_str:
					if ' ' in date_str:
						date_str = date_str.split(' ')[0]
					
					date_obj = datetime.strptime(date_str, '%d.%m.%Y')
					
					month_key = date_obj.strftime('%Y-%m')
					monthly_stats[month_key] = monthly_stats.get(month_key, 0) + 1
					
					day_key = date_obj.strftime('%Y-%m-%d')
					daily_stats[day_key] = daily_stats.get(day_key, 0) + 1
			
			except ValueError as e:
				logging.warning(f"⚠️ Sanani tahlil qilishda xato: {date_str} - {e}")
				continue
		
		top_sellers = dict(sorted(sellers_stats.items(), key=lambda x: x[1], reverse=True)[:10])
		
		top_products = dict(sorted(product_stats.items(), key=lambda x: x[1], reverse=True)[:10])
		
		top_locations = dict(sorted(location_stats.items(), key=lambda x: x[1], reverse=True)[:10])
		
		today = date.today()
		last_30_days = {}
		for i in range(30):
			day = today - timedelta(days=i)
			day_key = day.strftime('%Y-%m-%d')
			last_30_days[day_key] = daily_stats.get(day_key, 0)
		
		statistics = {
			'total_reports': total_reports,
			'sellers_stats': sellers_stats,
			'top_sellers': top_sellers,
			'monthly_stats': monthly_stats,
			'daily_stats': daily_stats,
			'last_30_days': last_30_days,
			'product_stats': product_stats,
			'top_products': top_products,
			'location_stats': location_stats,
			'top_locations': top_locations,
			'last_updated': datetime.now().strftime('%d.%m.%Y %H:%M:%S')
		}
		
		logging.info(f"📊 Statistika muvaffaqiyatli olindi: {total_reports} ta yozuv")
		return statistics
	
	except Exception as e:
		logging.error(f"❌ Statistika olishda xato: {e}")
		return {}

def get_reports_by_date_range(spreadsheet_id: str, worksheet_name: str, start_date: str, end_date: str) -> List[Dict]:
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if not worksheet:
			return []
		
		all_records = worksheet.get_all_records()
		filtered_reports = []
		
		start_dt = datetime.strptime(start_date, '%Y-%m-%d')
		end_dt = datetime.strptime(end_date, '%Y-%m-%d')
		
		for record in all_records:
			try:
				date_str = record.get('Hisobot yuborilgan sana', '').strip()
				if date_str:
					if ' ' in date_str:
						date_str = date_str.split(' ')[0]
					
					record_date = datetime.strptime(date_str, '%d.%m.%Y')
					if start_dt <= record_date <= end_dt:
						filtered_reports.append(record)
			
			except ValueError:
				continue
		
		logging.info(f"📅 Sana oralig'ida {len(filtered_reports)} ta hisobot topildi")
		return filtered_reports
	
	except Exception as e:
		logging.error(f"❌ Sana bo'yicha filtrlashda xato: {e}")
		return []

def get_seller_reports(spreadsheet_id: str, worksheet_name: str, seller_name: str) -> List[Dict]:
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if not worksheet:
			return []
		
		all_records = worksheet.get_all_records()
		seller_reports = []
		
		for record in all_records:
			record_seller = record.get('Sotuvchi ismi', '').strip()
			if record_seller.lower() == seller_name.lower():
				seller_reports.append(record)
		
		logging.info(f"👤 Sotuvchi '{seller_name}' uchun {len(seller_reports)} ta hisobot topildi")
		return seller_reports
	
	except Exception as e:
		logging.error(f"❌ Sotuvchi hisobotlarini olishda xato: {e}")
		return []

def update_contract_amount(spreadsheet_id: str, worksheet_name: str, contract_id: str, amount: str) -> bool:
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if not worksheet:
			return False
		
		all_values = worksheet.get_all_values()
		
		if len(all_values) <= 1:
			return False
		
		headers = all_values[0]
		contract_col = None
		amount_col = None
		
		for i, header in enumerate(headers):
			if 'Shartnoma raqami' in header:
				contract_col = i
			elif 'Shartnoma summasi' in header:
				amount_col = i
		
		if contract_col is None or amount_col is None:
			logging.error("❌ Kerakli ustunlar topilmadi")
			return False
		
		for row_idx, row in enumerate(all_values[1:], start=2):
			if len(row) > contract_col and row[contract_col] == contract_id:
				cell_address = f"{chr(65 + amount_col)}{row_idx}"
				worksheet.update(cell_address, amount)
				
				logging.info(f"💰 Shartnoma {contract_id} uchun summa '{amount}' ga yangilandi")
				return True
		
		logging.warning(f"⚠️ Shartnoma ID {contract_id} topilmadi")
		return False
	
	except Exception as e:
		logging.error(f"❌ Summa yangilashda xato: {e}")
		return False

def clear_test_data(spreadsheet_id: str, worksheet_name: str) -> bool:
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if not worksheet:
			return False
		
		all_values = worksheet.get_all_values()
		
		if len(all_values) <= 1:
			return True
		
		rows_to_delete = []
		
		for row_idx, row in enumerate(all_values[1:], start=2):
			if len(row) >= len(COLUMN_HEADERS):
				is_test_row = any('TEST' in str(cell).upper() for cell in row)
				
				if is_test_row:
					rows_to_delete.append(row_idx)
		
		for row_idx in reversed(rows_to_delete):
			worksheet.delete_rows(row_idx)
		
		if rows_to_delete:
			renumber_rows(worksheet)
		
		logging.info(f"🧹 {len(rows_to_delete)} ta test ma'lumoti tozalandi")
		return True
	
	except Exception as e:
		logging.error(f"❌ Test ma'lumotlarini tozalashda xato: {e}")
		return False

def renumber_rows(worksheet):
	try:
		all_values = worksheet.get_all_values()
		
		if len(all_values) <= 1:
			return
		
		for i in range(1, len(all_values)):
			new_number = i
			cell_address = f"A{i + 1}"
			worksheet.update(cell_address, str(new_number))
		
		logging.info(f"🔢 {len(all_values) - 1} ta qatordagi raqamlar yangilandi")
	
	except Exception as e:
		logging.error(f"❌ Qator raqamlarini yangilashda xato: {e}")

def get_sheet_info(spreadsheet_id: str) -> Dict:
	try:
		client = get_google_sheets_client()
		if not client:
			return {}
		
		spreadsheet = client.open_by_key(spreadsheet_id)
		
		info = {
			'title': spreadsheet.title,
			'id': spreadsheet.id,
			'url': spreadsheet.url,
			'worksheets': [],
			'last_updated': datetime.now().strftime('%d.%m.%Y %H:%M:%S')
		}
		
		for worksheet in spreadsheet.worksheets():
			all_values = worksheet.get_all_values()
			data_count = len(all_values) - 1 if all_values else 0
			
			worksheet_info = {
				'title': worksheet.title,
				'id': worksheet.id,
				'row_count': worksheet.row_count,
				'col_count': worksheet.col_count,
				'data_count': data_count
			}
			info['worksheets'].append(worksheet_info)
		
		logging.info(f"📋 Sheet ma'lumotlari olindi: {info['title']}")
		return info
	
	except Exception as e:
		logging.error(f"❌ Sheet ma'lumotlarini olishda xato: {e}")
		return {}

def handle_sheets_errors(func):
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except gspread.exceptions.APIError as e:
			logging.error(f"❌ Google Sheets API xatosi: {e}")
			return None
		except gspread.exceptions.SpreadsheetNotFound:
			logging.error("❌ Spreadsheet topilmadi")
			return None
		except gspread.exceptions.WorksheetNotFound:
			logging.error("❌ Worksheet topilmadi")
			return None
		except Exception as e:
			logging.error(f"❌ Kutilmagan xato: {e}")
			return None
	
	
	return wrapper

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
	handlers=[
		logging.StreamHandler(),
		logging.FileHandler('google_sheets.log', encoding='utf-8')
	]
)

logging.info("🚀 Google Sheets Integration moduli muvaffaqiyatli yuklandi")
logging.info("📊 Ma'lumotlar saqlash tartibi: Birinchi hisobot #1 (eng tepada), keyingisi #2 (pastda)")
logging.info(
	"📋 Ustunlar: № | Mijoz | Telefon | Mahsulot | Jo'natma | Manzil | Sana | Hisobot | Yuborilgan | Shartnoma | Summa | Sotuvchi")
