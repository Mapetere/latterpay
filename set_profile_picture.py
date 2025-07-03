import requests
import os
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN")  
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")    
WABA_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")                     
IMAGE_PATH = r"C:\Development\VS Code projects\LATTERPAY\latterpay\images\latterlogo.png"


upload_url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/media"



headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}



with open(IMAGE_PATH, "rb") as img_file:
    files = {
        "file": (os.path.basename(IMAGE_PATH), img_file, "image/png")
    }
    data = {
        "messaging_product": "whatsapp",
        "type": "image"
    }


    print("Uploading profile image...")
    upload_response = requests.post(upload_url, headers=headers, files=files, data=data)
    upload_data = upload_response.json()


if "id" not in upload_data:
    print("Failed to upload image:", upload_data)
    exit(1)


media_id = upload_data["id"]
print(f" Uploaded. Media ID: {media_id}")


import requests
headers = {"Authorization": "Bearer YOUR_ACCESS_TOKEN"}
response = requests.get("https://graph.facebook.com/v18.0/YOUR_WABA_ID?fields=id,name", headers=headers)
print(response.json())


set_profile_url = f"https://graph.facebook.com/v18.0/{WABA_ID}/whatsapp_business_profile"

payload = {
    "profile_picture": {
        "handle": media_id
    }
}

headers["Content-Type"] = "application/json"

print("Setting profile picture...")

set_response = requests.post(set_profile_url, headers=headers, json=payload)

if set_response.status_code == 200:
    print("Profile picture updated successfully!")
else:
    print(f" Failed to update profile picture: {set_response.status_code} {set_response.json()}")
