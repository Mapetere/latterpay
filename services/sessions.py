
from datetime import datetime
from datetime import timedelta
from services.userstore import is_known_user, add_known_user
from services.pygwan_whatsapp import whatsapp
from datetime import datetime
import json
import sqlite3

from services.pygwan_whatsapp import whatsapp


def cancel_session(phone):
    """Cancel and clean up a user's session (DB version)."""
    session = load_session(phone)
    if session:
        delete_session(phone)

    whatsapp.send_message(
        "🚫 Your donation session has been cancelled. "
        "You can start a new donation anytime by sending a message.",
        phone
    )


def check_session_timeout(phone):
    """Checks if the session is inactive for more than 5 minutes."""
    session = load_session(phone)
    if session:
        last_active = session.get("last_active")
        if last_active and (datetime.now() - datetime.fromisoformat(last_active)) > timedelta(minutes=5):
            cancel_session(phone)
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
            "👋 Hello! I’m *LatterPay*, your trusted donation assistant.\n"
            "Let’s get started. Please enter the *full name* of the person making the payment.",
            phone
        )
        add_known_user(phone)
    else:
        whatsapp.send_message(
            "🔄 Welcome back to *LatterPay*!\n"
            "Back for another donation? Please enter the *name of the person* making this payment.",
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



