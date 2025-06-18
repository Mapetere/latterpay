from dotenv import load_dotenv
import os

load_dotenv()

finance_phone = os.getenv("FINANCE_PHONE")
access_token = os.getenv("WHATSAPP_TOKEN")
phone_number_id = os.getenv("PHONE_NUMBER_ID")
admin_phone = os.getenv("ADMIN_PHONE") 


sessions = {}


donation_types = ["Monthly Contributions", "August Conference", "Youth Conference"]
donation_types.append("Other")

CUSTOM_TYPES_FILE = "custom_donation_types.json"
PAYMENTS_FILE = "donation_payment.json"

menu = [
        "1. _*Monthly Contributions*_",
        "2. _*August Conference*_",
        "3. _*Youth Conference*_",
        "4. _*Other*_ (describe new purpose)\n"

        "5. *Learn more about donation types*"
    ]
    

