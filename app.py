from flask import Flask, request
from dotenv import load_dotenv
import os
from pygwan import WhatsApp
from datetime import datetime, timedelta
import json

load_dotenv()

app = Flask(__name__)

whatsapp = WhatsApp(
    token=os.getenv("WHATSAPP_TOKEN"),
    phone_number_id=os.getenv("PHONE_NUMBER_ID")
)

sessions = {}

donation_types = ["Monthly Contributions", "August Conference", "Youth Conference"]
donation_types.append("Other")

CUSTOM_TYPES_FILE = "custom_donation_types.json"

# Initialize custom donation types from file if it doesn't exist
if not os.path.exists(CUSTOM_TYPES_FILE):
    with open(CUSTOM_TYPES_FILE, 'w') as f:
        json.dump([], f)

def cancel_session(phone):
    """Cancel and clean up a user's session"""
    if phone in sessions:
        del sessions[phone]
    whatsapp.send_message(
        "🚫 Your donation session has been cancelled. "
        "You can start a new donation anytime by sending a message.",
        phone
    )

def check_session_timeout(phone):
    """Returns True if session expired"""
    if phone in sessions:
        last_active = sessions[phone].get("last_active")
        if last_active and (datetime.now() - last_active) > timedelta(minutes=15):
            cancel_session(phone)
            return True
    return False

def notify_admin_for_approval(user_phone, donation_description):
    admin_phone = os.getenv("ADMIN_PHONE")  # Add ADMIN_PHONE to your .env
    approval_msg = (
        "🆕 New Donation Type Request\n\n"
        f"From: {user_phone}\n"
        f"Request: {donation_description}\n\n"
        "To approve, reply with:\n"
        f"/approve {user_phone} [duration]\n\n"
        "Example:\n"
        f"/approve {user_phone} 1year"
    )
    whatsapp.send_message(approval_msg, admin_phone)

def handle_admin_approval(admin_phone, msg):
    if msg.lower() == "cancel":
        whatsapp.send_message("Admin command cancelled", admin_phone)
        return
    
    if msg.startswith("/approve"):
        try:
            parts = msg.split()
            user_phone = parts[1]
            duration = parts[2]
            
            # Load existing custom types
            with open(CUSTOM_TYPES_FILE, "r") as f:
                custom_types = json.load(f)
            
            # Find the pending request for this user
            user_session = sessions.get(user_phone, {})
            request_desc = user_session.get("data", {}).get("custom_donation_request")
            
            if not request_desc:
                whatsapp.send_message("❌ No pending request found for this user", admin_phone)
                return
            
            # Calculate expiration date
            if duration == "forever":
                expires = None
            elif "year" in duration:
                years = int(duration.replace("year", ""))
                expires = (datetime.now() + timedelta(days=years*365)).isoformat()
            else:
                whatsapp.send_message("❌ Invalid duration. Use like: 1year, 5years, or forever", admin_phone)
                return
            
            # Add to custom types
            new_type = {
                "description": request_desc,
                "added_by": user_phone,
                "approved_by": admin_phone,
                "approved_on": datetime.now().isoformat(),
                "expires": expires
            }
            
            custom_types.append(new_type)
            
            # Save back to file
            with open(CUSTOM_TYPES_FILE, "w") as f:
                json.dump(custom_types, f)
            
            # Notify user
            whatsapp.send_message(
                f"✅ Your donation type '{request_desc}' has been approved! "
                f"It will be available until {expires or 'forever'}.",
                user_phone
            )
            
            whatsapp.send_message("✅ Donation type approved successfully!", admin_phone)
            
        except Exception as e:
            whatsapp.send_message(f"❌ Error processing approval: {str(e)}", admin_phone)

def cleanup_expired_donation_types():
    try:
        with open(CUSTOM_TYPES_FILE, "r") as f:
            custom_types = json.load(f)
        
        # Filter out expired types
        valid_types = []
        now = datetime.now()
        
        for item in custom_types:
            if item["expires"] is None:  # Forever
                valid_types.append(item)
            else:
                expires = datetime.fromisoformat(item["expires"])
                if expires > now:
                    valid_types.append(item)
        
        # Save back if anything was removed
        if len(valid_types) < len(custom_types):
            with open(CUSTOM_TYPES_FILE, "w") as f:
                json.dump(valid_types, f)
            
    except Exception as e:
        print(f"Error cleaning up donation types: {e}")

def get_donation_menu():
    # Load standard options
    menu = [
        "1. _*Monthly Contributions*_",
        "2. _*August Conference*_",
        "3. _*Youth Conference*_",
        "4. _*Other*_ (describe new purpose)"
    ]
    
    # Load and add custom options
    try:
        with open(CUSTOM_TYPES_FILE, "r") as f:
            custom_types = json.load(f)
        
        now = datetime.now()
        for i, item in enumerate(custom_types, start=5):
            if item["expires"] is None or datetime.fromisoformat(item["expires"]) > now:
                menu.append(f"{i}. _*{item['description']}*_")
                
    except Exception as e:
        print(f"Error loading custom types: {e}")
    
    return "\n".join(menu)

def notify_finance_director(d):
    finance_phone = os.getenv("FINANCE_PHONE")  # Must be set in .env
    msg = (
        f"📥 *New Church Donation!*\n\n"
        f"🙍🏽 Name: {d['name']}\n"
        f"💵 Amount: {d['amount']}\n"
        f"📌 Purpose: {d['donation_type']}\n"
        f"🌍 Congregation: {d['region']}\n"
        f"📝 Note: {d['note']}"
    )
    whatsapp.send_message(msg, finance_phone)

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
            return request.args.get("hub.challenge")
        return "Invalid verify token", 403

    data = request.get_json()
    print(f"Received data: {data}")  # Debug log
    
    if whatsapp.is_message(data):
        phone = whatsapp.get_mobile(data)
        name = whatsapp.get_name(data)
        msg = whatsapp.get_message(data).lower().strip()  # Clean the message
        print(f"Message from {name} ({phone}): {msg}")  # Debug log

        # Check for timeout first
        if check_session_timeout(phone):
            return "ok"
        
        # Check if message is from admin
        if phone == os.getenv("ADMIN_PHONE"):
            handle_admin_approval(phone, msg)
            return "ok"
        
        # Check for cancellation
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
                    "_Example: \"Building Fund\" or \"Pastoral Support\"_\n"
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
            notify_admin_for_approval(phone, msg)
            whatsapp.send_message(
                "🌍 *Congregation Name*:\n"
                "Please share your congregation\n\n"
                "_Note: Your custom donation type has been submitted for approval._ "
                "_We'll notify you once it's approved for future use._",
                phone
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
            confirm_message = (
                f"✅ *Thank you {summary['name']}!*\n\n"
                f"💰 *Amount:* {summary['amount']}\n"
                f"📌 *Type:* {summary['donation_type']}\n"
                f"🌍 *Congregation:* {summary['region']}\n"
                f"📝 *Note:* {summary['note']}\n\n"
                "_We will now send a payment link and notify the finance director after payment is complete._"
            )
            whatsapp.send_message(confirm_message, phone)
            notify_finance_director(summary)
            del sessions[phone]  # Clear the session

    return "ok"

if __name__ == "__main__":
    # Clean up expired types on startup
    cleanup_expired_donation_types()
    app.run(port=5000, debug=True)