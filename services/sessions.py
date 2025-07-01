from services import  config
from datetime import datetime
from datetime import timedelta

from services.pygwan_whatsapp import whatsapp


def cancel_session(phone):
    """Cancel and clean up a user's session"""
    if phone in config.sessions:
        del config.sessions[phone]
    whatsapp.send_message(
        "🚫 Your donation session has been cancelled. "
        "You can start a new donation anytime by sending a message.",
        phone
    )

def check_session_timeout(phone):
    """Returns True if session expired"""
    if phone in config.sessions:
        last_active = config.sessions[phone].get("last_active")
        if last_active and (datetime.now() - last_active) > timedelta(minutes=5):
            cancel_session(phone)
            return True
    return False

def initialize_session(phone, name):
    print(f"\nCreating NEW session for {phone} ({name})")
    if phone not in config.sessions:
        config.sessions[phone] = {
            "step": "name",
            "data": {},
            "last_active": datetime.now()
        }
        print(f"Current sessions: {config.sessions}")

        whatsapp.send_message(
            f"Good day {name}! To begin, please enter *sender*'s  full name...*  ",
            phone
        )

        return "ok"