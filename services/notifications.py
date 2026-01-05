"""
Notification Service for LatterPay
===================================
Handles all user notifications including:
- Payment confirmations
- Receipt generation
- Email notifications (optional)
- WhatsApp formatted messages

Author: Nyasha Mapetere
Version: 2.1.0
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
import json

from services.pygwan_whatsapp import whatsapp

logger = logging.getLogger(__name__)


# ============================================================================
# MESSAGE TEMPLATES
# ============================================================================

class MessageTemplates:
    """
    Centralized WhatsApp message templates for consistent formatting.
    """
    
    # Welcome messages
    WELCOME_NEW_USER = """
👋 *Welcome to LatterPay!*

I'm your trusted payments assistant for the Runde Rural Clinic Project.

💳 *What I can help you with:*
• Make donations and payments
• Track your payment history
• Get payment receipts

Let's get started! Please enter the *full name* of the person making the payment.
"""

    WELCOME_RETURNING_USER = """
🔄 *Welcome back to LatterPay!*

Great to see you again! Ready for another transaction?

Please enter the *name of the person* making this payment.
"""

    # Session messages
    SESSION_TIMEOUT_WARNING = """
⚠️ *Session Expiring Soon*

Your session will expire in about 1 minute.

_Reply with any message to keep your session active._
"""

    SESSION_EXPIRED = """
⏱️ *Session Expired*

Your session has timed out due to inactivity.

_Send any message to start a new session._
"""

    SESSION_CANCELLED = """
🚫 *Session Cancelled*

Your session has been cancelled successfully.

_You can start a new session anytime by sending a message._
"""

    # Payment flow messages
    ASK_REGION = """
📍 *Step 2 of 6: Region*

Please enter your *congregation name* or *region* in full.

_Example: Harare Central_
"""

    ASK_DONATION_TYPE = """
🎯 *Step 3 of 6: Payment Purpose*

{donation_menu}

_Reply with the number of your choice_
"""

    ASK_AMOUNT = """
💰 *Step 4 of 6: Amount*

Please enter the *payment amount* (e.g., 40 or 40.00)

⚠️ *Note:* Maximum amount per transaction is 480
"""

    ASK_CURRENCY = """
💱 *Step 5 of 6: Currency*

Choose your payment currency:

*1.* USD 🇺🇸
*2.* ZWG 🇿🇼

_Reply with 1 or 2_
"""

    ASK_NOTE = """
📝 *Step 6 of 6: Additional Notes*

Do you have any additional notes to clarify this payment?

_Type your note or send "none" to skip_
"""

    # Payment confirmation
    PAYMENT_SUMMARY = """
📋 *PAYMENT SUMMARY*
━━━━━━━━━━━━━━━━━━━━

👤 *Name:* {name}
🏛️ *Region:* {region}
🎯 *Purpose:* {donation_type}
💰 *Amount:* {currency} {amount}
📝 *Note:* {note}

━━━━━━━━━━━━━━━━━━━━

✅ Type *confirm* to proceed
✏️ Type *edit* to make changes
❌ Type *cancel* to abort
"""

    ASK_PAYMENT_METHOD = """
💳 *Select Payment Method*

*1.* EcoCash 📱
*2.* OneMoney 📱
*3.* TeleCash 📱
*4.* USD Transfer 💵

_Reply with the number of your choice_
"""

    ASK_PAYMENT_NUMBER = """
📞 *Enter Payment Number*

Please enter the *{method}* number to process this payment.

_Format: 0771234567 or 263771234567_
"""

    # Payment status messages
    PAYMENT_INITIATED = """
🔄 *Payment Request Sent!*

A payment request has been sent to your phone.

📱 *Please check your phone* and approve the payment.

_Type "check" after approving to confirm your payment status._
"""

    PAYMENT_SUCCESS = """
✅ *Payment Successful!*

━━━━━━━━━━━━━━━━━━━━
🎉 *RECEIPT*
━━━━━━━━━━━━━━━━━━━━

📅 *Date:* {date}
🔢 *Reference:* {reference}
👤 *Name:* {name}
💰 *Amount:* {currency} {amount}
🎯 *Purpose:* {donation_type}
📱 *Method:* {payment_method}

━━━━━━━━━━━━━━━━━━━━

Thank you for your contribution! 🙏

_This receipt has been recorded. You can screenshot this for your records._
"""

    PAYMENT_FAILED = """
❌ *Payment Failed*

Unfortunately, your payment could not be processed.

*Possible reasons:*
• Insufficient balance
• Transaction timeout
• Network issues

_Please try again or use a different payment method._
"""

    PAYMENT_CANCELLED = """
⚠️ *Payment Cancelled*

Your payment was cancelled.

_You can try again by typing "confirm" or type "cancel" to exit._
"""

    PAYMENT_PENDING = """
⏳ *Payment Processing*

Your payment is still being processed.

_Please wait a moment and type "check" again._
"""

    # Error messages
    INVALID_INPUT = """
❌ *Invalid Input*

{error_message}

_Please try again with a valid response._
"""

    GENERIC_ERROR = """
😔 *Something Went Wrong*

An error occurred while processing your request.

_Please try again or type "cancel" to start over._
"""

    RATE_LIMIT_ERROR = """
🚫 *Too Many Requests*

You're sending messages too quickly. Please slow down.

_Try again in a few seconds._
"""

    SERVICE_UNAVAILABLE = """
🔧 *Service Temporarily Unavailable*

We're experiencing technical difficulties. Our team has been notified.

_Please try again in a few minutes._
"""

    # Admin messages
    ADMIN_HELP = """
👩🏾‍💼 *Admin Panel*

Available commands:

📊 *Reports*
• `/report pdf` - Download PDF report
• `/report excel` - Download Excel report

✅ *Approvals*  
• `/approve [txn_id]` - Approve transaction
• `/session [phone]` - View user session

📈 *Stats*
• `/stats` - View system statistics
• `/health` - System health check
"""

    ADMIN_REPORT_SENT = """
📊 *Report Generated*

Your {report_type} report has been sent to the finance team.

_Report includes all transactions from the past 24 hours._
"""


# ============================================================================
# NOTIFICATION SERVICE
# ============================================================================

class NotificationService:
    """
    Centralized notification service for sending formatted messages.
    """
    
    @staticmethod
    def send_welcome(phone: str, is_new_user: bool = True) -> bool:
        """Send welcome message to user."""
        try:
            template = MessageTemplates.WELCOME_NEW_USER if is_new_user else MessageTemplates.WELCOME_RETURNING_USER
            whatsapp.send_message(template.strip(), phone)
            logger.info(f"Sent welcome message to {phone}")
            return True
        except Exception as e:
            logger.error(f"Failed to send welcome to {phone}: {e}")
            return False
    
    @staticmethod
    def send_payment_summary(phone: str, data: Dict[str, Any]) -> bool:
        """Send payment summary for confirmation."""
        try:
            message = MessageTemplates.PAYMENT_SUMMARY.format(
                name=data.get('name', 'N/A'),
                region=data.get('region', 'N/A'),
                donation_type=data.get('donation_type', 'N/A'),
                currency=data.get('currency', 'ZWG'),
                amount=data.get('amount', '0'),
                note=data.get('note', 'None')
            )
            whatsapp.send_message(message.strip(), phone)
            logger.info(f"Sent payment summary to {phone}")
            return True
        except Exception as e:
            logger.error(f"Failed to send payment summary to {phone}: {e}")
            return False
    
    @staticmethod
    def send_receipt(phone: str, data: Dict[str, Any], reference: str) -> bool:
        """Send payment receipt."""
        try:
            message = MessageTemplates.PAYMENT_SUCCESS.format(
                date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                reference=reference,
                name=data.get('name', 'N/A'),
                currency=data.get('currency', 'ZWG'),
                amount=data.get('amount', '0'),
                donation_type=data.get('donation_type', 'N/A'),
                payment_method=data.get('payment_method', 'N/A')
            )
            whatsapp.send_message(message.strip(), phone)
            logger.info(f"Sent receipt to {phone}, ref: {reference}")
            return True
        except Exception as e:
            logger.error(f"Failed to send receipt to {phone}: {e}")
            return False
    
    @staticmethod
    def send_payment_status(phone: str, status: str) -> bool:
        """Send payment status update."""
        try:
            status_messages = {
                'initiated': MessageTemplates.PAYMENT_INITIATED,
                'success': MessageTemplates.PAYMENT_SUCCESS,
                'failed': MessageTemplates.PAYMENT_FAILED,
                'cancelled': MessageTemplates.PAYMENT_CANCELLED,
                'pending': MessageTemplates.PAYMENT_PENDING,
            }
            
            message = status_messages.get(status, MessageTemplates.PAYMENT_PENDING)
            
            # For success, we need data - use generic success if no data
            if status == 'success':
                message = "✅ *Payment Successful!*\n\nYour payment has been recorded. Thank you! 🙏"
            
            whatsapp.send_message(message.strip(), phone)
            logger.info(f"Sent {status} status to {phone}")
            return True
        except Exception as e:
            logger.error(f"Failed to send status to {phone}: {e}")
            return False
    
    @staticmethod
    def send_error(phone: str, error_type: str = 'generic', error_message: str = None) -> bool:
        """Send error message to user."""
        try:
            if error_type == 'invalid_input' and error_message:
                message = MessageTemplates.INVALID_INPUT.format(error_message=error_message)
            elif error_type == 'rate_limit':
                message = MessageTemplates.RATE_LIMIT_ERROR
            elif error_type == 'service_unavailable':
                message = MessageTemplates.SERVICE_UNAVAILABLE
            else:
                message = MessageTemplates.GENERIC_ERROR
            
            whatsapp.send_message(message.strip(), phone)
            return True
        except Exception as e:
            logger.error(f"Failed to send error to {phone}: {e}")
            return False
    
    @staticmethod
    def send_session_warning(phone: str) -> bool:
        """Send session timeout warning."""
        try:
            whatsapp.send_message(MessageTemplates.SESSION_TIMEOUT_WARNING.strip(), phone)
            return True
        except Exception as e:
            logger.error(f"Failed to send session warning to {phone}: {e}")
            return False
    
    @staticmethod
    def send_session_expired(phone: str) -> bool:
        """Send session expired message."""
        try:
            whatsapp.send_message(MessageTemplates.SESSION_EXPIRED.strip(), phone)
            return True
        except Exception as e:
            logger.error(f"Failed to send session expired to {phone}: {e}")
            return False
    
    @staticmethod
    def send_admin_help(phone: str) -> bool:
        """Send admin help message."""
        try:
            whatsapp.send_message(MessageTemplates.ADMIN_HELP.strip(), phone)
            return True
        except Exception as e:
            logger.error(f"Failed to send admin help to {phone}: {e}")
            return False


# ============================================================================
# RECEIPT GENERATOR
# ============================================================================

class ReceiptGenerator:
    """
    Generates unique receipt/reference numbers for transactions.
    """
    
    @staticmethod
    def generate_reference() -> str:
        """
        Generate a unique transaction reference.
        Format: LP-YYYYMMDD-XXXXXX
        """
        date_part = datetime.now().strftime("%Y%m%d")
        import random
        random_part = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        return f"LP-{date_part}-{random_part}"
    
    @staticmethod
    def generate_receipt_data(session_data: Dict[str, Any], payment_status: str) -> Dict[str, Any]:
        """
        Generate complete receipt data for storage and display.
        """
        return {
            "reference": ReceiptGenerator.generate_reference(),
            "timestamp": datetime.now().isoformat(),
            "name": session_data.get('name', 'Unknown'),
            "region": session_data.get('region', 'Unknown'),
            "donation_type": session_data.get('donation_type', 'Donation'),
            "amount": session_data.get('amount', 0),
            "currency": session_data.get('currency', 'ZWG'),
            "payment_method": session_data.get('payment_method', 'Unknown'),
            "phone": session_data.get('phone', 'Unknown'),
            "note": session_data.get('note', ''),
            "status": payment_status,
        }


# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

notification_service = NotificationService()
receipt_generator = ReceiptGenerator()


__all__ = [
    'MessageTemplates',
    'NotificationService',
    'ReceiptGenerator',
    'notification_service',
    'receipt_generator',
]