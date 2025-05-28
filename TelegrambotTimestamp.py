import logging
import os
from datetime import datetime
from openpyxl import Workbook, load_workbook
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
import cv2
import pytesseract
from PIL import Image
import re
import numpy as np
import sqlite3
import shutil
import threading
import asyncio

# --- Constants and Configuration ---
IMAGE_FOLDER = "image_folder"
EXCEL_FILENAME = "image_metadata.xlsx"
ALLOWED_USERS_FILE = "User.txt"
MAX_DAILY_IMAGES = 99999
BOT_TOKEN = "7810837728:AAHTW70rIspyZfCdW8KBVXYkPC5lkbIUafQ"

ML_FEEDBACK_DB = "ml_feedback.db"
LOG_FILENAME = "bot_activity.log"

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILENAME, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

tesseract_cmd_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

try:
    if os.path.exists(tesseract_cmd_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd_path
    else:
        logging.warning(f"Tesseract executable not found at '{tesseract_cmd_path}'. Trying system PATH.")
        pytesseract.pytesseract.tesseract_cmd = 'tesseract'
except pytesseract.TesseractNotFoundError:
    logging.error("Tesseract is not installed or not found in system PATH. OCR will not work.")
except Exception as e:
    logging.error(f"Error setting Tesseract path: {e}")

DATE_TIME_PATTERNS = [
    (r'(\d{2}[-./]\d{2}[-./]\d{4})\s+(\d{2}:\d{2}:\d{2})',
     ['%d-%m-%Y %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%d.%m.%Y %H:%M:%S'],
     lambda d, t: f"{str(int(d[6:10]) - 543) if int(d[6:10]) > datetime.now().year + 50 and len(d) == 10 and d[6:10].isdigit() else d[6:10]}{d[2:6]}{d[0:2]} {t}"),
    (r'(\d{2}[-./]\d{2}[-./]\d{4})\s+(\d{2}:\d{2})',
     ['%d-%m-%Y %H:%M', '%d/%m/%Y %H:%M', '%d.%m.%Y %H:%M'],
     lambda d, t: f"{str(int(d[6:10]) - 543) if int(d[6:10]) > datetime.now().year + 50 and len(d) == 10 and d[6:10].isdigit() else d[6:10]}{d[2:6]}{d[0:2]} {t}"),
    (r'(\d{4}[-./]\d{2}[-./]\d{2})\s+(\d{2}:\d{2}:\d{2})',
     ['%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y.%m.%d %H:%M:%S'],
     lambda d, t: f"{d} {t}"),
    (r'(\d{4}[-./]\d{2}[-./]\d{2})\s+(\d{2}:\d{2})',
     ['%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M', '%Y.%m-%d %H:%M'],
     lambda d, t: f"{d} {t}"),
    (r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})', ['%m/%d/%Y %H:%M:%S'], lambda d, t: f"{d} {t}"),
    (r'(\d{2}[-./]\d{2}[-./]\d{2})\s+(\d{2}:\d{2}:\d{2})',
     ['%d-%m-%y %H:%M:%S', '%d/%m/%y %H:%M:%S', '%d.%m.%y %H:%M:%S'],
     lambda d, t: f"{d} {t}"),
    (r'(\d{2}[-./]\d{2}[-./]\d{2})\s+(\d{2}:\d{2})',
     ['%d-%m-%y %H:%M', '%d/%m/%y %H:%M', '%d.%m.%y %H:%M'],
     lambda d, t: f"{d} {t}"),
    (r'(\d{2}:\d{2}:\d{2})\s+(\d{2}[-./]\d{2}[-./]\d{4})',
     ['%H:%M:%S %d-%m-%Y', '%H:%M:%S %d/%m-%Y', '%H:%M:%S %d.%m.%Y'],
     lambda t, d: f"{str(int(d[6:10]) - 543) if int(d[6:10]) > datetime.now().year + 50 and len(d) == 10 and d[6:10].isdigit() else d[6:10]}{d[2:6]}{d[0:2]} {t}"),
    (r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s+\d{2}:\d{2}:\d{2})',
     ['%d %b %Y %H:%M:%S'], lambda s: s),
    (r'(\d{2}[-./]\d{2}[-./]\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M)',
     ['%d/%m/%y %I:%M %p', '%d/%m/%y %I:%M:%S %p', '%d-%m-%y %I:%M %p', '%d-%m-%y %I:%M:%S %p'],
     lambda s: s),
    (r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', ['%Y-%m-%dT%H:%M:%S'], lambda s: s),
    (r'(\d{1,2})\s+(พ\.ค\.)\s+(\d{4})\s+(\d{2}:\d{2}:\d{2})',
     ['%d %b %Y %H:%M:%S'],
     lambda d, m, y, t: f"{d} {m.replace('พ.ค.', 'May')} {str(int(y) - 543) if int(y) > datetime.now().year + 50 else y} {t}"),
    (r'(\d{1,2}[-./]\d{1,2}[-./]\d{2,4})\s+เวลา\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*น\.',
     ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M'],
     lambda d_str, t_str: f"{str(int(d_str[-4:]) - 543) if len(d_str) >= 4 and int(d_str[-4:]) > datetime.now().year + 50 else d_str[-4:]}{d_str[2:6]}{d[0:2]} {t_str}" if len(d_str) >= 4 and d_str[-4:].isdigit() else f"{d_str} {t_str}"
    )
]

def preprocess_image_for_ocr(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced_gray = clahe.apply(gray)
    blurred_image = cv2.GaussianBlur(enhanced_gray, (3, 3), 0)
    thresh_image = cv2.adaptiveThreshold(blurred_image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                         cv2.THRESH_BINARY_INV, 15, 5)

    coords = np.column_stack(np.where(thresh_image > 0))
    if coords.size > 0:
        rect = cv2.minAreaRect(coords)
        angle = rect[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        (h, w) = thresh_image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        thresh_image = cv2.warpAffine(thresh_image, M, (w, h),
                                      flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    kernel_dilate = np.ones((1,1), np.uint8)
    kernel_erode = np.ones((1,1), np.uint8)
    denoised_image = cv2.dilate(thresh_image, kernel_dilate, iterations=1)
    denoised_image = cv2.erode(denoised_image, kernel_erode, iterations=1)
    return denoised_image

def find_timestamp_roi(image):
    h, w, _ = image.shape
    rois = []

    rois.append((int(w * 0.5), int(h * 0.75), int(w * 0.5), int(h * 0.25)))
    rois.append((0, int(h * 0.75), int(w * 0.5), int(h * 0.25)))
    rois.append((int(w * 0.5), 0, int(w * 0.5), int(h * 0.25)))
    rois.append((0, 0, int(w * 0.5), int(h * 0.25)))

    rois.append((int(w * 0.65), int(h * 0.85), int(w * 0.35), int(h * 0.15)))
    rois.append((0, int(h * 0.85), int(w * 0.35), int(h * 0.15)))
    rois.append((int(w * 0.65), 0, int(w * 0.35), int(h * 0.15)))
    rois.append((0, 0, int(w * 0.35), int(h * 0.15)))

    rois.append((int(w * 0.25), int(h * 0.25), int(w * 0.5), int(h * 0.5)))
    rois.append((int(w * 0.1), int(h * 0.8), int(w * 0.8), int(h * 0.2)))
    rois.append((int(w * 0.1), 0, int(w * 0.8), int(h * 0.2)))
    rois.append((0, int(h * 0.1), int(w * 0.2), int(h * 0.8)))
    rois.append((int(w * 0.8), int(h * 0.1), int(w * 0.2), int(h * 0.8)))
    rois.append((int(w * 0.05), int(h * 0.05), int(w * 0.9), int(h * 0.9)))

    return rois

def extract_timestamp_from_image_ocr(image_path):
    logging.info(f"Attempting to extract timestamp from: {image_path}")
    
    try:
        img = cv2.imread(image_path)
        if img is None:
            logging.error(f"Could not load image: {image_path}")
            return None

        potential_rois = find_timestamp_roi(img)
        best_parsed_dt = None

        for i, (x_start, y_start, roi_width, roi_height) in enumerate(potential_rois):
            x_end = min(x_start + roi_width, img.shape[1])
            y_end = min(y_start + roi_height, img.shape[0])
            
            if x_start >= x_end or y_start >= y_end:
                continue

            current_roi = img[y_start:y_end, x_start:x_end]
            if current_roi.shape[0] == 0 or current_roi.shape[1] == 0:
                continue

            processed_roi = preprocess_image_for_ocr(current_roi)
            pil_img_roi = Image.fromarray(processed_roi)

            tess_config_base = '--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789-:/,. '
            extracted_text = pytesseract.image_to_string(pil_img_roi, lang='eng', config=tess_config_base).strip()
            
            if not extracted_text or not any(c.isdigit() for c in extracted_text):
                tess_config_fallback = '--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789-:/,.พคกบวศจภลยชซฐณตถนปผฝฟมยรฤลฬอสอหฮะัาิวีึืุูเแไใโ์็่้๊๋์ๆฯะำเเโใไ '
                extracted_text = pytesseract.image_to_string(pil_img_roi, lang='tha+eng', config=tess_config_fallback).strip()

            logging.debug(f"ROI ({x_start},{y_start},{x_end},{y_end}) - Extracted text: '{extracted_text}'")

            for regex_pattern, datetime_formats, preprocess_func in DATE_TIME_PATTERNS:
                match = re.search(regex_pattern, extracted_text)
                if match:
                    matched_groups = [group.strip() for group in match.groups() if group is not None]
                    processed_str = preprocess_func(*matched_groups) if preprocess_func else " ".join(matched_groups)
                    
                    logging.debug(f"Attempting to parse '{processed_str}' with regex: {regex_pattern}")

                    for dt_format in datetime_formats:
                        try:
                            parsed_dt = datetime.strptime(processed_str, dt_format)
                            current_time = datetime.now()
                            if abs((current_time - parsed_dt).days) < 365 * 10 or parsed_dt.year > current_time.year + 5:
                                if best_parsed_dt is None or parsed_dt < best_parsed_dt:
                                    best_parsed_dt = parsed_dt
                                    logging.info(f"Found and parsed timestamp: {best_parsed_dt} (from '{processed_str}') in ROI {i} with format {dt_format}")
                                    return best_parsed_dt
                                
                        except ValueError:
                            continue

        if best_parsed_dt:
            logging.info(f"Final best timestamp found for {image_path}: {best_parsed_dt}")
            return best_parsed_dt
        else:
            logging.warning(f"No valid timestamp found in any ROI or with any pattern for {image_path}.")
            return None

    except Exception as e:
        logging.error(f"Error during timestamp extraction for {image_path}: {e}")
        return None

def initialize_directories():
    os.makedirs(IMAGE_FOLDER, exist_ok=True)
    logging.info(f"Directory '{IMAGE_FOLDER}' ensured to exist.")

def initialize_excel():
    sheet_name = "ImageMetadata"
    if not os.path.exists(EXCEL_FILENAME):
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = sheet_name
            ws.append(["ID (username)", "Bot Timestamp", "Image Log Name", "Extracted Image Timestamp"])
            wb.save(EXCEL_FILENAME)
            logging.info(f"New Excel file '{EXCEL_FILENAME}' created with '{sheet_name}' sheet and headers.")
        except Exception as e:
            logging.error(f"Failed to create Excel file '{EXCEL_FILENAME}': {e}")
    else:
        try:
            wb = load_workbook(EXCEL_FILENAME)
            if sheet_name not in wb.sheetnames:
                ws = wb.create_sheet(sheet_name)
                ws.append(["ID (username)", "Bot Timestamp", "Image Log Name", "Extracted Image Timestamp"])
                logging.info(f"Created new sheet '{sheet_name}' in '{EXCEL_FILENAME}' with headers.")
            else:
                ws = wb[sheet_name]
                headers = [cell.value for cell in ws[1]]
                if "Extracted Image Timestamp" not in headers:
                    ws.cell(row=1, column=len(headers) + 1, value="Extracted Image Timestamp")
                    logging.info(f"Added 'Extracted Image Timestamp' column to '{sheet_name}' in '{EXCEL_FILENAME}'.")
            wb.save(EXCEL_FILENAME)
        except Exception as e:
            logging.warning(f"Could not initialize sheet '{sheet_name}' in '{EXCEL_FILENAME}': {e}")

def initialize_sqlite_db():
    conn = None
    try:
        conn = sqlite3.connect(ML_FEEDBACK_DB)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS missed_timestamps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_filename TEXT NOT NULL UNIQUE,
                timestamp_from_bot TEXT NOT NULL,
                ml_correct_timestamp TEXT,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logging.info(f"SQLite database '{ML_FEEDBACK_DB}' and table 'missed_timestamps' initialized.")
    except sqlite3.Error as e:
        logging.error(f"Error initializing SQLite database: {e}")
    finally:
        if conn:
            conn.close()

def insert_missed_timestamp_record(image_filename, timestamp_from_bot):
    conn = None
    try:
        conn = sqlite3.connect(ML_FEEDBACK_DB)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO missed_timestamps (image_filename, timestamp_from_bot)
            VALUES (?, ?)
        ''', (image_filename, timestamp_from_bot))
        conn.commit()
        if cursor.rowcount > 0:
            logging.info(f"Inserted missed timestamp record for '{image_filename}' into SQLite.")
        else:
            logging.info(f"Record for '{image_filename}' already exists in SQLite (ignored).")
    except sqlite3.Error as e:
        logging.error(f"Error inserting into missed_timestamps: {e}")
    finally:
        if conn:
            conn.close()

def load_allowed_users(filename=ALLOWED_USERS_FILE):
    if not os.path.exists(filename):
        logging.warning(f"'{filename}' not found. No users will be allowed unless created.")
        return set()
    try:
        with open(filename, "r", encoding="utf-8") as f:
            allowed_users = {line.strip().lower() for line in f if line.strip()}
        logging.info(f"Loaded {len(allowed_users)} allowed users from '{filename}'.")
        return allowed_users
    except Exception as e:
        logging.error(f"Error loading allowed users from '{filename}': {e}")
        return set()

# --- New Function: append_to_excel (ย้ายมาไว้ที่นี่เพื่อเรียกใช้ได้ง่าย) ---
def append_to_excel(username, bot_timestamp, filename, extracted_image_timestamp_str):
    try:
        wb = load_workbook(EXCEL_FILENAME)
        ws = wb["ImageMetadata"]
        ws.append([username, bot_timestamp, filename, extracted_image_timestamp_str])
        wb.save(EXCEL_FILENAME)
        logging.info(f"✅ Inserted record for '{filename}' into Excel.")
    except Exception as e:
        logging.error(f"❌ Excel write error for '{filename}': {e}")


def process_photo_thread_target(loop, bot_instance, file_path_no_filename, filename_with_suffix, username, bot_timestamp, chat_id):
    logging.info(f"[THREAD] Starting processing for {filename_with_suffix} from {username}")
    
    full_image_path = os.path.join(file_path_no_filename, filename_with_suffix)
    extracted_image_timestamp = None
    
    try:
        extracted_image_timestamp = extract_timestamp_from_image_ocr(full_image_path)

        if extracted_image_timestamp:
            logging.info(f"[THREAD] 📸 Extracted Timestamp from image: {extracted_image_timestamp}")
        else:
            logging.warning(f"[THREAD] ⚠️ Could not extract timestamp from image: {filename_with_suffix}. Logging to SQLite.")
            insert_missed_timestamp_record(filename_with_suffix, bot_timestamp)

    except Exception as e:
        logging.error(f"[THREAD] 🔥 Error during image OCR for '{filename_with_suffix}': {e}")
    
    try:
        # ใช้ append_to_excel function ที่แยกไว้
        append_to_excel(username, bot_timestamp, filename_with_suffix,
                        extracted_image_timestamp.strftime("%Y-%m-%d %H:%M:%S") if extracted_image_timestamp else "N/A")

        reply_message = f"✅ บันทึกข้อมูลเรียบร้อยแล้ว\nชื่อไฟล์: {filename_with_suffix}\n"
        if extracted_image_timestamp:
            reply_message += f"เวลาในภาพ: {extracted_image_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            reply_message += "StatusN \n(ข้อมูลถูกบันทึกในฐานข้อมูลเพื่อการตรวจสอบ)"
            
        async def send_reply_async():
            await bot_instance.send_message(chat_id=chat_id, text=reply_message)
        
        asyncio.run_coroutine_threadsafe(send_reply_async(), loop)

    except Exception as e:
        logging.error(f"[THREAD] ❌ Excel write error for '{filename_with_suffix}': {e}")
        async def send_error_reply_async():
            await bot_instance.send_message(chat_id=chat_id, text="❌ เกิดข้อผิดพลาดในการบันทึกข้อมูล")
        asyncio.run_coroutine_threadsafe(send_error_reply_async(), loop)
        
    logging.info(f"[THREAD] Finished processing for {filename_with_suffix}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await update.message.reply_text(
        f"สวัสดีครับ {user.first_name}!\n"
        "บอทนี้ใช้สำหรับรับภาพและบันทึกข้อมูล Timestamp\n"
        "คุณสามารถส่งรูปภาพมาได้เลย (หากได้รับอนุญาต)\n"
        "ใช้ /help เพื่อดูคำสั่งเพิ่มเติม"
    )
    logging.info(f"User {user.username} (ID: {user.id}) issued /start command.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "คำสั่งที่มี:\n"
        "/start - เริ่มต้นใช้งานบอท\n"
        "/help - แสดงคำสั่งนี้\n"
        "คุณสามารถส่งรูปภาพที่มี Timestamp เพื่อให้บอทประมวลผลได้"
    )
    logging.info(f"User {update.message.from_user.username} (ID: {update.message.from_user.id}) issued /help command.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("📸 Received a photo message.")
    
    user = update.message.from_user
    username = user.username if user.username else str(user.id)
    chat_id = update.message.chat_id
    logging.info(f"👤 Photo from user: {username} (ID: {user.id})")

    allowed_users = load_allowed_users()
    if username.lower() not in allowed_users:
        await update.message.reply_text("❌ คุณไม่ได้รับอนุญาตให้ส่งภาพเข้าเก็บระบบ")
        logging.warning(f"🚫 Unauthorized user tried to send image: {username}")
        return

    photo = update.message.photo[-1]
    
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    user_folder_path = os.path.join(IMAGE_FOLDER, username)
    date_folder_path = os.path.join(user_folder_path, date_str)

    os.makedirs(date_folder_path, exist_ok=True)
    logging.info(f"Ensured directory exists: {date_folder_path}")

    base_filename_prefix = f"{username}-log{date_str}"
    
    filename_with_suffix = None
    for i in range(1, MAX_DAILY_IMAGES + 1):
        suffix = f"{i:06}"
        temp_filename = f"{base_filename_prefix}-{suffix}.jpg"
        temp_file_path = os.path.join(date_folder_path, temp_filename)
        if not os.path.exists(temp_file_path):
            filename_with_suffix = temp_filename
            break
    
    if not filename_with_suffix:
        await update.message.reply_text(
                f"❌ เก็บภาพไม่สำเร็จ: เกินจำนวนสูงสุด {MAX_DAILY_IMAGES} ภาพในวันเดียวกัน"
        )
        logging.error(f"Exceeded max daily images for {username} on {date_str}.")
        return

    full_download_path = os.path.join(date_folder_path, filename_with_suffix)
    
    try:
        file_obj = await context.bot.get_file(photo.file_id)
        await file_obj.download_to_drive(full_download_path)
        logging.info(f"📥 Downloaded file to {full_download_path}")
        await update.message.reply_text("ได้รับรูปภาพแล้ว กำลังประมวลผล...")
    except Exception as e:
        logging.error(f"❌ Error downloading file '{filename_with_suffix}': {e}")
        await update.message.reply_text("❌ โหลดภาพล้มเหลว")
        return

    bot_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    current_loop = asyncio.get_event_loop()
    # ส่ง application.bot ไปยังเธรด
    thread = threading.Thread(target=process_photo_thread_target, 
                              args=(current_loop, context.bot, date_folder_path, filename_with_suffix, username, bot_timestamp, chat_id))
    thread.start()

# --- Resume Manager Logic (ย้ายมาไว้ที่นี่เพื่อความสะดวกในการรวมไฟล์) ---
import glob # จำเป็นสำหรับ glob.glob

def get_processed_image_filenames_for_resume(excel_filename_param):
    processed_files = set()
    try:
        if os.path.exists(excel_filename_param):
            wb = load_workbook(excel_filename_param)
            ws = wb["ImageMetadata"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row and len(row) > 2:
                    processed_files.add(row[2])
    except Exception as e:
        logging.error(f"Error reading processed filenames from Excel '{excel_filename_param}': {e}")
    return processed_files

def find_unprocessed_images_for_resume(image_folder_param, processed_files_set):
    unprocessed_images = []
    for root, dirs, files in os.walk(image_folder_param):
        for img_file_name in files:
            if img_file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                if img_file_name not in processed_files_set:
                    full_path = os.path.join(root, img_file_name)
                    unprocessed_images.append(full_path)
    return unprocessed_images

def process_single_unprocessed_image_for_resume(loop, bot_instance, full_image_path: str):
    logging.info(f"[RESUME] Processing unprocessed image: {full_image_path}")

    filename_with_suffix = os.path.basename(full_image_path)
    username_match = re.match(r'(.+)-log\d{4}-\d{2}-\d{2}-', filename_with_suffix)
    username = username_match.group(1) if username_match else "unknown_user"
    
    bot_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    extracted_image_timestamp = None
    try:
        extracted_image_timestamp = extract_timestamp_from_image_ocr(full_image_path)

        if extracted_image_timestamp:
            logging.info(f"[RESUME] 📸 Extracted Timestamp from image: {extracted_image_timestamp}")
        else:
            logging.warning(f"[RESUME] ⚠️ Could not extract timestamp from image: {filename_with_suffix}. Logging to SQLite.")
            insert_missed_timestamp_record(filename_with_suffix, bot_timestamp)

    except Exception as e:
        logging.error(f"[RESUME] 🔥 Error during image OCR for '{filename_with_suffix}': {e}")
    
    try:
        append_to_excel(username, bot_timestamp, filename_with_suffix,
                        extracted_image_timestamp.strftime("%Y-%m-%d %H:%M:%S") if extracted_image_timestamp else "N/A")
        logging.info(f"[RESUME] ✅ Inserted record for '{filename_with_suffix}' into Excel.")
    except Exception as e:
        logging.error(f"[RESUME] ❌ Excel write error for '{filename_with_suffix}': {e}")
        
    logging.info(f"[RESUME] Finished processing for {filename_with_suffix}")

def resume_unprocessed_tasks_init_main(bot_instance_param):
    logging.info("Checking for any unprocessed images from previous sessions...")
    
    processed_files_set = get_processed_image_filenames_for_resume(EXCEL_FILENAME)
    
    unprocessed_images = find_unprocessed_images_for_resume(IMAGE_FOLDER, processed_files_set)
    
    if unprocessed_images:
        logging.info(f"Found {len(unprocessed_images)} unprocessed images. Starting background processing...")
        current_loop = asyncio.get_event_loop()
        for img_path in unprocessed_images:
            thread = threading.Thread(target=process_single_unprocessed_image_for_resume,
                                      args=(current_loop, bot_instance_param, img_path))
            thread.start()
    else:
        logging.info("No unprocessed images found. All tasks are up-to-date.")


if __name__ == "__main__":
    logging.info("Starting Telegram Bot...")
    
    initialize_directories()
    initialize_excel()
    initialize_sqlite_db()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # --- Resume Unprocessed Tasks ---
    # ส่ง application.bot ไปยังฟังก์ชัน resume
    resume_unprocessed_tasks_init_main(application.bot) 

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    logging.info("Bot is ready to poll for updates.")
    application.run_polling()
