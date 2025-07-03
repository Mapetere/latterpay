from dotenv import load_dotenv
import os

load_dotenv()

finance_phone = os.getenv("FINANCE_PHONE")
access_token = os.getenv("WHATSAPP_TOKEN")
phone_number_id = os.getenv("PHONE_NUMBER_ID")
admin_phone = os.getenv("ADMIN_PHONE") 





donation_types = ["Monthly Contributions", "August Conference", "Youth Conference", "Construction Contribution", "Pastoral Support"]
donation_types.append("Other")

CUSTOM_TYPES_FILE = "custom_donation_types.json"
PAYMENTS_FILE = "donation_payment.json"

menu = [
        "1. *Monthly Contributions*",
        "2. *August Conference*",
        "3. *Youth Conference*",
        "4. *Construction Contribution*",
        "5. *Pastoral Support*"
       
    ]
    

