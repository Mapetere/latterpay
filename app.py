from flask import Flask, request, jsonify
from datetime import datetime
import os
import json
import logging
from dotenv import load_dotenv
from pygwan import WhatsApp as whatsapp

# Initialize logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)

load_dotenv()

app = Flask(__name__)

@app.route("/")
def home():
    return "App is running"

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    try:
        if request.method == "GET":
            # Webhook verification
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
            data = request.get_json()
            logging.info(f"Incoming POST data: {data}")
            
            # Handle Railway deployment notifications
            if data.get('type') == 'DEPLOY':
                logging.info("Received Railway deployment notification")
                return jsonify({"status": "ignored"}), 200
            
            # Handle WhatsApp messages
            try:
                
                if whatsapp.is_message(data):
                    return handle_whatsapp_message(data)
            except ImportError:
                logging.error("WhatsApp module not found")
            except Exception as e:
                logging.error(f"Error processing WhatsApp message: {str(e)}")
            
            return jsonify({"status": "unhandled"}), 200

    except Exception as e:
        logging.error(f"Webhook error: {str(e)}", exc_info=True)
        return "Error", 500

def handle_whatsapp_message(data):
    """Process WhatsApp messages"""
    phone = whatsapp.get_mobile(data)
    message = whatsapp.get_message(data)
    logging.info(f"Processing WhatsApp message from {phone}: {message}")
    
    # Add your message handling logic here
    return jsonify({"status": "processed"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port)