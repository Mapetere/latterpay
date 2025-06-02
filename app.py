from flask import Flask, request
from dotenv import load_dotenv
import os
from pygwan import WhatsApp

load_dotenv()

app = Flask(__name__)

whatsapp = WhatsApp(
    token=os.getenv("WHATSAPP_TOKEN"),
    phone_number_id=os.getenv("PHONE_NUMBER_ID")
)

sessions = {}

donation_types = ["Monthly Contributions", "August Conference", "Youth Conference"]

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
            print("Verify token matched")  # Debug log
            return request.args.get("hub.challenge")
        print("Invalid verify token")  # Debug log
        return "Invalid verify token", 403

    data = request.get_json()
    print(f"Received data: {data}")  # Debug log
    if whatsapp.is_message(data):
        phone = whatsapp.get_mobile(data)
        name = whatsapp.get_name(data)
        msg = whatsapp.get_message(data)
        print(f"Message from {name} ({phone}): {msg}")  # Debug log

        if phone not in sessions:
            sessions[phone] = {"step": "name", "data": {}}
            whatsapp.send_message(f"Hi {name}! Welcome to the Latter Rain Church Donation Bot. Kindly enter your *full name*", phone)
            return "ok"

        session = sessions[phone]

        if session["step"] == "name":
            session["data"]["name"] = msg
            session["step"] = "amount"
            whatsapp.send_message("💰 How much would you like to donate (e.g. 5000)?", phone)

        elif session["step"] == "amount":
            session["data"]["amount"] = msg
            session["step"] = "donation_type"
            
            menu_text = (
                "🙏🏾 Please choose the purpose of your donation:\n\n"
                "1. Monthly Contributions\n"
                "2. August Conference\n"
                "3. Youth Conference\n\n"
                "Reply with the number (1-3)"
            )
            whatsapp.send_message(menu_text, phone)

        elif session["step"] == "donation_type":
            if msg in ["1", "2", "3"]:
                session["data"]["donation_type"] = donation_types[int(msg)-1]  # Note: -1 because list is 0-indexed
                session["step"] = "region"
                whatsapp.send_message("🌍 What is your congregation name?", phone)
            else:
                whatsapp.send_message("❗Please reply with a number between 1-3 to select the donation type.", phone)



        elif session["step"] == "region":
            session["data"]["region"] = msg
            session["step"] = "note"
            whatsapp.send_message("📝 Any extra notes for the finance director?", phone)

        elif session["step"] == "note":
            session["data"]["note"] = msg
            session["step"] = "done"
            summary = session["data"]
            confirm_message = (
                f"✅ Thank you {summary['name']}!\n\n"
                f"💰 Amount: {summary['amount']}\n"
                f"📌 Type: {summary['donation_type']}\n"
                f"🌍 Congregation: {summary['region']}\n"
                f"📝 Note: {summary['note']}\n\n"
                "We will now send a payment link and notify the finance director after payment is complete."
            )
            whatsapp.send_message(confirm_message, phone)

            # TODO: Trigger Paynow here
            notify_finance_director(summary)
            del sessions[phone]

    return "ok"

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

if __name__ == "__main__":
    app.run(port=5000, debug=True)



