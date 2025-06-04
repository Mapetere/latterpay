import os
import requests
from services.config import config as config


def send_pdf(phone, file_path, caption):
    

    url = f"https://graph.facebook.com/v18.0/{config.phone_number_id}/media"

    # Upload media
    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f, 'application/pdf')}
        data = {
            'messaging_product': 'whatsapp'
        }
        headers = {
            'Authorization': f'Bearer {config.access_token}'
        }
        response = requests.post(url, files=files, data=data, headers=headers)
        print(response.json())
        media_id = response.json().get("id")

    # Send document using media_id
    if media_id:
        send_url = f"https://graph.facebook.com/v18.0/{config.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "document",
            "document": {
                "id": media_id,
                "caption": caption
            }
        }
        headers['Content-Type'] = 'application/json'
        resp = requests.post(send_url, json=payload, headers=headers)
        print(resp.json())
    else:
        print("❌ Failed to upload media.")    