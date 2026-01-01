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
from services.config import donation_types as DONATION_TYPES
from services.pygwan_whatsapp import whatsapp
from services.getdonationmenu import get_donation_menu, validate_donation_choice
from services.adminservice import AdminService
from services.sessions import delete_session, load_session,save_session
from decimal import Decimal, InvalidOperation
from services.sessions import (
    load_session, initialize_session, save_session,
     update_last_active
)
from services.config import admin_phone
from services.setup import send_payment_report_to_finance
from services.pygwan_whatsapp import whatsapp
from services.userstore import add_known_user, is_known_user

import sys
import logging

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


step_handlers = {}






def handle_user_message(phone, msg, session):
    
    update_last_active(phone)
    session = load_session(phone)
    if phone == admin_phone:
        return handle_admin_user(phone, msg, session)

    
    if not session:
        return initialize_session(phone)

    step = session.get("step", "name")
    handler = step_handlers.get(step)
    save_session(phone, step, session.get("data", {}))


   
    if handler:
        return handler(phone, msg, session)
    else:
        return handle_unknown_state(phone, msg, session)

    



def handle_unknown_state(phone, msg, session):
    whatsapp.send_message("Hmm... I got lost. I'm sorry you session will have to restart", phone)
    if session:
        cancel_session(phone)
    save_session(phone, session["step"], session["data"])

    return handle_name_step(phone, msg, session)



def handle_admin_user(phone, msg, session):
    known = is_known_user(phone)
    is_command = msg.startswith("/")

    if is_command:
        return handle_admin_command(phone, msg)

   
    if not known:
        whatsapp.send_message(" *Hello Admin!* You’re registered as an admin, but continuing as a donor.", phone)
        add_known_user(phone)
        return initialize_session(phone)

   
    if not session:
        whatsapp.send_message("👋🏽 Welcome back, *Admin*! Let’s continue your donation journey.", phone)
        return initialize_session(phone)

    
    step = session.get("step", "name")
    handler = step_handlers.get(step)
    save_session(phone, step, session.get("data", {}))
    if handler:
        return handler(phone, msg, session)
    else:
        return handle_unknown_state(phone, msg, session)



def handle_admin_command(phone, msg):
    msg = msg.strip().lower()
    if msg == "/admin":
        whatsapp.send_message(
            "👩🏾‍💼 *Admin Panel*\n\n"
            "Use the following commands:\n"
            "• /report pdf   (_Download payment report in PDF_)\n"
            "• /report excel (_Download payment report in Excel_)\n"
            "• /approve [txn_id]\n"
            "• /session [user_phone]",
            phone
        )
        return "ok"

    elif msg == "/report pdf":
        send_payment_report_to_finance("pdf")
        whatsapp.send_message("✅ PDF report sent to finance.", phone)
        return "ok"

    elif msg == "/report excel":
        send_payment_report_to_finance("excel")
        whatsapp.send_message("✅ Excel report sent to finance.", phone)
        return "ok"

    elif msg.startswith("/approve") or msg.startswith("/session"):
        AdminService.handle_approval_command(phone, msg)
        return "ok"

    else:
        whatsapp.send_message("❌ Unknown command. Type `/admin` to see available commands.", phone)
        return "ok"





def ask_for_payment_method(phone,msg=None,session=None):
    whatsapp.send_message(
        "*Select Payment Method:*\n"
        "1. EcoCash\n"
        "2. OneMoney\n"
        "3. Telecash\n"
        "4. USD Transfer\n\n"
        "_Reply with the number corresponding to your preferred method_",
        phone
    )

    if session:
        session["step"] = "payment_method" 
        save_session(phone, session["step"], session["data"])

    return "payment_method"




def handle_payment_method_step(phone, msg, session):
    msg = msg.strip()
    payment_options = {
        "1": "EcoCash",
        "2": "OneMoney",
        "3": "TeleCash",
        "4": "USD Transfer"
    }
    selected_method = payment_options.get(msg)
    if not selected_method:
        whatsapp.send_message(
            "❌ *Invalid Payment Method*\n"
            "Please reply with a number from the list:\n\n"
            "*1.* EcoCash\n"
            "*2.* OneMoney\n"
            "*3.* TeleCash\n"
            "*4.* USD Transfer\n\n"
            "_Choose your preferred method_",
            phone
        )
        return "payment_method"
    



    session["data"]["payment_method"] = selected_method
    session["step"] = "payment_number"
    save_session(phone, session["step"], session["data"])
    whatsapp.send_message(
        f"✅ *{selected_method} selected!*\n\n"
        f"To proceed,enter the  {selected_method} number" , phone)
    return "payment_number"



def handle_payment_number_step(phone, msg, session):

    import threading
    import time

    def poll_payment_status(phone, poll_url, paynow):
        for _ in range(30):  # try for 30 * 5 sec = 150 sec max or whatever timeout you want
            status = paynow.check_transaction_status(poll_url).status
            if status in ["paid", "cancelled", "failed"]:
                # Send immediate message
                if status == "failed":
                    whatsapp.send_message("❌ Payment failed. Please try again or use a different method.", phone)
                elif status == "cancelled":
                    whatsapp.send_message("⚠️ Payment was cancelled. You can try again.", phone)
                elif status == "paid":
                    whatsapp.send_message("✅ Payment was successful!\n" \
                    "Your payment has been recorded. Thank you for using latterpay",phone)

                break
            time.sleep(5)  # wait before checking again

    raw = msg.strip()

    
    if raw.startswith("0") and len(raw) == 10:
        formatted = "263" + raw[1:]
    elif raw.startswith("263") and len(raw) == 12:
        formatted = raw
    else:
        whatsapp.send_message("❌ Invalid number format. Use *0771234567* or *263771234567*.", phone)
        return "ok"

    session["data"]["phone"] = formatted
    save_session(phone, session["step"], session["data"])

    
    try:
        amount = float(session["data"]["amount"])
    except (ValueError, TypeError):
        whatsapp.send_message("❌ Invalid amount format. Please enter a number (e.g. 70).", phone)
        return "ok"

   
    method = session["data"]["payment_method"].lower()
    method_map = {
        "ecocash": "ecocash",
        "onemoney": "onemoney",
        "telecash": "zipit",
        "usd transfer": "usd"
    }

    paynow_method = method_map.get(method)
    if not paynow_method:
        whatsapp.send_message("❌ Unsupported payment method.", phone)
        return "ok"

    
    currency = session["data"].get("currency", "ZWG")
    if currency == "USD":
        paynow = Paynow(
                "21116",
                "f6cb151e-10df-45cf-a504-d5dff25249cb",
                "https://latterpay-production.up.railway.app/payment-return",
                "https://latterpay-production.up.railway.app/payment-result"

        )
    else:
       paynow = Paynow(
                "21227",
                "c77acfad-18b5-4e24-a94d-23e8ba122302",
                "https://latterpay-production.up.railway.app/payment-return",
                "https://latterpay-production.up.railway.app/payment-result"
            )    
    
    donation_desc = session["data"].get("donation_type", "Donation")
    payment = paynow.create_payment("Order", "mapeterenyasha@gmail.com")
    payment.add(donation_desc, amount)

    try:
        logger.debug(f"Sending payment using Paynow method: '{paynow_method}'")
        response = paynow.send_mobile(payment, formatted, paynow_method)
        logger.debug(f" Paynow response: {response}")

        if isinstance(response, str):
            logger.warning(f"Unexpected string response: {response}")
            whatsapp.send_message("❌ Payment request failed. Please try again.", phone)
            return "ok"

        if hasattr(response, "success") and response.success:
            poll_url = response.poll_url
            session["poll_url"] = poll_url
            
            save_session(phone, session["step"], session["data"])
            whatsapp.send_message(
                "✅ Payment request sent!\n"
                "Approve the payment on your phone and type *check* to confirm.",
                phone
            )
            
            threading.Thread(target=poll_payment_status, args=(phone, poll_url, paynow)).start()

        else:
            error_msg = getattr(response, 'error', 'Unknown error')
            logger.warning(f"❌ Paynow send_mobile failed: {error_msg}")
            whatsapp.send_message(
                "❌ Failed to send payment request.\n"
                "Please check your number and try again or contact support.",
                phone
            )

    except Exception as e:
        logger.exception(f"🔥 Exception during Paynow payment: {e}")
        whatsapp.send_message("❌ Payment error. Please try again later.", phone)

   





    def poll_once(paynow, poll_url):
        status = paynow.check_transaction_status(poll_url)
        return status.status

    result = poll_once(paynow, poll_url)


    if result == "paid":
        record_payment(session["data"])
        send_payment_report_to_finance()
        whatsapp.send_message("✅ Payment confirmed! Your donation has been recorded. Thank you 🙏", phone)
        delete_session(phone)

    elif result == "cancelled":
        whatsapp.send_message("⚠️ Payment was cancelled. Type *confirm* to try again.", phone)
        session["step"] = "awaiting_confirmation"
        save_session(phone, session["step"], session["data"])
    elif result == "failed":
        whatsapp.send_message("❌ Payment failed. Please try again or use a different method.", phone)
        session["step"] = "awaiting_confirmation"
        save_session(phone, session["step"], session["data"])
    else:
        whatsapp.send_message("⏳ Payment still processing. Please wait a minute and type *check* again.", phone)

    return "ok"



def handle_edit_command(phone, session):
    session["step"] = "editing_fields"
    session["edit_queue"] = ["name", "region", "donation_type", "amount", "note"]
    session["current_edit"] = session["edit_queue"].pop(0)
    save_session(phone, session["step"], session["data"])
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
    save_session(phone, session["step"], session["data"])
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
        save_session(phone, session["step"], session["data"])
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
    # If they're already in a session and just sending the name
    session["data"]["name"] = msg.strip().title()
    session["step"] = "region"
    save_session(phone, session["step"], session["data"])
    whatsapp.send_message("Next step, please enter your congregation name in full...",phone)
    return "ok"




def handle_currency_step(phone, msg, session):
    currency = msg.strip()
    if currency == "1":
        session["data"]["currency"] = "USD"
    elif currency == "2":
        session["data"]["currency"] = "ZWG"
    else:
        whatsapp.send_message(
            "❌ Invalid currency selection.\n\n"
            "Choose your currency :\n1. USD\n2. ZWG", phone
        )
        return "currency"

    session["step"] = "note"
    save_session(phone, session["step"], session["data"])
    whatsapp.send_message(" Do you have any additional notes , to clarify payment purpose?", phone)

    return "ok"



def handle_amount_step(phone, msg, session):
    try:
        # Check for comma instead of dot
        if ',' in msg:
            whatsapp.send_message("❗ Please use '.' instead of ',' for decimal values.", phone)
            return "ok"

        amount = float(msg)
        dec = Decimal(msg)
        decimal_places = -dec.as_tuple().exponent

        if decimal_places not in [0, 1, 2]:
            whatsapp.send_message("❗ Please enter amount with 0, 1 or 2 decimal places only (e.g. 40, 40.0, or 40.00).", phone)
            return "ok"

        # Check for zero or negative amount
        if amount <= 0:
            whatsapp.send_message(
                "❗ *Invalid Amount*\n\n"
                "Amount must be greater than zero.\n"
                "Please enter a valid amount (e.g. 50).",
                phone
            )
            return "ok"

        if amount > 480:
            whatsapp.send_message("❗ Maximum amount is 480. Please enter a value that is less or equal to 480.", phone)
            return "ok"

        session["data"]["amount"] = amount
        session["step"] = "currency"
        save_session(phone, session["step"], session["data"])
        whatsapp.send_message(
            "*Choose your preferred currency:*\n"
            "1. USD\n"
            "2. ZWG", phone
        )

    except (ValueError, InvalidOperation):
        whatsapp.send_message("❗ Invalid amount. Please enter a number (e.g. 50).", phone)

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
    session["step"] = "amount"
    save_session(phone, session["step"], session["data"])
    whatsapp.send_message(
        "*Please enter the amount*( e.g 40)\n\n" 
        "Please note: Maximum amount per transaction is 480.",
        phone
    )
    return "ok"




def normalize_congregation_name(name: str) -> str:
    """
    Normalize congregation/region name by:
    - Removing common suffixes like 'congregation', 'church', 'assembly'
    - Standardizing capitalization
    - Removing extra whitespace
    """
    if not name:
        return name
    
    # Convert to title case and strip
    normalized = name.strip().title()
    
    # Remove common suffixes (case-insensitive)
    suffixes_to_remove = [
        ' Congregation', ' Church', ' Assembly', ' Chapel',
        ' Parish', ' Ward', ' Branch', ' Zone', ' District'
    ]
    for suffix in suffixes_to_remove:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)].strip()
    
    # Remove leading "The "
    if normalized.startswith('The '):
        normalized = normalized[4:]
    
    return normalized


def handle_region_step(phone, msg, session):
    # Normalize the congregation name
    normalized_region = normalize_congregation_name(msg)
    session["data"]["region"] = normalized_region
    session["step"] = "donation_type"
    save_session(phone, session["step"], session["data"])
    whatsapp.send_message(
        "*Please choose the payment purpose  :*\n" + get_donation_menu() + "\n\n _reply with a number_",
        phone
    )
    return "ok"



def handle_note_step(phone, msg, session):
    note = msg.strip()
    # Handle 'none' or 'no' as empty note
    if note.lower() in ['none', 'no', 'n/a', '-', 'nil']:
        note = 'None'
    session["data"]["note"] = note
    session["step"] = "awaiting_confirmation"
    summary = session["data"]
    save_session(phone, session["step"], session["data"])
    
    # Currency symbol
    currency = summary.get('currency', 'ZWG')
    currency_symbol = '$' if currency == 'USD' else 'ZWG '
    
    whatsapp.send_message(
        f"📋 *PAYMENT SUMMARY*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 *Name:* {summary.get('name', 'N/A')}\n"
        f"🏛️ *Congregation:* {summary.get('region', 'N/A')}\n"
        f"🎯 *Purpose:* {summary.get('donation_type', 'N/A')}\n"
        f"💰 *Amount:* {currency_symbol}{summary.get('amount', 0)}\n"
        f"📝 *Note:* {summary.get('note', 'None')}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ *Reply with:*\n"
        f"• Type *confirm* to proceed to payment\n"
        f"• Type *edit* to change any details\n"
        f"• Type *cancel* to abort\n\n"
        f"_What would you like to do?_",
        phone
    )
    return "ok"



step_handlers = {
    "name": handle_name_step,
    "amount": handle_amount_step,
    "currency": handle_currency_step, 
    "donation_type": handle_donation_type_step,
    "region": handle_region_step,
    "note": handle_note_step,
    "awaiting_confirmation": handle_confirmation_step,
    "awaiting_user_method": ask_for_payment_method,
    "payment_method": handle_payment_method_step,
    "payment_number": handle_payment_number_step,
    "editing_fields": handle_editing_fields,
}
