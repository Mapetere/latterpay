"""
Simple Paynow Integration Module for LatterPay
===============================================
Provides simplified Paynow payment functions.

Author: Nyasha Mapetere
Version: 2.0.0
"""

from paynow import Paynow
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Initialize Paynow with environment variables
_integration_id = os.getenv("PAYNOW_INTEGRATION_ID") or os.getenv("PAYNOW_ZWG_ID")
_integration_key = os.getenv("PAYNOW_INTEGRATION_KEY") or os.getenv("PAYNOW_ZWG_KEY")
_return_url = os.getenv("PAYNOW_RETURN_URL", "https://latterpay-production.up.railway.app/payment-return")
_result_url = os.getenv("PAYNOW_RESULT_URL", "https://latterpay-production.up.railway.app/payment-result")

# Check if we have the required config
PAYNOW_CONFIGURED = bool(_integration_id and _integration_key)

if PAYNOW_CONFIGURED:
    paynow = Paynow(
        _integration_id,
        _integration_key,
        _return_url,
        _result_url
    )
    logger.info("Paynow initialized successfully")
else:
    paynow = None
    logger.warning("Paynow not configured - payment functions will not work")


def initiate_payment(name, email, phone, amount, reference="Donation"):
    """
    Initiate a mobile payment via Paynow.
    
    Args:
        name: Payer's name
        email: Payer's email
        phone: Payer's phone number
        amount: Payment amount
        reference: Payment reference
        
    Returns:
        Dictionary with payment status and details
    """
    if not PAYNOW_CONFIGURED:
        return {"status": "error", "message": "Payment service not configured"}
    
    try:
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
            
    except Exception as e:
        logger.error(f"Payment initiation error: {e}")
        return {"status": "error", "message": str(e)}


def check_payment_status(poll_url):
    """
    Check the status of a payment.
    
    Args:
        poll_url: The poll URL from payment initiation
        
    Returns:
        Dictionary with payment status
    """
    if not PAYNOW_CONFIGURED:
        return {"status": "error", "message": "Payment service not configured"}
    
    try:
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
            
    except Exception as e:
        logger.error(f"Payment status check error: {e}")
        return {"status": "error", "message": str(e)}


def get_payment_details(reference):
    """Get details of a payment by reference."""
    if not PAYNOW_CONFIGURED:
        return {"status": "error", "message": "Payment service not configured"}
    
    try:
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
            
    except Exception as e:
        logger.error(f"Get payment details error: {e}")
        return {"status": "error", "message": str(e)}


def cancel_payment(reference):
    """Cancel a pending payment."""
    if not PAYNOW_CONFIGURED:
        return {"status": "error", "message": "Payment service not configured"}
    
    try:
        response = paynow.cancel_payment(reference)

        if response.success:
            return {"status": "cancelled", "message": "Payment cancelled successfully"}
        else:
            return {"status": "error", "message": response.message}
            
    except Exception as e:
        logger.error(f"Payment cancellation error: {e}")
        return {"status": "error", "message": str(e)}


def get_payment_methods(): 
    """Get available payment methods."""
    if not PAYNOW_CONFIGURED:
        return []
    
    try:
        return paynow.get_payment_methods()
    except Exception as e:
        logger.error(f"Get payment methods error: {e}")
        return []


def get_payment_instructions():
    """Get instructions for available payment methods."""
    methods = get_payment_methods()
    instructions = []

    for method in methods:
        if method.name == "ecocash":
            instructions.append("To pay via Ecocash, dial *151# and follow the prompts.")
        elif method.name == "onemoney":
            instructions.append("To pay via OneMoney, dial *111# and follow the prompts.")
        elif method.name == "zipit":
            instructions.append("To pay via Zipit, use your bank's mobile app or USSD service.")
        elif method.name == "usd":
            instructions.append("To pay in USD, please visit our nearest branch or contact us for details.")

    return "\n".join(instructions) if instructions else "Payment instructions not available."


def get_payment_reference():
    """Generate a unique payment reference."""
    import uuid
    return str(uuid.uuid4())    


def get_payment_status_message(status):
    """Return a user-friendly message based on payment status."""
    status_messages = {
        "pending": "Your payment is pending. Please complete the transaction.",
        "completed": "Your payment was successful! Thank you for your donation.",
        "failed": "Your payment failed. Please try again or contact support.",
        "cancelled": "Your payment has been cancelled.",
    }
    return status_messages.get(status, "Unknown payment status.")


# Export functions
__all__ = [
    'initiate_payment',
    'check_payment_status',
    'get_payment_details',
    'cancel_payment',
    'get_payment_methods',
    'get_payment_instructions',
    'get_payment_reference',
    'get_payment_status_message',
    'PAYNOW_CONFIGURED',
]
