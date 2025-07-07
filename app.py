import os
import json
import base64
import logging
from flask import Flask, request, jsonify
from Crypto.Cipher import AES as CryptoAES
from Crypto.Util.Padding import pad, unpad
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('whatsapp_decryption.log')
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
PRIVATE_KEY_FILE = os.getenv('PRIVATE_KEY_FILE', 'private.pem')
PRIVATE_KEY_PASSPHRASE = os.getenv('PRIVATE_KEY_PASSPHRASE')

class WhatsAppDecryptor:
    """Handles WhatsApp message decryption with robust padding handling"""
    
    @staticmethod
    def decrypt_aes_key(encrypted_key_b64: str) -> bytes:
        """Decrypt the AES key using RSA private key"""
        try:
            encrypted_key = base64.b64decode(encrypted_key_b64)
            with open(PRIVATE_KEY_FILE, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=PRIVATE_KEY_PASSPHRASE.encode() if PRIVATE_KEY_PASSPHRASE else None,
                    backend=default_backend()
                )
            return private_key.decrypt(
                encrypted_key,
                asym_padding.OAEP(
                    mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
        except Exception as e:
            logger.error(f"AES key decryption failed: {str(e)}")
            raise ValueError("Failed to decrypt AES key") from e

    @staticmethod
    def handle_malformed_data(encrypted_data: bytes) -> bytes:
        """Attempt to fix malformed encrypted data"""
        original_length = len(encrypted_data)
        if original_length % 16 == 0:
            return encrypted_data
            
        # Calculate required padding
        pad_len = 16 - (original_length % 16)
        logger.warning(f"Attempting to fix malformed data. Original length: {original_length}, Adding {pad_len} bytes")
        
        # Try common padding approaches
        attempts = [
            bytes([pad_len] * pad_len),  # PKCS7 style
            b'\x80' + bytes([0]*(pad_len-1)),  # ISO7816 style
            bytes([0] * pad_len)  # Zero padding
        ]
        
        for padding in attempts:
            try:
                fixed_data = encrypted_data + padding
                return fixed_data
            except Exception as e:
                continue
                
        raise ValueError("Could not fix malformed data")

    @staticmethod
    def decrypt_flow_data(encrypted_data_b64: str, aes_key: bytes, iv_b64: str) -> str:
        """Decrypt WhatsApp flow data with automatic padding correction"""
        try:
            # Clean and decode inputs
            encrypted_data = base64.b64decode(encrypted_data_b64.strip())
            iv = base64.b64decode(iv_b64.strip())

            # Validate lengths
            if len(aes_key) not in [16, 24, 32]:
                raise ValueError(f"Invalid AES key length: {len(aes_key)} bytes")
            if len(iv) != 16:
                raise ValueError(f"Invalid IV length: {len(iv)} bytes")

            # Handle potentially malformed data
            try:
                cipher = CryptoAES.new(aes_key, CryptoAES.MODE_CBC, iv)
                decrypted = cipher.decrypt(encrypted_data)
                return unpad(decrypted, CryptoAES.block_size).decode('utf-8')
            except ValueError as pad_error:
                logger.warning(f"Standard decryption failed: {str(pad_error)}. Attempting recovery...")
                fixed_data = WhatsAppDecryptor.handle_malformed_data(encrypted_data)
                cipher = CryptoAES.new(aes_key, CryptoAES.MODE_CBC, iv)
                decrypted = cipher.decrypt(fixed_data)
                return unpad(decrypted, CryptoAES.block_size).decode('utf-8')

        except Exception as e:
            logger.error(f"Decryption failed | Key: {aes_key.hex()[:6]}... | IV: {iv_b64[:10]}... | Data: {encrypted_data_b64[:20]}...")
            logger.error(f"Error details: {str(e)}", exc_info=True)
            raise ValueError(f"Decryption failed: {str(e)}")

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Main WhatsApp webhook endpoint"""
    try:
        if request.method == 'GET':
            # Verification handshake
            verify_token = request.args.get('hub.verify_token')
            if verify_token == os.getenv('VERIFY_TOKEN'):
                return request.args.get('hub.challenge'), 200
            return "Verification failed", 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        # Process encrypted flow data
        if all(key in data for key in ['encrypted_aes_key', 'encrypted_flow_data', 'initial_vector']):
            try:
                aes_key = WhatsAppDecryptor.decrypt_aes_key(data['encrypted_aes_key'])
                decrypted = WhatsAppDecryptor.decrypt_flow_data(
                    data['encrypted_flow_data'],
                    aes_key,
                    data['initial_vector']
                )
                
                # Process decrypted JSON
                flow_data = json.loads(decrypted)
                logger.info(f"Decrypted flow data: {flow_data}")
                
                # Handle different flow actions
                action = flow_data.get('action')
                if action == 'INIT':
                    return jsonify({"status": "Flow initialized"})
                elif action == 'data_exchange':
                    return jsonify({"status": "Success", "data": flow_data.get('data')})
                else:
                    return jsonify({"status": "Unknown action"}), 400

            except json.JSONDecodeError:
                return jsonify({"error": "Invalid JSON in decrypted data"}), 400
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}", exc_info=True)
                return jsonify({"error": "Internal server error"}), 500

        return jsonify({"status": "Unhandled message type"}), 200

    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    # Validate configuration
    if not os.path.exists(PRIVATE_KEY_FILE):
        raise FileNotFoundError(f"Private key file not found at {PRIVATE_KEY_FILE}")
    if not os.getenv('VERIFY_TOKEN'):
        raise EnvironmentError("VERIFY_TOKEN environment variable is required")

    # Start the server
    port = int(os.getenv('PORT', 8000))
    logger.info(f"Starting WhatsApp webhook service on port {port}")
    app.run(host='0.0.0.0', port=port)