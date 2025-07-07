import requests
from latterpay import WHATSAPP_API_URL, headers
from services.pygwan_whatsapp import whatsapp

from services.sessions import (
    get_user_step, update_user_step, get_user_registration,
    update_session_data, save_registration_to_db, update_user_mode  
)




def save_name(phone, value): update_session_data(phone, "name", value)
def save_surname(phone, value): update_session_data(phone, "surname", value)
def save_email(phone, value): update_session_data(phone, "email", value if value.lower() != "skip" else "")
def save_skill(phone, value): update_session_data(phone, "skill", value)
def save_volunteer_area(phone, value): update_session_data(phone, "area", value)






def handleRegistrationFlow(phone_number, message):
    step = get_user_step(phone_number)

    if step == "awaiting_name":
        save_name(phone_number, message)
        update_user_step(phone_number, "awaiting_surname")
        whatsapp.send_message(phone_number, "Thanks! What's your *surname*?")

    elif step == "awaiting_surname":
        save_surname(phone_number, message)
        update_user_step(phone_number, "awaiting_email")
        whatsapp.send_message(phone_number, "Awesome! What's your *email*? (Or say 'skip')")

    elif step == "awaiting_email":
        save_email(phone_number, message)
        update_user_step(phone_number, "awaiting_skill")
        whatsapp.send_message(phone_number, "Noted. What's your *skill*?")

    elif step == "awaiting_skill":
        save_skill(phone_number, message)
        update_user_step(phone_number, "awaiting_area")
        send_volunteer_area_buttons(phone_number)

    elif step == "awaiting_area":
        # This will be handled by button reply!
        pass

    elif step == "completed":
        whatsapp.send_message(phone_number, "✅ You are already registered!")




def send_volunteer_area_buttons(phone_number):
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Choose the area you'd like to volunteer in:"
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "area_carpentry", "title": " Carpentry"}},
                    {"type": "reply", "reply": {"id": "area_building", "title": " Building"}},
                    {"type": "reply", "reply": {"id": "area_software", "title": " Software Dev"}}
                ]
            }
        }
    }
    requests.post(WHATSAPP_API_URL, headers=headers, json=payload)



def handleVolunteerArea(button_id, phone_number):
    area = {
        "area_carpentry": "Carpentry",
        "area_building": "Building",
        "area_software": "Software Development"
    }.get(button_id, "Unknown")

    save_volunteer_area(phone_number, area)
    update_user_step(phone_number, "completed")

    user_data = get_user_registration(phone_number)
    save_registration_to_db(**user_data)

    whatsapp.send_message(phone_number, f"✅ Thank you {user_data['name']}! You've been registered to help with *{area}*. We’ll be in touch soon. ❤️")



def handleUserModeSelection(button_id, phone_number):
    if button_id == "register_btn":
        update_user_mode(phone_number, "registration")
        update_user_step(phone_number, "awaiting_name")
        whatsapp.send_message(phone_number, "Great! 🏥 Let's get you registered.\nWhat's your *first name*?")
    
    elif button_id == "pay_btn":
        whatsapp.send_message(phone_number, "💳 Sorry, payment is coming soon! We'll let you know when it's ready.")
