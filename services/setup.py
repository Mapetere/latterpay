import os
from flask import request
from apscheduler.schedulers.background import BackgroundScheduler
from services.sendpdf import send_pdf
from services.generatePR import generate_payment_report 
from services.config import finance_phone
import atexit


#Daily/weekly auto-reports

def setup_scheduled_reports():
    """Configure automatic daily/weekly reports"""
    scheduler = BackgroundScheduler(daemon=True)
    
    
    # Weekly summary every Monday at 10am
    scheduler.add_job(
        lambda: send_payment_report_to_finance("excel"),  # Excel for weekly
        'cron',
        day_of_week='mon',
        hour=10,
        minute=0
    )
    
    scheduler.start()
    print("Scheduled reports setup complete.")
    scheduler.remove_all_jobs()

    atexit.register(lambda: scheduler.shutdown())

def send_payment_report_to_finance():
    try:
        # 1. Generate my PDF
        pdf_path = generate_payment_report()
        if not pdf_path:
            print(" PDF generation failed")
            return False

        # 2. Verify the PDF
        if not os.path.exists(pdf_path):
            print(f"PDF not found at {pdf_path}")
            return False

        print(f" PDF generated ({os.path.getsize(pdf_path)} bytes)")

        # 3. Send my PDF
        success = send_pdf(
            phone=finance_phone,
            file_path=pdf_path,
            caption="Donation Report"
        )

        # 4. Clean up
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)

        return success

    except Exception as e:
        print(f" Error in send_payment_report_to_finance: {e}")
        return False

PHONE_NUMBER_ID = " 666157656583239"
ACCESS_TOKEN = "EAAIrEZAia0v8BO5xHnuGXNrzsBTgqzlTkKyjFFfDll46bMGVzoXV3mJjq9NLAwsTd8RPREz6grYGD3musybZAjK1Uy46H1Q2vcVyWL2fehKUtZC6S6QwdsLWeckZBIXG4WaWbcwtbhoUI4LDy6G5WyNlow82MBBWkbtwd1mCSVEP9sIuDEhLinmug5PBLmKMXgZDZD"
PIN = "1"  
    
def register_phone_number(phone_number_id, access_token, pin):
    access_token = ACCESS_TOKEN
    url = f'https://graph.facebook.com/v22.0/{666157656583239
    }/register'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    payload = {
        "messaging_product": "whatsapp",
        "pin": pin
    }
    
    response = request.post(url, headers=headers, json=payload)
    
    print(f"Status code: {response.status_code}")
    print("Response body:")
    print(response.text)
    
    return response


""" from flask import Flask, request
from datetime import datetime
import os
import json
from dotenv import load_dotenv
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, sessions, PAYMENTS_FILE, donation_types as DONATION_TYPES
from services.sessions import (
    check_session_timeout,
    cancel_session,
    initialize_session
)
from services.donationflow import (
    handle_other,
    handle_name_step,
    handle_amount_step,
    handle_donation_type_step,
    handle_region_step,
    handle_note_step  
)
from services.adminservice import AdminService
from services.cleanup import cleanup_expired_donation_types
from services.setup import setup_scheduled_reports

load_dotenv()

app = Flask(__name__)

# Initialize data files
if not os.path.exists(CUSTOM_TYPES_FILE):
    with open(CUSTOM_TYPES_FILE, 'w') as f:
        json.dump([], f)

#Intialize payments file if it doesn't exist
if not os.path.exists(PAYMENTS_FILE):
    with open(PAYMENTS_FILE, 'w') as f:
        json.dump([], f)



@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "POST":
            print("[DEBUG] Got POST")
            print(request.get_json())
            return "ok"  # Temporarily exit early to avoid error

    if request.method == "GET":
        if request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
            return request.args.get("hub.challenge")
        return "Invalid verify token", 403
    
    print("[WEBHOOK] POST triggered")
    data = request.get_json()
    
   

    # Skip if not a message
    if not whatsapp.is_message(data):
        return "ok"
   


    phone = whatsapp.get_mobile(data)
    name = whatsapp.get_name(data)
    msg = whatsapp.get_message(data).strip()
       
   
    # Handle admin commands
    if phone == os.getenv("ADMIN_PHONE"):
        return AdminService.handle_admin_command(phone, msg) or "ok"

    # Check session timeout
    if check_session_timeout(phone):
        return "ok"

    # Handle cancellation
    if msg.lower() == "cancel":
        cancel_session(phone)
        return "ok"

    # Initialize new session
    if phone not in sessions:
        initialize_session(phone, name)
        return "ok"
    
    # Update session activity
    sessions[phone]["last_active"] = datetime.now()
    session = sessions[phone]

    # Route through session steps
    step_handlers = {
        "name": handle_name_step,
        "amount": handle_amount_step,
        "donation_type": handle_donation_type_step,
        "other_donation_details": handle_other,
        "region": handle_region_step,
        "note": handle_note_step
    }

    if session["step"] in step_handlers:
        
        return step_handlers[session["step"]](phone, msg, session)
    
    return "Invalid session step", 400

import requests



if __name__ == "__main__":
    cleanup_expired_donation_types()
    setup_scheduled_reports()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
"""