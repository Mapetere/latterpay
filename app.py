from flask import Flask, request, jsonify
from datetime import datetime
import os
import json
from paynow import Paynow
import sys
import logging
from dotenv import load_dotenv
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, sessions, PAYMENTS_FILE
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
from services.recordpaymentdata import record_payment
from services.setup import send_payment_report_to_finance




logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()



if not os.path.exists(CUSTOM_TYPES_FILE):
    with open(CUSTOM_TYPES_FILE, 'w') as f:
        json.dump([], f)

if not os.path.exists(PAYMENTS_FILE):
    with open(PAYMENTS_FILE, 'w') as f:
        json.dump([], f)

latterpay = Flask(__name__)

def handle_awaiting_payment_step(phone, msg, session):
    if msg.strip().lower() != "done":
        whatsapp.send_message("⌛ Waiting for payment confirmation. Type *done* once you've paid.", phone)
        return "ok"

    poll_url = session.get("poll_url")
    if not poll_url:
        whatsapp.send_message("⚠️ No payment in progress. Please restart the process.", phone)
        return "ok"

    paynow = Paynow (
        integration_id=os.getenv("PAYNOW_ID"),
        integration_key=os.getenv("PAYNOW_KEY"),
        return_url=os.getenv("PAYNOW_RETURN_URL"),
        result_url=os.getenv("PAYNOW_RESULT_URL") 
        )

    status = paynow.poll_transaction(poll_url)

    if status.paid:
        
        record_payment(session["data"])
        send_payment_report_to_finance()
        whatsapp.send_message("✅ Payment confirmed! Your donation has been recorded. Thank you!", phone)

        del sessions[phone]
    else:
        whatsapp.send_message("❌ Payment not confirmed yet. Please wait a moment and try again.", phone)

    return "ok"





@latterpay.route("/")
def home():
    logger.info("Home endpoint accessed")
    return "WhatsApp Donation Service is running"


@latterpay.route("/webhook", methods=["GET", "POST"])
def webhook_debug():
    try:
        if request.method == "GET":
            verify_token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")
            expected_token = os.getenv("VERIFY_TOKEN")

            logging.info(f"Webhook verification attempt. Received: {verify_token}, Expected: {expected_token}")

            if verify_token == expected_token:
                logging.info("Webhook verified successfully!")
                return challenge, 200
            logging.error("Webhook verification failed!")
            return "Verification failed", 403

        elif request.method == "POST":
            data = None

            if request.is_json:
                data = request.get_json()

                #  Detect if message is from my bot (echo)
                if 'messages' in data['entry'][0]['changes'][0]['value']:
                    msg_data = data['entry'][0]['changes'][0]['value']['messages'][0]

                    if msg_data.get("from") == os.getenv("PHONE_NUMBER_ID"):
                        print("🔁 Echo message from bot — ignored.")
                        return "ok"

                    if msg_data.get("from") == os.getenv("WHATSAPP_BOT_NUMBER"):
                        print("🔁 Echo from bot number — ignored.")
                        return "ok"

                    if msg_data.get("type") == "text" and msg_data.get("text", {}).get("body") == "some known auto-response":
                        print("🤖 Ignoring known auto-reply echo.")
                        return "ok"

                    if msg_data.get("echo"):
                        print("🔁 Detected echo=True, ignoring...")
                        return "ok"

                    
                    print("✅ Received valid message.")
                    logging.info(f"Incoming JSON POST data: {json.dumps(data, indent=2)}")

            else:
                try:
                    raw_data = request.data.decode("utf-8")
                    logging.info(f"Incoming RAW POST data: {raw_data}")
                    data = json.loads(raw_data)

                except Exception as decode_err:
                    logging.error(f"Failed to decode raw POST data: {decode_err}")
                    return jsonify({"status": "error", "message": "Invalid raw JSON"}), 400


            if data.get("type") == "DEPLOY":
                logging.info("Received Railway deployment notification")
                return jsonify({"status": "ignored"}), 200


            if isinstance(data, dict) and data.get('type') == 'DEPLOY':
                logging.info("Received Railway deployment notification")
                return jsonify({"status": "ignored"}), 200

         
            if not isinstance(data, dict):
                logging.warning("Skipping non-dictionary data")
                return jsonify({"status": "ignored"}), 200

            
            if whatsapp.is_message(data):
                logging.info("\n=== HANDLING WHATSAPP MESSAGE ===")
                phone = whatsapp.get_mobile(data)
                name = whatsapp.get_name(data)
                msg = whatsapp.get_message(data).strip()
                logging.info(f"New message from {phone} ({name}): '{msg}'")

                if phone not in sessions:
                    logging.info(f"Initializing new session for {phone}")
                    initialize_session(phone, name)
                    return jsonify({"status": "new session started"}), 200

                if phone == os.getenv("ADMIN_PHONE"):
                    logging.info("Processing admin command")
                    return AdminService.handle_admin_command(phone, msg) or jsonify({"status": "processed"}), 200

                if check_session_timeout(phone):
                    logging.info(f"Session timeout for {phone}")
                    return jsonify({"status": "session timeout"}), 200

                if msg.lower() == "cancel":
                    logging.info(f"Cancelling session for {phone}")
                    cancel_session(phone)
                    return jsonify({"status": "session cancelled"}), 200

                sessions[phone]["last_active"] = datetime.now()
                session = sessions[phone]

                step_handlers = {
                    "name": handle_name_step,
                    "amount": handle_amount_step,
                    "donation_type": handle_donation_type_step,
                    "other_donation_details": handle_other,
                    "region": handle_region_step,
                    "note": handle_note_step,
                    "payment_method": handle_payment_method_step,
                    "awaiting_payment": handle_awaiting_payment_step
                }
                
                pending_payments = {}

                def handle_payment_method_step(phone, msg, session):
                    payment_methods = {
                        "1": "EcoCash",
                        "2": "OneMoney",
                        "3": "ZIPIT",
                        "4": "USD Transfer"
                    }

                    method = payment_methods.get(msg.strip())

                    if not method:
                        whatsapp.send_message(
                            "❌ Invalid selection.\nPlease reply with a number:\n"
                            "1. EcoCash\n2. OneMoney\n3. ZIPIT\n4. USD Transfer",
                            phone
                        )
                        return "ok"

                    session["data"]["payment_method"] = method
                    session["step"] = "awaiting_payment"

                    # 💸 Set up Paynow client
                    paynow = Paynow(
                        integration_id=os.getenv("PAYNOW_ID"),
                        integration_key=os.getenv("PAYNOW_KEY"),
                        return_url="https://latterpay-production.app/payment-return",
                        result_url="https://latterpay-production.app/payment-result"
                    )

                    d = session["data"]
                    payment = paynow.create_payment(
                        d.get("name", "Donor"),
                        d.get("email", "donor@example.com")
                    )


                    payment.add(d.get("purpose", "Church Donation"), float(d.get("amount", 0)))

                    # Send payment request
                    response = paynow.send_mobile(
                        payment,
                        d.get("phone", phone),
                        method.lower().replace(" ", "")
                    )

                    if response.success:
                        session["poll_url"] = response.poll_url
                        pending_payments[phone] = {
                            "poll_url": response.poll_url,
                            "start_time": datetime.now()
                        }

                        whatsapp.send_message(
                            f"💳 Please complete your {method} payment using the link below:\n\n"
                            f"{response.redirect_url}\n\n"
                            "✅ I will monitor your payment for 10 minutes and confirm automatically.\n"
                            "_Type *done* when finished if you'd like to speed things up._",
                            phone
                        )
                    else:
                        whatsapp.send_message(
                            "❌ Failed to generate payment request. Please try again or use another method.",
                            phone
                        )

                    return "ok"


               


                if session["step"] in step_handlers:
                    logging.info(f"Processing step '{session['step']}' for {phone}")
                    return step_handlers[session["step"]](phone, msg, session)

                logging.error(f"Invalid session step for {phone}: {session['step']}")
                return jsonify({"status": "error", "message": "Invalid session step"}), 400

            logging.info("Received POST that is not a WhatsApp message.")
            return jsonify({"status": "ignored"}), 200

    except Exception as e:
        logger.error(f"Message processing error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

  




        
        
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8010))
    logger.info(f"Starting server on port {port}")
    latterpay.run(host="0.0.0.0", port=port)