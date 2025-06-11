from flask import Flask, request
from datetime import datetime
import os
from flask import request
from paynow import Paynow
from datetime import datetime
from services.adminservice import handle_admin_command
import json
import os
from dotenv import load_dotenv
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, sessions, PAYMENTS_FILE, donation_types as DONATION_TYPES
from services.sessions import (
    check_session_timeout,
    cancel_session,
    initialize_session
)


load_dotenv()

app = Flask(__name__)


@app.route("/payment-return")
def payment_return():
    return "✅ Payment process complete! You may close this tab."

@app.route("/payment-result", methods=["POST", "GET"])
def payment_result():
    # Parse result from Paynow (this gets called by Paynow server)
    from paynow import Paynow  # assuming you're using the `paynow` package
    paynow = Paynow(
        os.getenv("PAYNOW_ID"),
        os.getenv("PAYNOW_KEY"),
        "h https://418e-197-221-251-66.ngrok-free.app/return",
        " https://418e-197-221-251-66.ngrok-free.app/payment-result"
    )

    # Here you check the status if needed
    print("✅ Paynow callback received!")
    return "Payment result processed", 200


@app.route("/flow-submission", methods=["POST"])
def flow_submission():
    try:
        data = request.get_json()
        print("[FLOW SUBMISSION]  Received:", json.dumps(data, indent=2))

        # Assuming WhatsApp Meta sends your flow submission here
        # You should adapt this to match your actual payload shape
        form_data = data.get("form_data", {})

        # Extract fields
        full_name = form_data.get("full_name")
        purpose = form_data.get("purpose")
        amount = form_data.get("amount")
        congregation = form_data.get("congregation")
        notes = form_data.get("notes", "")

        if not all([full_name, purpose, amount, congregation]):
            return "Missing required fields", 400

        # Save to file
        payment_record = {
            "name": full_name,
            "amount": float(amount),
            "purpose": purpose,
            "congregation": congregation,
            "note": notes,
            "timestamp": datetime.now().isoformat()
        }

        with open("donation_payment.json", "r+") as f:
            try:
                records = json.load(f)
            except json.JSONDecodeError:
                records = []

            records.append(payment_record)
            f.seek(0)
            json.dump(records, f, indent=2)
            f.truncate()

        # Generate Paynow payment
        paynow = Paynow(
            integration_id=os.getenv("PAYNOW_ID"),
            integration_key=os.getenv("PAYNOW_KEY"),
            return_url=" https://418e-197-221-251-66.ngrok-free.app/payment-return",
            result_url=" https://418e-197-221-251-66.ngrok-free.app/payment-result"
        )

        payment = paynow.create_payment(full_name, "placeholder@email.com")  # Email can be fake or real
        payment.add(purpose, amount)

        response = paynow.send(payment)

        if response.success:
            payment_link = response.redirect_url

            # Respond with payment link
            return {
                "status": "success",
                "message": f"✅ Donation recorded. Please complete payment here: {payment_link}",
                "payment_link": payment_link
            }, 200
        else:
            return {
                "status": "fail",
                "message": "❌ Could not initiate payment. Try again later."
            }, 500

    except Exception as e:
        print(f"❌ Flow submission error: {e}")
        return "Internal Server Error", 500


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
        return handle_admin_command(phone, msg) or "ok"

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
        
    
   
if __name__ == "__main__":
    from services.cleanup import cleanup_expired_donation_types
    from services.setup import setup_scheduled_reports


    cleanup_expired_donation_types()
    setup_scheduled_reports()
    app.run(port=5000, debug=True)
