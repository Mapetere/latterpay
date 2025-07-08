# services/registrationflow.py

from services.sessions import save_session, update_last_active, cancel_session
from services.pygwan_whatsapp import whatsapp
from services.pygwan_whatsapp import whatsapp
from services.sessions import save_session

class RegistrationFlow:
    @staticmethod
    def start_registration(phone):
        whatsapp.send_message("📝 Registration started.\n" \
        " What's your full name?", phone)
        session = {"mode": "registration", "step": "awaiting_name", "data": {}}
        save_session(phone, session["step"], session["data"])

step_handlers = {}

def handle_registration_message(phone, msg, session):
    
    update_last_active(phone)
    step = session.get("step", "awaiting_name")
    handler = step_handlers.get(step)
    if handler:
        return handler(phone, msg, session)
    else:
        whatsapp.send_message("Oops! Something went wrong in registration. Let's start again.", phone)
        session["step"] = "awaiting_name"
        save_session(phone, session["step"], session["data"])
        return handle_name_step(phone, msg, session)


def handle_button_response(button_id, phone):
    # Example: final confirm, skill type selection, etc.
    if button_id == "confirm_registration":
        whatsapp.send_message("🎉 You are now registered! Thank you.", phone)
        cancel_session(phone)  # Clear the session
        return True
    return False

def handle_name_step(phone, msg, session):
    session["data"]["name"] = msg.strip().title()
    session["step"] = "awaiting_email"
    save_session(phone, session["step"], session["data"])
    whatsapp.send_message("Great! Now, please enter your *email address*.", phone)
    return "ok"

def handle_email_step(phone, msg, session):
    session["data"]["email"] = msg.strip()
    session["step"] = "awaiting_area"
    save_session(phone, session["step"], session["data"])
    whatsapp.send_message("Enter your *area of residence* (e.g., Harare).", phone)
    return "ok"

def handle_area_step(phone, msg, session):
    session["data"]["area"] = msg.strip().title()
    session["step"] = "awaiting_skill"
    save_session(phone, session["step"], session["data"])
    whatsapp.send_message("Please enter your *main skill* or profession.", phone)
    return "ok"

def handle_skill_step(phone, msg, session):
    session["data"]["skill"] = msg.strip().title()
    session["step"] = "awaiting_confirmation"
    save_session(phone, session["step"], session["data"])

    data = session["data"]
    whatsapp.send_message(
        f"🔍 *Review your registration details:*\n\n"
        f"*Name:* {data.get('name')}\n"
        f"*Email:* {data.get('email')}\n"
        f"*Area:* {data.get('area')}\n"
        f"*Skill:* {data.get('skill')}\n\n"
        "Type *confirm* to finish or *cancel* to abort.",
        phone
    )
    return "ok"

def handle_confirmation_step(phone, msg, session):
    msg = msg.strip().lower()
    if msg == "confirm":
        from services.sessions import save_registration_to_db
        save_registration_to_db(phone, **session["data"])
        whatsapp.send_message("🎉 Registration complete. Thank you for registering!", phone)
        cancel_session(phone)
    elif msg == "cancel":
        whatsapp.send_message("🚫 Registration cancelled. You can start again anytime.", phone)
        cancel_session(phone)
    else:
        whatsapp.send_message("Please type *confirm* or *cancel*.", phone)
    return "ok"

step_handlers = {
    "awaiting_name": handle_name_step,
    "awaiting_email": handle_email_step,
    "awaiting_area": handle_area_step,
    "awaiting_skill": handle_skill_step,
    "awaiting_confirmation": handle_confirmation_step
}
