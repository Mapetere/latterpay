from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import os
from datetime import datetime, timedelta
import json
from services.pygwan_whatsapp import whatsapp
from services.config import sessions, donation_types, CUSTOM_TYPES_FILE, PAYMENTS_FILE
from services.cleanup import cleanup_expired_donation_types
from services.setup import  setup_scheduled_reports

app = Flask(__name__)


# Initialize custom donation types from file if it doesn't exist
if not os.path.exists(CUSTOM_TYPES_FILE):
    with open(CUSTOM_TYPES_FILE, 'w') as f:
        json.dump([], f)



@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
            return request.args.get("hub.challenge")
        return "Invalid verify token", 403

    print("[WEBHOOK] POST triggered")
    data = request.get_json()
    print(f"Received data: {json.dumps(data, indent=2)}")  # Better debug output
    
    if not whatsapp.is_message(data):
        return "ok"  # Not a message we care about

    phone = whatsapp.get_mobile(data)
    name = whatsapp.get_name(data)
    msg = whatsapp.get_message(data).lower().strip()

    # 🧑🏾‍💼 Admin-only commands (handle early and exit)
    if phone == os.getenv("ADMIN_PHONE"):
        # ADMIN COMMANDS HANDLING (ADD THIS SECTION)
        if msg == "/admin":
            whatsapp.send_message(
                "👩🏾‍💼 *Admin Panel*\n"
                "Use the following commands:\n"
                "• /report pdf or /report excel\n"
                "• /approve \n"
                "• /session — View current session state",
                phone
            )
            return "ok"

        elif msg == "/report pdf":
            from services.notifications import send_payment_report_to_finance
            send_payment_report_to_finance("pdf")
            whatsapp.send_message("✅ PDF report sent to finance.", phone)
            return "ok"

        elif msg == "/report excel":
            send_payment_report_to_finance("excel")
            whatsapp.send_message("✅ Excel report sent to finance.", phone)
            return "ok"

        elif msg.startswith("/approve") or msg.startswith("/session"):
            from services.notifications import handle_admin_approval
            handle_admin_approval(phone, msg)
            return "ok"

        elif msg == "/session":
            whatsapp.send_message(f"📦 Current session:\n```{json.dumps(sessions.get(phone), indent=2)}```", phone)
            return "ok"

    

    # Check for timeout first
    from services.recordpaymentdata import record_payment
    from services.sessions import check_session_timeout, cancel_session

    if check_session_timeout(phone):
        return "ok"
    
    
    # Handle regular user messages
    if msg == "cancel":
        cancel_session(phone)
        return "ok"
    
    

    # Initialize session if it doesn't exist
    if phone not in sessions:
        sessions[phone] = {
            "step": "name", 
            "data": {},
            "last_active": datetime.now()
        }
        whatsapp.send_message(
            f"Hi {name}! Welcome to the Latter Rain Church Donation Bot.\n"
            "Kindly enter your *full name*\n\n"
            "_You can type *cancel* at any time to exit._", 
            phone
        )
        return "ok"
    
    # Update activity timestamp
    sessions[phone]["last_active"] = datetime.now()
    session = sessions[phone]

    # Handle session steps
    if session["step"] == "name":
        session["data"]["name"] = msg
        session["step"] = "amount"
        whatsapp.send_message(
            "💰 *How much would you like to donate?*\n"
            "Enter amount (e.g. 5000)\n\n"
            "_Type *cancel* to exit_",
            phone
        )


    elif session["step"] == "amount":
        try:
            # Validate it's a number
            float(msg)
            session["data"]["amount"] = msg
            session["step"] = "donation_type"
            from services.getdonationmenu import get_donation_menu
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

    elif session["step"] == "donation_type":
        if msg in ["1", "2", "3"]:
            session["data"]["donation_type"] = donation_types[int(msg)-1]
            session["step"] = "region"
            whatsapp.send_message(
                "🌍 *Congregation Name*:\n"
                "Please share your congregation\n\n"
                "_Type *cancel* to exit_",
                phone
            )

        
        
        elif msg == "4":
            session["step"] = "other_donation_details"
            whatsapp.send_message(
                "✏️ *New Donation Purpose*:\n"
                "Describe what this donation is for\n\n"
                "_Example: \"Building Fund\" or \"Pastoral Support\"_\n" \
                "_Type *cancel* to exit_",
                phone
            )
        else:
            whatsapp.send_message(
                "❌ *Invalid Selection*\n"
                "Please choose:\n\n"
                f"{get_donation_menu()}\n\n"
                "_Type *cancel* to exit_",
                phone
            )

        

    elif session["step"] == "other_donation_details":
        session["data"]["donation_type"] = f"Other: {msg}"
        session["data"]["custom_donation_request"] = msg
        session["step"] = "region"
        whatsapp.send_message(
            "🌍 *Congregation Name*:\n"
            "Please share your congregation,phone"
        )

    elif session["step"] == "region":
        session["data"]["region"] = msg
        session["step"] = "note"
        whatsapp.send_message(
            "📝 *Additional Notes*:\n"
            "Any extra notes for the finance director?\n\n"
            "_Type *cancel* to exit_",
            phone
        )
        

    elif session["step"] == "note":
        session["data"]["note"] = msg
        session["step"] = "done"
        summary = session["data"]

        record_payment(summary)  # Record the payment
        confirm_message = (
            f"✅ *Thank you {summary['name']}!*\n\n"
            f"💰 *Amount:* {summary['amount']}\n"
            f"📌 *Type:* {summary['donation_type']}\n"
            f"🌍 *Congregation:* {summary['region']}\n"
            f"📝 *Note:* {summary['note']}\n\n"
            "_We will now send a payment link and notify the finance director after payment is complete._"
        )
        
        from services.setup import send_payment_report_to_finance   
        send_payment_report_to_finance("pdf")
        whatsapp.send_message(confirm_message, phone)
        

        del sessions[phone]  # Clear the session

    return "ok"

if __name__ == "__main__":
        # Clean up expired types on startup
        cleanup_expired_donation_types()
        setup_scheduled_reports()
        app.run(port=5000, debug=True)
        