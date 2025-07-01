from services import  config
from datetime import datetime
from datetime import timedelta
from services.userstore import is_known_user, add_known_user
from services.pygwan_whatsapp import whatsapp
from datetime import datetime
import config 

from services.config import sessions

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




def initialize_session(phone, name="there"):
    print(f"\nCreating NEW session for {phone} ({name})")

    if phone not in sessions:
        sessions[phone] = {
            "step": "name",
            "data": {},
            "last_active": datetime.now()
        }

        print(f"Current sessions: {sessions}")

        if not is_known_user(phone):
            # First time? Be formal & fabulous
            whatsapp.send_message(
                "👋 Hello! I’m *LatterPay*, your trusted donation assistant.\n"
                "Let’s get started. Please enter the *full name* of the person making the payment.",
                phone
            )
            add_known_user(phone)
        else:
            # They've been here before
            whatsapp.send_message(
                "🔄 Welcome back to *LatterPay*!\n"
                "Back for another donation? Please enter the *name of the person* making this payment.",
                phone
            )

    return "ok"
