
# services/admin_service.py
from datetime import datetime, timedelta
import json
import os
from services import config
from services.pygwan_whatsapp import whatsapp
from services.setup import send_payment_report_to_finance


class AdminService:

    @staticmethod
    def notify_approval_request(user_phone, donation_description):
        """Notify admin about new donation type request"""
        approval_msg = (
            "🆕 New Donation Type Request\n\n"
            f"From: {user_phone}\n"
            f"Request: {donation_description}\n\n"
            "To approve, reply with:\n"
            f"/approve {user_phone} [duration]\n\n"
            "Example:\n"
            f"/approve {user_phone} 1year"
        )
        config.whatsapp.send_message(approval_msg, config.admin_phone)

    @staticmethod
    def _process_approval(admin_phone, user_phone, duration):
        """Core approval logic"""
        # Load existing types
        with open(config.CUSTOM_TYPES_FILE, "r") as f:
            custom_types = json.load(f)
        
        # Validate request exists
        user_session = config.sessions.get(user_phone, {})
        request_desc = user_session.get("data", {}).get("custom_donation_request")
        
        if not request_desc:
            config.whatsapp.send_message("❌ No pending request found", admin_phone)
            return False
        
        # Create and save new type
        new_type = AdminService._create_donation_type(
            request_desc, user_phone, admin_phone, duration
        )
        custom_types.append(new_type)
        
        with open(config.CUSTOM_TYPES_FILE, "w") as f:
            json.dump(custom_types, f)
        
        # Notify both parties
        AdminService._send_approval_notifications(
            admin_phone, user_phone, request_desc, duration
        )
        return True

    @staticmethod
    def _create_donation_type(description, user_phone, admin_phone, duration):
        """Create new donation type object"""
        return {
            "description": description,
            "added_by": user_phone,
            "approved_by": admin_phone,
            "approved_on": datetime.now().isoformat(),
            "expires": AdminService._calculate_expiry(duration)
        }

    @staticmethod
    def _calculate_expiry(duration):
        """Calculate expiration timestamp"""
        if duration == "forever":
            return None
        if "year" in duration:
            years = int(duration.replace("year", ""))
            return (datetime.now() + timedelta(days=years*365)).isoformat()
        raise ValueError("Invalid duration format")

    @staticmethod
    def _send_approval_notifications(admin_phone, user_phone, description, duration):
        """Send success messages to both parties"""
        config.whatsapp.send_message(
            f"✅ Your donation type '{description}' has been approved!\n"
            f"Available until: {duration if duration != 'forever' else 'permanently'}",
            user_phone
        )
        config.whatsapp.send_message(
            "✅ Approval processed successfully!",
            admin_phone
        )
