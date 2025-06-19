# services/donation_flow.py
from datetime import datetime
import json
from services import config
from services.config import CUSTOM_TYPES_FILE, donation_types as DONATION_TYPES
from services.pygwan_whatsapp import whatsapp
from services.getdonationmenu import get_donation_menu, validate_donation_choice

sessions = config.sessions

def handle_user_message(phone, msg, session):
    msg = msg.strip().lower()
    state = session.get("state", "awaiting_name")

    state_handlers = {
        "awaiting_name": handle_name_step,
        "awaiting_amount": handle_amount_step,
        "awaiting_donation_type": handle_donation_type_step,
        "awaiting_region": handle_region_step,
        "awaiting_note": handle_note_step,
        "awaiting_confirmation": handle_confirmation_step,
        "awaiting_edit": handle_edit_command,
        "editing_fields": handle_editing_fields,
        "awaiting_user_method": ask_for_payment_method,

    }


    
    handler = state_handlers.get(state, handle_unknown_state)
    return handler(phone, msg, session)

def handle_unknown_state(phone, msg, session):
    whatsapp.send_message("⚠️ Hmm... I got lost. Let me reset your donation flow from the last known point.", phone)
    
    # I want it to recover gracefully
    fallback_step = session.get("step", "name")
    session["step"] = fallback_step

    # I'll use  the correct handler
    return handle_user_message(phone, msg, session)



def ask_for_payment_method(phone):
    whatsapp.send_message(
        "💳 *Select Payment Method:*\n"
        "1. EcoCash\n"
        "2. OneMoney\n"
        "3. ZIPIT\n"
        "4. USD Transfer\n\n"
        "_Reply with the number corresponding to your preferred method_",
        phone
    )


def handle_edit_command(phone, session):
    session["state"] = "editing_fields"
    session["edit_queue"] = ["name", "amount", "donation_type", "region", "note"]
    session["current_edit"] = session["edit_queue"].pop(0)

    current_value = session["data"][session["current_edit"]]
    whatsapp.send_message(
        f"✏️ Let's update your details.\n\n"
        f"Current *{session['current_edit']}*: {current_value}\n"
        f"Send the new value or type *skip* to keep it.",
        phone
    )

    return "editing_fields"


def handle_editing_fields(phone, msg, session):
    field = session.get("current_edit")

    if not field:
        whatsapp.send_message("⚠️ Unexpected error. Restarting edit flow.", phone)
        return handle_edit_command(phone, session)

    if msg.strip().lower() != "skip":
        session["data"][field] = msg.strip().title()

    if session["edit_queue"]:
        session["current_edit"] = session["edit_queue"].pop(0)
        current_value = session["data"][session["current_edit"]]
        whatsapp.send_message(
            f"Current *{session['current_edit']}*: {current_value}\n"
            f"Send new value or type *skip* to keep it.",
            phone
        )
        return "editing_fields"

    
    session.pop("current_edit", None)
    session.pop("edit_queue", None)
    session["state"] = "awaiting_confirmation"

    summary = session["data"]
    whatsapp.send_message(
        "Here's your updated payment summary:\n\n"
        f"*Name:* {summary['name']}\n"
        f"*Amount:* {summary['amount']}\n"
        f"*Purpose:* {summary['donation_type']}\n"
        f"*Region:* {summary['region']}\n"
        f"*Note:* {summary['note']}\n\n"
        "Type *confirm* to proceed or *edit* to review again.",
        phone
    )

    return "awaiting_confirmation"



def handle_confirmation_step(phone, msg, session):
    if msg == "confirm":
        return ask_for_payment_method(phone)
    
    elif msg == "edit":
        return handle_edit_command(phone, session)


    elif msg == "cancel":
        whatsapp.send_message("❌ Donation cancelled. No worries, come back anytime!", phone)
        from services.sessions import cancel_session
        cancel_session(phone)

    else:
        whatsapp.send_message("Invalid option. Type *confirm*, *edit*, or *cancel*.", phone)
        return "awaiting_confirmation"
    

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
        " *How much would you like to donate?*\n"
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
            "*Please choose the purpose of your donation:*\n\n"
            f"{get_donation_menu()}\n\n"
            "_Reply with the number (1-5)_\n",
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


    """#" Handle different selection types
    if choice_num == 6:  # Other
        session["step"] = "other_donation_details"
        whatsapp.send_message(
            "✏️ *New Donation Purpose*\n"
            "Describe what this donation is for:\n\n"
            "_Example: \"Building Fund\" or \"Pastoral Support\"_\n"
            "_Type *cancel* to go back_",
            phone
        )"""
    

    if choice_num <= 5:  # Standard types
        session["data"]["donation_type"] = DONATION_TYPES[choice_num-1]
        session["step"] = "region"
        whatsapp.send_message(
            "🌍 *Congregation Name*:\n"
            "Please share your congregation\n\n"
            "_Type *cancel* to exit_",
            phone
        )

        """
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
    return "ok" """



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

    msg = msg.strip().lower()

    
    """Finalize donation and move to payment step"""
    session["data"]["note"] = msg
    session["step"]="awaiting_confirmation"

    summary = session["data"]

   
    confirm_message = (

        "PAYMENT DETAILS:\n\n"
        f"*Payee Name {summary['name']}!*\n"
        f"*Amount:* {summary['amount']}\n"
        f"*Purpose:* {summary['donation_type']}\n"
        f"*Congregation:* {summary['region']}\n"
        f"*Note:* {summary['note']}\n\n"
        
        "Kindly type *confirm* to proceed with the payment.\n"
    )

   
   
    whatsapp.send_message(confirm_message, phone)

    
    return "ok"
    


   



    



