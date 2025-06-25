# services/donation_flow.py
from datetime import datetime
import json
import os
import time  
from paynow import Paynow
from services.recordpaymentdata import record_payment
from services.setup import send_payment_report_to_finance
from services.sessions import check_session_timeout, cancel_session, initialize_session
from services import config
from services.config import CUSTOM_TYPES_FILE, donation_types as DONATION_TYPES
from services.pygwan_whatsapp import whatsapp
from services.getdonationmenu import get_donation_menu, validate_donation_choice
import sys
import logging

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


sessions = config.sessions

step_handlers = {}

def handle_user_message(phone, msg, session):
    step = session.get("step", "name")
    handler = step_handlers.get(step)
    if handler:
        return handler(phone, msg, session)
    else:
        return handle_unknown_state(phone, msg, session)
    


def handle_unknown_state(phone, msg, session):
    whatsapp.send_message("Hmm... I got lost. Let me reset your donation flow from the last known point.", phone)
    session["step"] = "name"
    return handle_name_step(phone, msg, session)



def ask_for_payment_method(phone,msg=None,session=None):
    whatsapp.send_message(
        "*Select Payment Method:*\n"
        "1. EcoCash\n"
        "2. OneMoney\n"
        "3. ZIPIT\n"
        "4. USD Transfer\n\n"
        "_Reply with the number corresponding to your preferred method_",
        phone
    )

    if session:
        session["step"] = "payment_method" 

    return "payment_method"



def handle_payment_method_step(phone, msg, session):
    msg = msg.strip()
    payment_options = {
        "1": "EcoCash",
        "2": "OneMoney",
        "3": "ZIPIT",
        "4": "USD Transfer"
    }
    selected_method = payment_options.get(msg)
    if not selected_method:
        whatsapp.send_message(
            "❌ *Invalid Payment Method*\n"
            "Please reply with a number from the list:\n\n"
            "*1.* EcoCash\n"
            "*2.* OneMoney\n"
            "*3.* ZIPIT\n"
            "*4.* USD Transfer\n\n"
            "_Choose your preferred method_",
            phone
        )
        return "payment_method"
    

    session["data"]["payment_method"] = selected_method
    session["step"] = "payment_number"
    whatsapp.send_message(
        f"✅ *{selected_method} selected!*\n\n"
        "Please enter the payment *number* or *account* to send to.\n"
        "_Type *cancel* to exit_",
        phone
    )
    return "payment_number"



def handle_payment_number_step(phone, msg, session):
    raw = msg.strip()


    if raw.startswith("0") and len(raw) == 10: 
        formatted = "263" + raw[1:]
    elif raw.startswith("263") and len(raw) == 12:
        formatted = raw
    else:
        whatsapp.send_message("❌ Invalid number format. Use *0771234567* or *263771234567*.", phone)
        return "ok"
    
    

    session["data"]["phone"] = formatted

    try:
        amount = float(session["data"]["amount"])
    except (ValueError, TypeError):
        whatsapp.send_message("❌ Invalid amount format. Please enter a number like 5000.", phone)
        return "ok"


    method = session["data"]["payment_method"].lower()
    valid_methods = ["ecocash", "onemoney", "zipit", "usd"]
    if method == "ecocash":
        method = "ecocash"
    elif method == "onemoney":
        method = "onemoney"
    elif method == "zipit":
        method = "zipit"
    elif method == "usd transfer":
        method = "usd"

    if method not in valid_methods:
        whatsapp.send_message("❌ Unsupported payment method.", phone)
        return "ok"

    paynow = Paynow(
        "21116",
        "f6cb151e-10df-45cf-a504-d5dff25249cb",
        "https://latterpay-production.up.railway.app/payment-return",
        "https://latterpay-production.up.railway.app/payment-result"
    )

    donation_desc = session["data"]["donation_type"]

    payment = paynow.create_payment("Order", "mapeterenyasha@gmail.com")

    payment.add(donation_desc, amount)

    try:
        logger.debug(f"Using Paynow method: '{method}'")


        response = paynow.send_mobile(payment, formatted, method)

        logger.debug(f"Raw Paynow response: {response}")
        logger.debug(f"Response type: {type(response)}")
        if hasattr(response, "poll_url"):
            logger.debug(f"Poll URL: {response.poll_url}")

    except Exception as e:
        logger.warning(f"Paynow SendMobile Exception: {type(e)} - {e}")
        whatsapp.send_message("❌ Failed to send payment request. Please try again later.", phone)
        return "ok"


    if hasattr(response, "success") and response.success:
        session["poll_url"] = response.poll_url
        session["step"] = "awaiting_payment"
        whatsapp.send_message(
            "✅ Payment request sent!\n"
            "Approve it on your phone and type *check* to confirm.",
            phone
        )
    else:
        logger.warning(f"Paynow SendMobile Failed: {getattr(response, 'error', str(response))}")
        whatsapp.send_message(
            "❌ Failed to send payment request.\n"
            "Please check your number and try again or contact support.",
            phone
        )
    logger.debug(f"Session data after payment request: {json.dumps(session, indent=2, default=str)}")

    if session:
        session["step"] = "awaiting_payment" 

    return "ok"





def handle_awaiting_payment_step(phone, msg, session):
    if msg.strip().lower() != "check":
        whatsapp.send_message(
            "Type *check* to see if your payment was confirmed.\n"
            "If you haven’t authorized the payment yet, please do so on your phone.",
            phone
        )
        return "ok"

    poll_url = session.get("poll_url")
    if not poll_url:
        whatsapp.send_message("⚠️ No payment in progress.", phone)
        return "cancel_session"
    

    paynow = Paynow(
            "21116",
            "f6cb151e-10df-45cf-a504-d5dff25249cb",
            "https://latterpay-production.up.railway.app/payment-return",
            "https://latterpay-production.up.railway.app/payment-result"
        )
    


    def poll_once(paynow, poll_url):
        status = paynow.check_transaction_status(poll_url)
        return status.status

    result = poll_once(paynow, poll_url)





    if result == "paid":
        record_payment(session["data"])
        send_payment_report_to_finance()
        whatsapp.send_message("✅ Payment confirmed! Your donation has been recorded. Thank you 🙏", phone)
        del sessions[phone]
    elif result == "cancelled":
        whatsapp.send_message("⚠️ Payment was cancelled. Type *confirm* to try again.", phone)
        session["step"] = "awaiting_confirmation"
    elif result == "failed":
        whatsapp.send_message("❌ Payment failed. Please try again or use a different method.", phone)
        session["step"] = "awaiting_confirmation"
    else:
        whatsapp.send_message("⏳ Payment still processing. Please wait a minute and type *check* again.", phone)

    return "ok"


def handle_edit_command(phone, session):
    session["step"] = "editing_fields"
    session["edit_queue"] = ["name", "amount", "donation_type", "region", "note"]
    session["current_edit"] = session["edit_queue"].pop(0)
    current_value = session["data"].get(session["current_edit"], "")
    whatsapp.send_message(
        f"Let's update your details.\n\nCurrent *{session['current_edit']}*: {current_value}\nSend new value or *skip*.",
        phone
    )
    return "editing_fields"



def handle_editing_fields(phone, msg, session):
    field = session.get("current_edit")
    if not field:
        return handle_edit_command(phone, session)
    if msg.strip().lower() != "skip":
        session["data"][field] = msg.strip().title()
    if session["edit_queue"]:
        session["current_edit"] = session["edit_queue"].pop(0)
        current_value = session["data"].get(session["current_edit"], "")
        whatsapp.send_message(
            f"Current *{session['current_edit']}*: {current_value}\nSend new value or *skip*.", phone
        )
        return "editing_fields"
    

    session.pop("current_edit", None)
    session.pop("edit_queue", None)
    session["step"] = "awaiting_confirmation"
    summary = session["data"]
    whatsapp.send_message(
        "Updated payment summary:\n\n"
        f"*Name:* {summary['name']}\n*Amount:* {summary['amount']}\n*Purpose:* {summary['donation_type']}\n"
        f"*Region:* {summary['region']}\n*Note:* {summary['note']}\n\nType *confirm* or *edit*.",
        phone
    )
    return "ok"




def handle_confirmation_step(phone, msg, session):
    msg = msg.strip().lower()
    if msg == "confirm":
        session["step"] = "awaiting_user_method"
        return ask_for_payment_method(phone,msg,session)
    elif msg == "edit":
        return handle_edit_command(phone, session)
    elif msg == "cancel":
        whatsapp.send_message("❌ Donation cancelled. See you again soon!", phone)
        cancel_session(phone)
        return "ok"
    else:
        whatsapp.send_message("Invalid option. Type *confirm*, *edit*, or *cancel*.", phone)
        return "ok"

def handle_name_step(phone, msg, session):
    if phone not in sessions:
        sessions[phone] = {"step": "name", "data": {}, "last_active": datetime.now()}
        whatsapp.send_message(
            "Good day! I'm LatterPay.\nTo begin, please enter your *full name*:", phone
        )
        return "ok"
    session["data"]["name"] = msg
    session["step"] = "amount"
    whatsapp.send_message("*Amount?* Enter amount (e.g. 5000). Type *cancel* to exit.", phone)
    return "ok"

def handle_amount_step(phone, msg, session):
    try:
        amount = float(msg)
        session["data"]["amount"] = amount
        session["step"] = "donation_type"
        whatsapp.send_message(
            "*Choose donation purpose:*\n" + get_donation_menu() + "\n_Reply with the number._",
            phone
        )
    except ValueError:
        whatsapp.send_message("❗ Invalid amount. Please enter a number (e.g. 5000).", phone)
    return "ok"


def handle_donation_type_step(phone, msg, session):
    max_options = len(get_donation_menu())
    is_valid, response = validate_donation_choice(msg, max_options)
    if not is_valid:
        whatsapp.send_message(
            f"❌ Invalid selection.\n{response}\nPlease choose a valid number.", phone
        )
        return "ok"
    choice_num = int(msg)
    session["data"]["donation_type"] = DONATION_TYPES[choice_num - 1]
    session["step"] = "region"
    whatsapp.send_message("🌍 Enter your congregation name:", phone)
    return "ok"


def handle_region_step(phone, msg, session):
    session["data"]["region"] = msg
    session["step"] = "note"
    whatsapp.send_message("📝 Any additional notes to clarify your payment purpose?", phone)
    return "ok"


def handle_note_step(phone, msg, session):
    session["data"]["note"] = msg.strip()
    session["step"] = "awaiting_confirmation"
    summary = session["data"]
    whatsapp.send_message(
        f"PAYMENT DETAILS:\n\n"
        f"*Name:* {summary['name']}\n*Amount:* {summary['amount']}\n"
        f"*Purpose:* {summary['donation_type']}\n*Region:* {summary['region']}\n*Note:* {summary['note']}\n\n"
        "Type *confirm* to proceed or *edit* to change any detail.",
        phone
    )
    return "ok"

# Register handlers in the shared map
step_handlers = {
    "name": handle_name_step,
    "amount": handle_amount_step,
    "donation_type": handle_donation_type_step,
    "region": handle_region_step,
    "note": handle_note_step,
    "awaiting_confirmation": handle_confirmation_step,
    "awaiting_user_method": ask_for_payment_method,
    "payment_method": handle_payment_method_step,
    "payment_number": handle_payment_number_step,
    "awaiting_payment": handle_awaiting_payment_step,
    "editing_fields": handle_editing_fields,
}
