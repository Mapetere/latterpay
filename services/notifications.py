import config
from datetime import datetime, timedelta

import os

def notify_admin_for_approval(user_phone, donation_description):
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


def notify_finance_director(d):
    msg = (
        f"📥 *New Church Donation!*\n\n"
        f"🙍🏽 Name: {d['name']}\n"
        f"💵 Amount: {d['amount']}\n"
        f"📌 Purpose: {d['donation_type']}\n"
        f"🌍 Congregation: {d['region']}\n"
        f"📝 Note: {d['note']}"
    )
    config.whatsapp.send_message(msg, config.finance_phone)