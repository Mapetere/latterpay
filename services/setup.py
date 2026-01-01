"""
Setup Module for LatterPay
===========================
Handles scheduled reports and phone registration.

Author: Nyasha Mapetere
Version: 2.0.0
"""

import os
import logging
from flask import request
import requests
from services.sendpdf import send_pdf
from services.generatePR import generate_payment_report 
from services.generateER import generate_excel_report
from services.config import finance_phone
import atexit

logger = logging.getLogger(__name__)

# Try to import scheduler, with fallback
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.warning("APScheduler not available - scheduled reports disabled")


def setup_scheduled_reports():
    """Configure automatic daily/weekly reports."""
    if not SCHEDULER_AVAILABLE:
        logger.warning("Scheduler not available, skipping scheduled reports setup")
        return
    
    try:
        scheduler = BackgroundScheduler(daemon=True)
        
        # Weekly summary every Monday at 10am
        scheduler.add_job(
            lambda: send_payment_report_to_finance("excel"),
            'cron',
            day_of_week='mon',
            hour=10,
            minute=0
        )
        
        scheduler.start()
        logger.info("Scheduled reports setup complete")
        
        atexit.register(lambda: scheduler.shutdown())
        
    except Exception as e:
        logger.error(f"Failed to setup scheduled reports: {e}")


def send_payment_report_to_finance(report_format="pdf"):
    """
    Generate and send payment report to finance.
    
    Args:
        report_format: Either "pdf" or "excel"
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Generate the report
        if report_format == "excel":
            report_path = generate_excel_report()
        else:
            report_path = generate_payment_report()

        if not report_path:
            logger.error(f"{report_format.upper()} generation failed")
            return False

        if not os.path.exists(report_path):
            logger.error(f"{report_format.upper()} not found at {report_path}")
            return False

        logger.info(f"{report_format.upper()} generated ({os.path.getsize(report_path)} bytes)")

        # Send the file
        caption = f"Donation Report ({report_format.upper()})"
        success = send_pdf(
            phone=finance_phone,
            file_path=report_path,
            caption=caption
        )

        # Cleanup - remove temporary file
        try:
            if os.path.exists(report_path):
                os.unlink(report_path)
        except Exception as cleanup_err:
            logger.warning(f"Failed to cleanup report file: {cleanup_err}")

        return success

    except Exception as e:
        logger.error(f"Error sending {report_format.upper()} report: {e}")
        return False


def register_phone_number(phone_number_id: str, access_token: str, pin: str):
    """
    Register a phone number with WhatsApp Business API.
    
    Args:
        phone_number_id: The WhatsApp phone number ID
        access_token: The access token for authentication
        pin: The registration PIN
        
    Returns:
        Response from the API
    """
    try:
        url = f'https://graph.facebook.com/v22.0/{phone_number_id}/register'
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "pin": pin
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        logger.info(f"Phone registration status: {response.status_code}")
        logger.debug(f"Response: {response.text}")
        
        return response
        
    except Exception as e:
        logger.error(f"Phone registration failed: {e}")
        raise


# Export functions
__all__ = [
    'setup_scheduled_reports',
    'send_payment_report_to_finance',
    'register_phone_number',
]