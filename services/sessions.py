import config  
from datetime import datetime
from datetime import timedelta

def cancel_session(phone):
    """Cancel and clean up a user's session"""
    if phone in config.sessions:
        del config.sessions[phone]
    config.whatsapp.send_message(
        "🚫 Your donation session has been cancelled. "
        "You can start a new donation anytime by sending a message.",
        phone
    )

def check_session_timeout(phone):
    """Returns True if session expired"""
    if phone in config.sessions:
        last_active = config.sessions[phone].get("last_active")
        if last_active and (datetime.now() - last_active) > timedelta(minutes=15):
            cancel_session(phone)
            return True
    return False