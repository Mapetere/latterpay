# services/donation_flow.py
from datetime import datetime
import json
from services import config
from services.config import CUSTOM_TYPES_FILE, donation_types as DONATION_TYPES
from services.recordpaymentdata import record_payment
from services.setup import send_payment_report_to_finance
from services.pygwan_whatsapp import whatsapp
from services.getdonationmenu import get_donation_menu, validate_donation_choice

sessions = config.sessions

def handle_incoming_message(phone, msg):
    if phone not in sessions:
        sessions[phone] = {
            "step": "name",
            "data": {}
        }
        whatsapp.send_message("👋🏾 Hello! What is your name?", phone)
        return


def handle_name_step(phone, msg, session):
    
    if phone not in sessions:
        sessions[phone] = {
            "step": "name",
            "data": {},
            "last_active": datetime.now()
        }
        whatsapp.send_message(
            f"Good day!\n"
            "I'm latterpay, here to assist you with your ecocash payments to Latter Rain Church(Zimbabwe).\n\n"
            "To begin , please enter *payee full name:*  ",
            phone
        )
    """Process name input and move to amount step"""
    session["data"]["name"] = msg
    session["step"] = "amount"
    whatsapp.send_message(
        "💰 *How much would you like to donate?*\n"
        "Enter amount (e.g. 5000)\n\n"
        "_Type *cancel* to exit_",
        phone
    )
    return "ok"

def handle_amount_step(phone, msg, session):
    """Validate amount and move to donation type selection"""
    try:
        # Validate it's a number
        amount = float(msg)
        session["data"]["amount"] = amount
        session["step"] = "donation_type"
        
        whatsapp.send_message(
            "🙏🏾 *Please choose the purpose of your donation:*\n\n"
            f"{get_donation_menu()}\n\n"
            "_Reply with the number (1-4)_\n"
            "_Type *cancel* to exit_",
            phone
        )
    except ValueError:
        whatsapp.send_message(
            "❗*Invalid Amount*\n"
            "Please enter a valid number (e.g. 5000)\n\n"
            "_Type *cancel* to exit_",
            phone
        )
    return "ok"

def handle_donation_type_step(phone, msg, session):
    """Process donation type selection"""
    menu = get_donation_menu()
    max_options = len(menu)

    # Check for cancellation first
    if msg.lower() == "cancel":
        from services.sessions import cancel_session
        cancel_session(phone)
        return "ok"
    
    # Validate selection
    is_valid, response = validate_donation_choice(msg, max_options)

    if not is_valid:
        whatsapp.send_message(
            f"❌ *Invalid Selection*\n"
            f"{response}"
            f"Please choose:\n" + 
            "\n".join(menu) +
            "\n\n_Tap a number or type *cancel*_",
            phone
        )
        return "ok"
    
    choice_num = response 

    # Handle different selection types
    if choice_num == 4:  # Other
        session["step"] = "other_donation_details"
        whatsapp.send_message(
            "✏️ *New Donation Purpose*\n"
            "Describe what this donation is for:\n\n"
            "_Example: \"Building Fund\" or \"Pastoral Support\"_\n"
            "_Type *cancel* to go back_",
            phone
        )
    elif choice_num <= 3:  # Standard types
        session["data"]["donation_type"] = DONATION_TYPES[choice_num-1]
        session["step"] = "region"
        whatsapp.send_message(
            "🌍 *Congregation Name*:\n"
            "Please share your congregation\n\n"
            "_Type *cancel* to exit_",
            phone
        )
    else:  # Custom types (5+)
        with open(CUSTOM_TYPES_FILE, 'r') as f:
            custom_types = json.load(f)
        custom_type = custom_types[choice_num-5]
        session["data"]["donation_type"] = custom_type["description"]
        session["step"] = "region"
        whatsapp.send_message(
            "🌍 *Congregation Name*:\n"
            "Please share your congregation\n\n"
            "_Type *cancel* to exit_",
            phone
        )
    return "ok"



def handle_region_step(phone, msg, session):
    """Process congregation input"""
    session["data"]["region"] = msg
    session["step"] = "note"
    whatsapp.send_message(
        "📝 *Additional Notes*:\n"
        "Any extra notes for the finance director?\n\n"
        "_Type *cancel* to exit_",
        phone
    )
    return "ok"

def handle_other(phone, msg, session):
    """Process custom donation description"""
    session["data"]["donation_type"] = f"Other: {msg}"
    session["data"]["custom_donation_request"] = msg
    session["step"] = "region"
    
    from services.notifications import notify_admin_for_approval
    notify_admin_for_approval(phone, msg)
    
    whatsapp.send_message(
        "🌍 *Congregation Name*:\n"
        "Please share your congregation\n\n"
        "_Note: Your custom donation type has been submitted for approval._",
        phone
    )
    return "ok"

def handle_note_step(phone, msg, session):
    """Finalize donation and send confirmation"""
    session["data"]["note"] = msg
    summary = session["data"]
    
    # Record payment
    record_payment(summary)
    
    # Send confirmation
    confirm_message = (
        f"✅ *Thank you {summary['name']}!*\n\n"
        f"💰 *Amount:* {summary['amount']}\n"
        f"📌 *Purpose:* {summary['donation_type']}\n"
        f"🌍 *Congregation:* {summary['region']}\n"
        f"📝 *Note:* {summary['note']}\n\n"
        "We will process your donation shortly."
    )
    whatsapp.send_message(confirm_message, phone)
    
    # Send report to finance
    send_payment_report_to_finance()
    
    # Clear session
    del sessions[phone]
    return "ok"
