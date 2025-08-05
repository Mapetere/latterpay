# services/registrationflow.py

from services.sessions import save_session, update_last_active, cancel_session
from services.pygwan_whatsapp import whatsapp
from services.pygwan_whatsapp import whatsapp
from services.sessions import save_session,initialize_session
from flask import jsonify
from datetime import datetime 




class RegistrationFlow:
    @staticmethod
    def start_registration(phone,msg):
        whatsapp.send_message("Registration started.\n" \
        " What's your full name?", phone)
        session = {"mode": "registration", "step": "awaiting_name", "data": {}}
        save_session(phone, session["step"], session["data"])
        return handle_name_step(phone,msg, session)

step_handlers = {}


def handle_first_message(phone, msg, session):

    update_last_active(phone)

    session["last_active"] = datetime.now()
    save_session(phone, session["step"], session["data"])


    if msg == "1":
        session["mode"] = "registration"
        session["step"] = "awaiting_name"
        save_session(phone, session["step"], session["data"])
        return RegistrationFlow.start_registration(phone)

    elif msg == "2":
        session["mode"] = "donation"
        session["step"] = "awaiting_amount"
        save_session(phone, session["step"], session["data"])
        return initialize_session(phone)
    
    elif msg.lower() == "cancel":
        cancel_session(phone)
        return jsonify({"status": "session cancelled"}), 200    
    
    elif msg != "1" or "2":
            whatsapp.send_message("❓ Please type *1* to Register or *2* to Donate.", phone)
            return jsonify({"status": "awaiting valid option"}), 200

    else: 
        if not session.get("mode"):
            whatsapp.send_message(
                "👋 You sent me a message!\n\n"
                "Welcome! What would you like to do?\n\n"
                "1️⃣ Register to Runde Rural Clinic Project\n"
                "2️⃣ Make payment\n\n"
                "Please reply with a number", phone)
            return jsonify({"status": "awaiting valid option"}), 200



    if session.get("mode") == "registration":
        return RegistrationFlow.start_registration(phone, msg)

    elif session.get("mode") == "donation":
        return whatsapp.send_message("Oops! Donation flow is not in use yet.\n"
                                        "Contact Nyasha on mapeterenyasha@gmail.com for any enquiries.", phone)




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
    if button_id == "confirm_registration":
        whatsapp.send_message("🎉 You are now registered! Thank you for using latterpay.", phone)
        cancel_session(phone)  
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
    "awaiting_message": handle_registration_message,
    "awaiting_name": handle_name_step,
    "awaiting_email": handle_email_step,
    "awaiting_area": handle_area_step,
    "awaiting_skill": handle_skill_step,
    "awaiting_confirmation": handle_confirmation_step,
    "awaiting_amount": initialize_session
}
