import sqlite3
import logging

# Constants (เหล่านี้จะถูกกำหนดในไฟล์หลัก และเข้าถึงได้จาก global scope)
# เพื่อให้โมดูลนี้สามารถทำงานได้จริง ต้องมั่นใจว่าค่าเหล่านี้ถูกกำหนดใน main.py แล้ว
ML_FEEDBACK_DB = "ml_feedback.db" 

def initialize_sqlite_db():
    """
    Initializes the SQLite database and creates the 'missed_timestamps' table if it doesn't exist.
    """
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
    """
    Inserts a record into the 'missed_timestamps' table for images where OCR failed or was skipped.
    """
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