import logging
from datetime import datetime
from services.sessions import (
    get_user_step, update_user_step, get_user_registration,
    update_session_data, save_registration_to_db
)
from services.pygwan_whatsapp import whatsapp
from services.whatsappservice import WhatsAppService

logger = logging.getLogger(__name__)

class RegistrationFlow:
    @staticmethod
    def save_field(phone, field, value):
        """Generic method to save registration field"""
        update_session_data(phone, field, value if value.lower() != "skip" else "")

    @classmethod
    def handle_message(cls, phone_number, message, session):
        """Main handler for registration flow messages"""
        step = get_user_step(phone_number)
        logger.info(f"Registration flow - Step: {step}, Phone: {phone_number}")

        if step == "awaiting_name":
            cls.save_field(phone_number, "name", message)
            update_user_step(phone_number, "awaiting_surname")
            whatsapp.send_message(phone_number, "Thanks! What's your *surname*?")

        elif step == "awaiting_surname":
            cls.save_field(phone_number, "surname", message)
            update_user_step(phone_number, "awaiting_email")
            whatsapp.send_message(phone_number, "Awesome! What's your *email*? (Or say 'skip')")

        elif step == "awaiting_email":
            cls.save_field(phone_number, "email", message)
            update_user_step(phone_number, "awaiting_skill")
            whatsapp.send_message(phone_number, "Noted. What's your *skill*?")

        elif step == "awaiting_skill":
            cls.save_field(phone_number, "skill", message)
            update_user_step(phone_number, "awaiting_area")
            WhatsAppService.send_interactive_buttons(phone_number, "volunteer_area")

        elif step == "completed":
            whatsapp.send_message(phone_number, "✅ You are already registered!")

    @classmethod
    def handle_button_response(cls, button_id, phone_number):
        """Handle button responses specific to registration"""
        if button_id.startswith("area_"):
            area = {
                "area_carpentry": "Carpentry",
                "area_building": "Building",
                "area_software": "Software Development"
            }.get(button_id, "Unknown")

            cls.save_field(phone_number, "area", area)
            update_user_step(phone_number, "completed")

            user_data = get_user_registration(phone_number)
            save_registration_to_db(**user_data)

            whatsapp.send_message(
                phone_number,
                f"✅ Thank you {user_data['name']}! You've been registered to help with *{area}*. "
                "We'll be in touch soon. ❤️"
            )
            return True
        return False

    @classmethod
    def start_registration(cls, phone_number):
        """Initialize registration process"""
        update_user_step(phone_number, "awaiting_name")
        whatsapp.send_message(phone_number, "Great! 🏥 Let's get you registered.\nWhat's your *first name*?")