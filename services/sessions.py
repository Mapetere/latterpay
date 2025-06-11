from services import  config
from datetime import datetime
from datetime import timedelta
from services.pygwan_whatsapp import whatsapp

sessions = config.sessions


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
    if phone in sessions:
        elapsed = datetime.now() - sessions[phone]["last_active"]
        if elapsed > timedelta(minutes=15):
            whatsapp.send_message(
                "⌛ Your session has expired. Please start over.",
                phone
            )
            del sessions[phone]
            return True
    return False



def initialize_session(phone, name):
    phone = whatsapp.get_mobile(phone)
    if phone not in sessions:
        sessions[phone] = {
            "step": "name",
            "data": {},
            "last_active": datetime.now()
        }
        whatsapp.send_message(
            f"Good day {name}!\n"
            "I'm latterpay, here to assist you with your ecocash payments to Latter Rain Church(Zimbabwe).\n\n"
            "To begin , please enter *payee full name:*  ",
            phone
        )

        return "ok"