

{
  "messaging_product": "whatsapp",
  "to": "{{user_phone}}",
  "type": "interactive",
  "interactive": {
    "type": "button",
    "body": {
      "text": "👋🏾 Hi there! What would you like to do today?\n\n1️⃣ Register for the *Runder Rural Clinic Project*\n2️⃣ Make a Payment"
    },
    "action": {
      "buttons": [
        {
          "type": "reply",
          "reply": {
            "id": "register_btn",
            "title": "📝 Register"
          }
        },
        {
          "type": "reply",
          "reply": {
            "id": "pay_btn",
            "title": "💸 Make Payment"
          }
        }
      ]
    }
  }
}
