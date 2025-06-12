from flask import Flask, request

app = Flask(__name__)

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    print("Webhook hit")
    return "ok"

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
