import logging
import os # จำเป็นสำหรับ FileHandler

def setup_logging(log_filename="bot_activity.log"):
    """
    Sets up logging to output to both console and a specified log file.
    This function should be called once at the start of the application.
    """
    # ตรวจสอบว่ามี handlers ที่ถูกตั้งค่าไว้แล้วหรือไม่ เพื่อป้องกันการเพิ่มซ้ำ
    # logging.root.handlers จะไม่ว่างเปล่าถ้ามีการเรียก logging.basicConfig ไปแล้ว
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'), # เขียนลงไฟล์ (กำหนด encoding)
                logging.StreamHandler()            # แสดงใน Console
            ]
        )
    logging.info(f"Logging configured. Outputting to console and '{log_filename}'.")