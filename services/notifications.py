from services.pygwan_whatsapp import whatsapp
from services import  config
from datetime import datetime, timedelta
import os




def notify_finance_director(d):
    msg = (
        f"📥 *New Church Donation!*\n\n"
        f"🙍🏽 Name: {d['name']}\n"
        f"💵 Amount: {d['amount']}\n"
        f"📌 Purpose: {d['donation_type']}\n"
        f"🌍 Congregation: {d['region']}\n"
        f"📝 Note: {d['note']}"
    )
    whatsapp.send_message(msg, config.finance_phone)