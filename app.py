from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from dotenv import load_dotenv
import uvicorn
import json
import os
import logging
import sys
import sqlite3
from datetime import datetime
import threading
import time

from services.sessions import (
    check_session_timeout, cancel_session,
    load_session, save_session, monitor_sessions
)
from services.registrationflow import handle_first_message
from services.pygwan_whatsapp import whatsapp
from services.config import CUSTOM_TYPES_FILE, PAYMENTS_FILE

load_dotenv()

app = FastAPI()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

for file_path in [CUSTOM_TYPES_FILE, PAYMENTS_FILE]:
    if not os.path.exists(file_path):
        with open(file_path, 'w') as f:
            json.dump([], f)

def init_db():
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_messages (
            msg_id TEXT PRIMARY KEY,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS known_users (
            phone TEXT PRIMARY KEY,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            phone TEXT PRIMARY KEY,
            step TEXT,
            data TEXT,
            last_active TIMESTAMP,
            warned INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def is_echo_message(msg_id):
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM sent_messages WHERE msg_id = ?", (msg_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_sent_message_id(msg_id):
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO sent_messages (msg_id) VALUES (?)", (msg_id,))
    conn.commit()
    conn.close()

def delete_old_ids():
    conn = sqlite3.connect("botdata.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sent_messages WHERE sent_at < datetime('now', '-15 minutes')")
    conn.commit()
    conn.close()

def cleanup_message_ids():
    def cleaner():
        while True:
            try:
                delete_old_ids()
                time.sleep(3600)
            except Exception as e:
                logger.warning(f"[CLEANUP ERROR] {e}")
                time.sleep(600)
    threading.Thread(target=cleaner, daemon=True).start()




@app.get("/")
async def home():
    logger.info("Home endpoint accessed")
    return PlainTextResponse("WhatsApp Donation Service is running")

@app.get("/payment-return")
async def payment_return():
    return HTMLResponse("<h2>Payment attempted. You may now return to WhatsApp.</h2>")

@app.post("/payment-result")
async def payment_result(request: Request):
    try:
        raw_data = await request.body()
        logger.info("Paynow Result Received:\n" + raw_data.decode())
        return PlainTextResponse("OK")
    except Exception as e:
        logger.error(f" Error handling Paynow result: {e}")
        return PlainTextResponse("ERROR", status_code=500)



@app.api_route("/webhook", methods=["GET", "POST"])
async def webhook_debug(request: Request):
    try:
        if request.method == "GET":
            params = dict(request.query_params)
            verify_token = params.get("hub.verify_token")
            challenge = params.get("hub.challenge")
            if verify_token == os.getenv("VERIFY_TOKEN"):
                logger.info("Webhook verified successfully!")
                return PlainTextResponse(challenge)
            return PlainTextResponse("Verification failed", status_code=403)

        elif request.method == "POST":
            body = await request.body()
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                logger.error("Invalid JSON received")
                return JSONResponse({"error": "Invalid JSON"}, status_code=400)

            if data.get("type") == "DEPLOY":
                logger.info("Railway deployment ping received")
                return JSONResponse({"status": "ignored"})

            if whatsapp.is_message(data):
                logger.info("=== WHATSAPP MESSAGE RECEIVED ===")
                phone = whatsapp.get_mobile(data)
                name = whatsapp.get_name(data)
                msg = whatsapp.get_message(data).strip()
                logger.info(f"Message from {phone} ({name}): {msg}")

                msg_id = whatsapp.get_message_id(data)
                if is_echo_message(msg_id) or msg_id is None:
                    logger.info("Ignored echo or missing msg ID.")
                    return JSONResponse({"status": "ignored"})

                save_sent_message_id(msg_id)

                session = load_session(phone)

                if not session:
                    whatsapp.send_button({
                        "header": "Welcome to LatterPay!",
                        "body": "Have you registered on Google Forms?",
                        "action": {
                            "buttons": [
                                {"type": "reply", "reply": {"id": "yes", "title": "Yes, I have registered"}},
                                {"type": "reply", "reply": {"id": "no", "title": "No, I haven't registered"}}
                            ]
                        }
                    }, phone)

                    session = {
                        "step": "start",
                        "data": {},
                        "last_active": datetime.now()
                    }
                    save_session(phone, session["step"], session["data"])

                    return await handle_first_message(phone, msg, session)

                if msg.lower() == "cancel":
                    cancel_session(phone)
                    return JSONResponse({"status": "session cancelled"})

                if check_session_timeout(phone):
                    return JSONResponse({"status": "session timeout"})

                return await handle_first_message(phone, msg, session)

            else:
                logger.info("Ignored non-message webhook")
                return JSONResponse({"status": "ignored"})

    except Exception as e:
        logger.error(f"Unhandled error in webhook: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)

init_db()
monitor_sessions()
cleanup_message_ids()
