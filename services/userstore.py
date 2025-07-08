import os
import sqlite3


DB_PATH = "botdata.db"



def is_known_user(phone):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM known_users WHERE phone = ?", (phone,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_known_user(phone):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO known_users (phone) VALUES (?)", (phone,))
    conn.commit()
    conn.close()
