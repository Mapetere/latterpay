import pygwan
from dotenv import load_dotenv
from pygwan import WhatsApp
import os

load_dotenv()
whatsapp = WhatsApp(
    token=os.getenv("WHATSAPP_TOKEN"),
    phone_number_id=os.getenv("PHONE_NUMBER_ID")
)
