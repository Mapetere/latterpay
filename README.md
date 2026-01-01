# 💳 LatterPay - WhatsApp Payment Service

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/Mapetere/latterpay)
[![Python](https://img.shields.io/badge/python-3.9+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)

> A production-grade WhatsApp bot for managing donations and payments with end-to-end encryption, resilience patterns, and comprehensive error handling.

![LatterPay Banner](images/latterlogo.png)

## 🌟 Features

### Core Functionality
- 📱 **WhatsApp Integration** - Full WhatsApp Business API integration via Pygwan
- 💳 **Payment Processing** - Paynow integration for EcoCash, OneMoney, TeleCash, and USD
- 🔐 **End-to-End Encryption** - Meta Flow encryption with AES-256-CBC and RSA
- 📝 **Registration Flow** - Volunteer and donor registration with skill tracking

### Resilience & Reliability
- 🔄 **Circuit Breaker** - Prevents cascading failures when services are down
- ⏱️ **Rate Limiting** - Token bucket algorithm protects against abuse
- 🔁 **Retry with Backoff** - Exponential backoff for failed external calls
- 🏥 **Health Checks** - `/health` endpoint for monitoring

### Security
- 🛡️ **Input Validation** - XSS and SQL injection prevention
- ✅ **Webhook Signature Verification** - Meta and Paynow signature validation
- 🚫 **Request Throttling** - IP-based rate limiting
- 🔒 **Secure Sessions** - Database-backed session management

### Observability
- 📊 **Metrics Endpoint** - `/metrics` for request/error statistics
- 📝 **Structured Logging** - Request ID tracing with rotating log files
- 📈 **Payment Analytics** - Daily reports and transaction statistics
- 🔍 **Audit Trail** - Complete payment history tracking

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- WhatsApp Business Account
- Paynow Merchant Account
- Railway/Heroku for hosting (optional)

### Installation

```bash
# Clone the repository
git clone https://github.com/Mapetere/latterpay.git
cd latterpay

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables

Create a `.env` file with the following:

```env
# WhatsApp API
WHATSAPP_TOKEN=your_whatsapp_api_token
PHONE_NUMBER_ID=your_phone_number_id
VERIFY_TOKEN=your_webhook_verify_token
WHATSAPP_BOT_NUMBER=your_bot_phone_number

# Paynow (ZWG)
PAYNOW_ZWG_ID=your_zwg_integration_id
PAYNOW_ZWG_KEY=your_zwg_integration_key

# Paynow (USD)
PAYNOW_USD_ID=your_usd_integration_id
PAYNOW_USD_KEY=your_usd_integration_key

# Security
META_APP_SECRET=your_meta_app_secret
PRIVATE_KEY_PASSPHRASE=your_private_key_passphrase
FLASK_SECRET_KEY=random_secure_key

# Admin
ADMIN_PHONE=263771234567
FINANCE_PHONE=263771234568

# Feature Flags
ENABLE_REGISTRATION=true
ENABLE_DONATIONS=true
DEBUG=false
```

### Running Locally

```bash
# Development mode
python app.py

# Production mode with Gunicorn
gunicorn app:latterpay --bind 0.0.0.0:8010
```

## 📁 Project Structure

```
latterpay/
├── app.py                      # Main application entry point
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker configuration
├── Procfile                    # Railway/Heroku process file
├── private.pem                 # RSA private key (for encryption)
├── public.pem                  # RSA public key
├── services/
│   ├── __init__.py
│   ├── config.py              # Configuration management
│   ├── sessions.py            # Session management
│   ├── donationflow.py        # Donation flow handler
│   ├── resilience.py          # Circuit breaker, rate limiter
│   ├── notifications.py       # Message templates & notifications
│   ├── payment_history.py     # Payment tracking & analytics
│   ├── webhook_security.py    # Signature verification
│   ├── adminservice.py        # Admin commands
│   ├── setup.py               # Report generation
│   └── pygwan_whatsapp.py     # WhatsApp client wrapper
├── registration/
│   ├── handle_registration_flow.py
│   └── menu_with_buttons.py
├── templates/
│   └── menu_with_buttons.json
├── images/
│   └── latterlogo.png
└── logs/                       # Application logs
```

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service status |
| `/health` | GET | Health check with component status |
| `/metrics` | GET | Request/error statistics |
| `/webhook` | GET | WhatsApp webhook verification |
| `/webhook` | POST | WhatsApp message handling |
| `/payment-return` | GET | Paynow payment return page |
| `/payment-result` | POST | Paynow IPN handler |

## 💬 User Commands

Users can interact with the bot using these commands:

| Command | Description |
|---------|-------------|
| `cancel` | Cancel current session |
| `1` / `2` | Select options from menu |
| `confirm` | Confirm payment details |
| `edit` | Edit payment details |
| `check` | Check payment status |

### Admin Commands

Admin users have access to additional commands:

| Command | Description |
|---------|-------------|
| `/admin` | Show admin help menu |
| `/report pdf` | Generate PDF report |
| `/report excel` | Generate Excel report |
| `/approve [id]` | Approve a transaction |
| `/stats` | View system statistics |

## 🏗️ Architecture

### Resilience Patterns

```
┌─────────────────────────────────────────────────────────┐
│                     Rate Limiter                         │
│              (Token Bucket - 30 req/user)               │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                  Circuit Breaker                         │
│        (5 failures = OPEN, 60s recovery)                │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                 Retry with Backoff                       │
│         (3 retries, exponential delay)                  │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │  External APIs  │
              │  (WhatsApp,     │
              │   Paynow)       │
              └─────────────────┘
```

### Message Flow

```
WhatsApp → Webhook → Validation → Session Check → Flow Handler → Response
              │                        │               │
              ▼                        ▼               ▼
         Signature              Load/Create        Payment/
         Verification           Session           Registration
```

## 🔧 Configuration

### Feature Flags

Toggle features via environment variables:

```env
ENABLE_REGISTRATION=true    # Enable registration flow
ENABLE_DONATIONS=true       # Enable donation flow
ENABLE_META_FLOWS=true      # Enable encrypted Meta flows
ENABLE_WEBHOOK_VERIFICATION=true  # Require signature verification
DEBUG=false                 # Enable debug mode
```

### Payment Limits

Configure in `services/config.py`:

```python
max_amount: float = 480.0   # Maximum per transaction
min_amount: float = 1.0     # Minimum per transaction
```

## 📊 Monitoring

### Health Check Response

```json
{
  "status": "healthy",
  "timestamp": "2026-01-01T18:00:00",
  "components": {
    "payment_service": {"circuit_state": "closed"},
    "whatsapp_service": {"circuit_state": "closed"},
    "rate_limiter": {"enabled": true, "max_tokens": 30}
  },
  "metrics": {
    "total_requests": 1234,
    "successful_requests": 1200,
    "failed_requests": 34,
    "avg_response_time_ms": 45.2
  }
}
```

## 🚢 Deployment

### Railway

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login and deploy
railway login
railway deploy
```

### Docker

```bash
# Build image
docker build -t latterpay .

# Run container
docker run -p 8010:8010 --env-file .env latterpay
```

### Heroku

```bash
heroku create latterpay
heroku config:set $(cat .env | xargs)
git push heroku Dev:main
```

## 🧪 Testing

```bash
# Run syntax checks
python -m py_compile app.py
python -m py_compile services/*.py

# Run with debug logging
DEBUG=true python app.py
```

## 📝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👨‍💻 Author

**Nyasha Mapetere**
- Email: mapeterenyasha@gmail.com
- GitHub: [@Mapetere](https://github.com/Mapetere)

## 🙏 Acknowledgments

- [Pygwan](https://github.com/pygwan) - WhatsApp API wrapper
- [Paynow](https://paynow.co.zw) - Payment gateway
- [Flask](https://flask.palletsprojects.com/) - Web framework
- Runde Rural Clinic Project - Inspiration

---

<p align="center">
  Made with ❤️ for the Runde Rural Clinic Project
</p>
