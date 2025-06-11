from flask import request
from paynow import Paynow
from datetime import datetime
import json
import os

@app.route("/flow-submission", methods=["POST"])
def flow_submission():
    try:
        data = request.get_json()
        print("[FLOW SUBMISSION] 🔔 Received:", json.dumps(data, indent=2))

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
            return_url="https://yourdomain.com/payment-return",
            result_url="https://yourdomain.com/payment-result"
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
