from services.config import config as config
import json
from datetime import datetime

def record_payment(payment_data):
    """Record a new payment in the payments file"""
    try:
        with open(config.PAYMENTS_FILE, 'r') as f:
            payments = json.load(f)
        
        payments.append({
            "name": payment_data["name"],
            "amount": float(payment_data["amount"]),
            "congregation": payment_data["region"],
            "purpose": payment_data["donation_type"],
            "date": datetime.now().isoformat(),
            "note": payment_data.get("note", "")
        })
        
        with open(config.PAYMENTS_FILE, 'w') as f:
            json.dump(payments, f)
        
        print("Payment recorded successfully.")
    except Exception as e:
        print(f"Error recording payment: {e}")