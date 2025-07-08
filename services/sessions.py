
from datetime import datetime
from datetime import timedelta
from services.userstore import is_known_user, add_known_user
from services.pygwan_whatsapp import whatsapp
from datetime import datetime
from services.whatsappservice import WhatsAppService
import json
import sqlite3
from datetime import datetime, timedelta
import threading
import time
from services.pygwan_whatsapp import whatsapp

import time

from services.pygwan_whatsapp import whatsapp

last_active = datetime.now()



def get_all_sessions():
    conn = sqlite3.connect("botdata.db")
    cursor = conn.cursor()
    cursor.execute("SELECT phone, step, data, last_active FROM sessions")
    rows = cursor.fetchall()
    conn.close()

    sessions = []
    for phone, step, data_json, last_active in rows:
        sessions.append({
            "phone": phone,
            "step": step,
            "data": json.loads(data_json),
            "last_active": datetime.fromisoformat(last_active)
        })
    return sessions



def monitor_sessions():
    def run_monitor():
        while True:
            try:
                sessions = get_all_sessions()
                now = datetime.now()

                for session in sessions:
                    phone = session["phone"]
                    last_active = session["last_active"]
                    warned = session.get("warned", 0)

                    minutes_inactive = (now - last_active).total_seconds() / 60

                    # Warn only once around ~4m50s
                    if 4 < minutes_inactive < 5 and not warned:
                        whatsapp.send_message(
                            "⚠️ Just a heads-up , your session will expire in a minute.\n\n"
                            "_Reply with any message to keep me active_.",
                            phone
                        )
                        mark_warned(phone)  

                    elif minutes_inactive >= 5:
                        cancel_session(phone)

                time.sleep(60)

            except Exception as e:
                print(f"[MONITOR ERROR] {e}")
                time.sleep(60)

    thread = threading.Thread(target=run_monitor, daemon=True)
    thread.start()


def mark_warned(phone):
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET warned = 1 WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


#This will come in handy when I have to update the session's last_active value
def update_last_active(phone):
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions
        SET last_active = ?, warned = 0
        WHERE phone = ?
    """, (datetime.now(), phone))
    conn.commit()
    conn.close()



def cancel_session(phone):
    """Cancel and clean up a user's session (DB version)."""
    session = load_session(phone)
    if session:
        delete_session(phone)

    whatsapp.send_message(
        "🚫 Your donation session has been cancelled.\n\n "
        "_You can start a new donation anytime by sending a message._",
        phone
    )


def check_session_timeout(phone):
    """Checks if the session is inactive for more than 5 minutes."""
    session = load_session(phone)
    if session:
        last_active = session.get("last_active")
        if last_active and (datetime.now() - datetime.fromisoformat(last_active)) > timedelta(minutes=5):
            delete_session(phone)
            whatsapp.send_message(
               "Opps, your session has timed out due to inactivity. "
               "Please start a new donation session by sending a message.",
                phone 
            )
            return True
    return False


def initialize_session(phone, name="there"):
    print(f"\nCreating NEW session for {phone} ({name})")

    # Create new session object
    session_data = {
        "step": "name",
        "data": {},
        "last_active": datetime.now().isoformat()
    }

    save_session(phone, session_data["step"], session_data["data"])

    if not is_known_user(phone):
        whatsapp.send_message(
            " Let’s get started. Please enter the *full name* of the person making the payment.",
            phone
        )
        add_known_user(phone)
    else:
        whatsapp.send_message(
            "Welcome back! Please enter the *name of the person* making this payment.",
            phone
        )

    return "ok"



DB_PATH = "botdata.db" 

def load_session(phone):
    conn = sqlite3.connect("botdata.db")
    cursor = conn.cursor()

    cursor.execute("SELECT step, data FROM sessions WHERE phone=?", (phone,))
    result = cursor.fetchone()
    conn.close()

    if result:
        step, data_json = result
        return {
            "step": step,
            "data": json.loads(data_json)
        }
    return None


def delete_session(phone):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE phone=?", (phone,))
    conn.commit()
    conn.close()




def save_session(phone, step, data):
    conn = sqlite3.connect("botdata.db")
    cursor = conn.cursor()

    session_json = json.dumps(data)
    now = datetime.now().isoformat()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            phone TEXT PRIMARY KEY,
            step TEXT,
            data TEXT,
            last_active TIMESTAMP
        )
    """)

    cursor.execute("SELECT phone FROM sessions WHERE phone=?", (phone,))
    exists = cursor.fetchone()

    if exists:
        cursor.execute("UPDATE sessions SET step=?, data=?, last_active=? WHERE phone=?",
                       (step, session_json, now, phone))
    else:
        cursor.execute("INSERT INTO sessions (phone, step, data, last_active) VALUES (?, ?, ?, ?)",
                       (phone, step, session_json, now))

    conn.commit()
    conn.close()





def get_user_step(phone):
    conn = sqlite3.connect("botdata.db")
    cursor = conn.cursor()
    cursor.execute("SELECT step FROM sessions WHERE phone = ?", (phone,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def update_user_step(phone, step):
    conn = sqlite3.connect("botdata.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sessions (phone, step, last_active)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(phone) DO UPDATE SET step=excluded.step, last_active=CURRENT_TIMESTAMP
    """, (phone, step))
    conn.commit()
    conn.close()


import json


def update_session_data(phone, key, value):
    conn = sqlite3.connect("botdata.db")
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM sessions WHERE phone = ?", (phone,))
    result = cursor.fetchone()
    existing_data = json.loads(result[0]) if result and result[0] else {}

    existing_data[key] = value
    updated_data = json.dumps(existing_data)

    cursor.execute("UPDATE sessions SET data = ?, last_active = CURRENT_TIMESTAMP WHERE phone = ?", (updated_data, phone))
    conn.commit()
    conn.close()


# Add these functions to your existing sessions.py

def get_user_registration(phone):
    """Get complete registration data for a user"""
    session = load_session(phone)
    if not session:
        return None
    return session.get("data", {})

def save_registration_to_db(phone, **data):
    """Save registration data to permanent storage"""

    
    conn = sqlite3.connect("botdata.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO registrations 
        (phone, name, surname, email, skill, area, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (phone, data.get('name'), data.get('surname'), 
         data.get('email'), data.get('skill'), data.get('area'), 
         datetime.now()))
    conn.commit()
    conn.close()