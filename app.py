from flask import Flask, request
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import os
from pygwan import WhatsApp
from datetime import datetime, timedelta
import json
import pandas as pd
from fpdf import FPDF
import tempfile
import requests


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
PAYMENTS_FILE = "donation_payment.json"

#Intialize payments file if it doesn't exist
if not os.path.exists(PAYMENTS_FILE):
    with open(PAYMENTS_FILE, 'w') as f:
        json.dump([], f)

#Daily/weekly auto-reports

def setup_scheduled_reports():
    """Configure automatic daily/weekly reports"""
    scheduler = BackgroundScheduler(daemon=True)
    
    # Daily report at 9am
    scheduler.add_job(
        send_payment_report_to_finance,
        'cron',
        day_of_week='mon-fri',
        hour=9,
        minute=0,
        args=["pdf"]  # Send PDF by default
    )
    
    # Weekly summary every Monday at 10am
    scheduler.add_job(
        lambda: send_payment_report_to_finance("excel"),  # Excel for weekly
        'cron',
        day_of_week='mon',
        hour=10,
        minute=0
    )
    
    scheduler.start()
    
    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())

#excel export option
def generate_excel_report():
    """Generate Excel report of all payments"""
    try:
        with open(PAYMENTS_FILE, 'r') as f:
            payments = json.load(f)
            
        if not payments:
            return None
            
        df = pd.DataFrame(payments)
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        excel_path = temp_file.name
        df.to_excel(excel_path, index=False)
        temp_file.close()
        
        return excel_path
        
    except Exception as e:
        print(f"Error generating Excel report: {e}")
        return None


def record_payment(payment_data):
    """Record a new payment in the payments file"""
    try:
        with open(PAYMENTS_FILE, 'r') as f:
            payments = json.load(f)
        
        payments.append({
            "name": payment_data["name"],
            "amount": float(payment_data["amount"]),
            "congregation": payment_data["region"],
            "purpose": payment_data["donation_type"],
            "date": datetime.now().isoformat(),
            "note": payment_data.get("note", "")
        })
        
        with open(PAYMENTS_FILE, 'w') as f:
            json.dump(payments, f)
        
        print("Payment recorded successfully.")
    except Exception as e:
        print(f"Error recording payment: {e}")

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


def generate_payment_report():
    """Generate a PDF report of all payments grouped by congregation"""
    try:
        with open(PAYMENTS_FILE, 'r') as f:
            payments = json.load(f)
        
        if not payments:
            return None
            
        # Create DataFrame and group by congregation
        df = pd.DataFrame(payments)
        grouped = df.groupby('congregation')
        
        # Create PDF
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        
        # Title
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, 'Donation Payments Report', 0, 1, 'C')
        pdf.ln(10)
        
        # Add date
        pdf.set_font('Arial', '', 12)
        pdf.cell(0, 10, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1)
        pdf.ln(10)
        
        # Add summary stats
        total_amount = df['amount'].sum()
        pdf.cell(0, 10, f"Total Donations: ${total_amount:,.2f}", 0, 1)
        pdf.cell(0, 10, f"Total Donors: {len(df)}", 0, 1)
        pdf.ln(15)
        
        # Add congregation sections
        for congregation, group in grouped:
            pdf.set_font('Arial', 'B', 14)
            pdf.cell(0, 10, f"Congregation: {congregation}", 0, 1)
            pdf.set_font('Arial', '', 12)
            
            # Create table header
            pdf.cell(60, 10, 'Name', 1, 0, 'L')
            pdf.cell(40, 10, 'Amount', 1, 0, 'R')
            pdf.cell(80, 10, 'Purpose', 1, 1, 'L')
            
            # Add rows
            for _, row in group.iterrows():
                pdf.cell(60, 10, row['name'], 1, 0, 'L')
                pdf.cell(40, 10, f"${row['amount']:,.2f}", 1, 0, 'R')
                pdf.cell(80, 10, row['purpose'], 1, 1, 'L')
            
            pdf.ln(5)
        
        # Save to temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_path = temp_file.name
        pdf.output(pdf_path)
        temp_file.close()
        
        return pdf_path
        
    except Exception as e:
        print(f"Error generating report: {e}")
        return None

def send_payment_report_to_finance(report_type="pdf"):
    finance_phone = os.getenv("FINANCE_PHONE")
    file_path = generate_payment_report()

    if not file_path:
        print("❌ No PDF was generated.")
        return

    send_pdf(finance_phone, file_path,"🧾 Church Donation Report")
    os.unlink(file_path)  # cleanup

        


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


def send_pdf(phone, file_path, caption):
    access_token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("PHONE_NUMBER_ID")

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/media"

    # Upload media
    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f, 'application/pdf')}
        data = {
            'messaging_product': 'whatsapp'
        }
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        response = requests.post(url, files=files, data=data, headers=headers)
        print(response.json())
        media_id = response.json().get("id")

    # Send document using media_id
    if media_id:
        send_url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "document",
            "document": {
                "id": media_id,
                "caption": caption
            }
        }
        headers['Content-Type'] = 'application/json'
        resp = requests.post(send_url, json=payload, headers=headers)
        print(resp.json())
    else:
        print("❌ Failed to upload media.")    


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
        if msg == "/admin":
            whatsapp.send_message("⚠️ You're the admin, but continuing as a donor. Type /admin to see admin commands.", phone)
            whatsapp.send_message(
                "👩🏾‍💼 *Admin Panel*\n"
                "Use the following commands:\n"
                "• /report pdf or /report excel\n"
                "• /approve <user> <duration>\n"
                "• /session — View current session state",
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
            handle_admin_approval(phone, msg)
            return "ok"

        elif msg == "/session":
            whatsapp.send_message(f"📦 Current session:\n```{json.dumps(sessions.get(phone), indent=2)}```", phone)
            return "ok"

    
    print(f"Message from {name} ({phone}): {msg}")

    # Check for timeout first
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

        record_payment(summary)  # Record the payment
        confirm_message = (
            f"✅ *Thank you {summary['name']}!*\n\n"
            f"💰 *Amount:* {summary['amount']}\n"
            f"📌 *Type:* {summary['donation_type']}\n"
            f"🌍 *Congregation:* {summary['region']}\n"
            f"📝 *Note:* {summary['note']}\n\n"
            "_We will now send a payment link and notify the finance director after payment is complete._"
        )

        whatsapp.send_message(confirm_message, phone)
        send_payment_report_to_finance("pdf")

        del sessions[phone]  # Clear the session

    return "ok"

if __name__ == "__main__":
        # Clean up expired types on startup
        cleanup_expired_donation_types()
        setup_scheduled_reports()
        app.run(port=5000, debug=True)
        