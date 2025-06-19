from paynow import Paynow
import os
from dotenv import load_dotenv
load_dotenv()

paynow = Paynow(
    os.getenv("PAYNOW_INTEGRATION_ID"),
    os.getenv("PAYNOW_INTEGRATION_KEY"),
    os.getenv("PAYNOW_RETURN_URL"),
    os.getenv("PAYNOW_RESULT_URL")
)

def initiate_payment(name, email, phone, amount, reference="Donation"):
    payment = paynow.create_payment(reference, email)
    payment.add(f"Donation from {name}", amount)

    response = paynow.send_mobile(payment, phone, "ecocash")  

    if response.success:
        return {
            "status": "pending",
            "poll_url": response.poll_url,
            "instructions": response.instructions,
            "redirect_url": response.redirect_url
        }
    else:
        return {"status": "error", "message": response.message}
    
def check_payment_status(poll_url):
    response = paynow.poll(poll_url)

    if response.success:
        return {
            "status": response.status,
            "amount": response.amount,
            "reference": response.reference,
            "paid_at": response.paid_at
        }
    else:
        return {"status": "error", "message": response.message}
def get_payment_details(reference):
    payment = paynow.get_payment(reference)

    if payment.success:
        return {
            "status": payment.status,
            "amount": payment.amount,
            "reference": payment.reference,
            "paid_at": payment.paid_at,
            "details": payment.details
        }
    else:
        return {"status": "error", "message": payment.message}
    
def cancel_payment(reference):
    response = paynow.cancel_payment(reference)

    if response.success:
        return {"status": "cancelled", "message": "Payment cancelled successfully"}
    else:
        return {"status": "error", "message": response.message}
    
def get_payment_methods(): 
    return paynow.get_payment_methods()

def get_payment_instructions():
    methods = get_payment_methods()
    instructions = []

    for method in methods:
        if method.name == "ecocash":
            instructions.append("To pay via Ecocash, dial *151# and follow the prompts.*")
        elif method.name == "onemoney":
            instructions.append("To pay via OneMoney, dial *111# and follow the prompts.")
        elif method.name == "zipit":
            instructions.append("To pay via Zipit, use your bank's mobile app or USSD service.")
        elif method.name == "usd":
            instructions.append("To pay in USD, please visit our nearest branch or contact us for details.")

    return "\n".join(instructions)

def get_payment_reference():
    """Generates a unique payment reference"""
    import uuid
    return str(uuid.uuid4())    

def get_payment_status_message(status):
    """Returns a user-friendly message based on payment status"""
    if status == "pending":
        return "Your payment is pending. Please complete the transaction."
    elif status == "completed":
        return "Your payment was successful! Thank you for your donation."
    elif status == "failed":
        return "Your payment failed. Please try again or contact support."
    elif status == "cancelled":
        return "Your payment has been cancelled."
    else:
        return "Unknown payment status."
    


# Ensure environment variables are loaded
if not all([os.getenv("PAYNOW_INTEGRATION_ID"), os.getenv("PAYNOW_INTEGRATION_KEY"),
            os.getenv("PAYNOW_RETURN_URL"), os.getenv("PAYNOW_RESULT_URL")]):
    raise EnvironmentError("Missing required Paynow environment variables")

