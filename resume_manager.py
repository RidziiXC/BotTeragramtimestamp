import logging
import os
import glob
import re # สำหรับ regex ในการแยก username จากชื่อไฟล์
from datetime import datetime
import asyncio
import threading
from openpyxl import load_workbook # จำเป็นสำหรับ get_processed_image_filenames
from telegram.ext import ContextTypes # จำเป็นสำหรับการส่ง ContextTypes เข้ามา

# ต้อง Import โมดูลที่จำเป็นจากโปรเจกต์เดียวกัน (ถ้าไม่ได้แยกทั้งหมด)
# ถ้าโปรเจกต์ของคุณยังเป็นไฟล์เดียว โปรดปรับ import เหล่านี้ให้เป็นชื่อฟังก์ชันโดยตรง
# แต่ถ้าคุณมีโมดูลแยกอย่าง ocr_processor.py, excel_manager.py, sqlite_manager.py อยู่แล้ว
# ก็สามารถใช้ import แบบนี้ได้

# สมมติว่าฟังก์ชันเหล่านี้อยู่ในไฟล์หลัก หรือถูก import ไว้แล้วในไฟล์หลักและสามารถเข้าถึงได้
# หากคุณยังใช้โค้ดแบบไฟล์เดียว โปรดตรวจสอบว่าฟังก์ชันเหล่านี้สามารถถูกเรียกได้โดยตรง

# เนื่องจากต้องการแยกแค่ฟังก์ชันใหม่ เราจะอ้างอิงถึงฟังก์ชันจากโค้ดหลักโดยตรง
# หากคุณแยกเป็นโมดูลจริงๆ จะต้องมีการ import ocr_processor, excel_manager, sqlite_manager
# และตัวแปรจาก config (เช่น IMAGE_FOLDER, EXCEL_FILENAME, ML_FEEDBACK_DB) เข้ามาในโมดูลนี้
# ในตัวอย่างนี้ ผมจะสมมติว่าตัวแปร Constants และฟังก์ชันหลัก
# (extract_timestamp_from_image_ocr, append_to_excel, insert_missed_timestamp_record)
# สามารถเข้าถึงได้จาก context หรือ global scope (ซึ่งไม่ใช่แนวทางที่ดีนักในการแยกโมดูลที่แท้จริง)
# แต่เพื่อให้ตรงกับความต้องการ "แค่เฉพาะฟังก์ชันใหม่ที่บอกที่ต้องการแยก"
# เราจะส่งผ่าน dependencies ที่จำเป็นเข้ามา

def get_processed_image_filenames(excel_filename_param):
    """
    Reads the Excel file and returns a set of image filenames that have already been processed.
    """
    processed_files = set()
    try:
        if os.path.exists(excel_filename_param):
            wb = load_workbook(excel_filename_param)
            ws = wb["ImageMetadata"]
            # ข้ามแถว header
            for row in ws.iter_rows(min_row=2, values_only=True):
                # ชื่อไฟล์รูปภาพอยู่ในคอลัมน์ที่ 3 (Index 2)
                if row and len(row) > 2:
                    processed_files.add(row[2])
    except Exception as e:
        logging.error(f"Error reading processed filenames from Excel '{excel_filename_param}': {e}")
    return processed_files

def find_unprocessed_images(image_folder_param, processed_files_set):
    """
    Scans the image_folder for image files that are not in the processed_files set.
    Returns a list of full paths to unprocessed images.
    Expects structure: image_folder/username/date/filename.jpg
    """
    unprocessed_images = []
    # ใช้ os.walk เพื่อ traverse โฟลเดอร์ย่อยทั้งหมด
    for root, dirs, files in os.walk(image_folder_param):
        for img_file_name in files:
            if img_file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')): # ตรวจสอบเฉพาะไฟล์รูปภาพ
                if img_file_name not in processed_files_set:
                    full_path = os.path.join(root, img_file_name)
                    unprocessed_images.append(full_path)
    return unprocessed_images

def process_single_unprocessed_image(
    loop, # asyncio event loop ของเธรดหลัก
    context, # ContextTypes.DEFAULT_TYPE จาก telegram.ext
    full_image_path: str,
    # ส่งผ่านฟังก์ชันที่จำเป็นเข้ามาเป็นพารามิเตอร์
    # เนื่องจากโมดูลนี้ถูกแยกออกมา จึงไม่สามารถเข้าถึงฟังก์ชันเหล่านี้โดยตรงจาก global scope ได้
    extract_timestamp_func,
    append_to_excel_func,
    insert_missed_record_func,
    excel_filename_param,
    ml_feedback_db_param,
    image_folder_param
):
    """
    Processes a single unprocessed image (OCR, Excel/SQLite logging).
    This function simulates the work done by process_photo_thread_target but for existing files.
    """
    logging.info(f"[RESUME] Processing unprocessed image: {full_image_path}")

    filename_with_suffix = os.path.basename(full_image_path)
    
    # พยายามดึง username จากชื่อไฟล์ (ต้องมีรูปแบบชื่อไฟล์ที่แน่นอน)
    # เช่น "username-logYYYY-MM-DD-######.jpg"
    username_match = re.match(r'(.+)-log\d{4}-\d{2}-\d{2}-', filename_with_suffix)
    username = username_match.group(1) if username_match else "unknown_user"
    
    bot_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    extracted_image_timestamp = None
    try:
        extracted_image_timestamp = extract_timestamp_func(full_image_path)

        if extracted_image_timestamp:
            logging.info(f"[RESUME] 📸 Extracted Timestamp from image: {extracted_image_timestamp}")
        else:
            logging.warning(f"[RESUME] ⚠️ Could not extract timestamp from image: {filename_with_suffix}. Logging to SQLite.")
            insert_missed_record_func(filename_with_suffix, bot_timestamp)

    except Exception as e:
        logging.error(f"[RESUME] 🔥 Error during image OCR for '{filename_with_suffix}': {e}")
    
    try:
        extracted_image_timestamp_str = extracted_image_timestamp.strftime("%Y-%m-%d %H:%M:%S") if extracted_image_timestamp else "N/A"
        append_to_excel_func(username, bot_timestamp, filename_with_suffix, extracted_image_timestamp_str)
        logging.info(f"[RESUME] ✅ Inserted record for '{filename_with_suffix}' into Excel.")
    except Exception as e:
        logging.error(f"[RESUME] ❌ Excel write error for '{filename_with_suffix}': {e}")
        
    logging.info(f"[RESUME] Finished processing for {filename_with_suffix}")

def resume_unprocessed_tasks_init(context: ContextTypes.DEFAULT_TYPE,
                                  image_folder_param, excel_filename_param, ml_feedback_db_param,
                                  extract_timestamp_func, append_to_excel_func, insert_missed_record_func):
    """
    Initiates the process of finding and processing any unprocessed images.
    This runs when the bot starts up.
    """
    logging.info("Checking for any unprocessed images from previous sessions...")
    
    processed_files_set = get_processed_image_filenames(excel_filename_param)
    
    unprocessed_images = find_unprocessed_images(image_folder_param, processed_files_set)
    
    if unprocessed_images:
        logging.info(f"Found {len(unprocessed_images)} unprocessed images. Starting background processing...")
        current_loop = asyncio.get_event_loop()
        for img_path in unprocessed_images:
            thread = threading.Thread(target=process_single_unprocessed_image, 
                                      args=(current_loop, context, img_path,
                                            extract_timestamp_func, append_to_excel_func, insert_missed_record_func,
                                            excel_filename_param, ml_feedback_db_param, image_folder_param))
            thread.start()
    else:
        logging.info("No unprocessed images found. All tasks are up-to-date.")