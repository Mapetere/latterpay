"""
AI-Powered Natural Language Understanding for LatterPay
========================================================
Uses OpenAI GPT for accurate intent and entity extraction.
Falls back to regex-based NLU if API fails.

Author: Nyasha Mapetere
Version: 1.0.0
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")  # Cheaper, fast model
OPENAI_ENABLED = bool(OPENAI_API_KEY)

# Import regex NLU as fallback
from services.smart_conversation import NaturalLanguageEngine, ParsedIntent

# Initialize regex fallback
regex_nlu = NaturalLanguageEngine()


@dataclass
class AIExtraction:
    """Structured extraction from AI."""
    intent: str = "unknown"
    amount: Optional[float] = None
    currency: Optional[str] = None
    purpose: Optional[str] = None
    name: Optional[str] = None
    congregation: Optional[str] = None
    confidence: float = 0.0
    raw_response: str = ""


# System prompt for OpenAI
SYSTEM_PROMPT = """You are a donation chatbot assistant for LatterPay, a church donation platform in Zimbabwe.

Your job is to extract information from user messages. Extract ONLY what the user explicitly mentions.

VALID PURPOSES (use exact names):
- Monthly Contributions
- August Conference
- Youth Conference
- Construction Contribution
- Pastoral Support

VALID CURRENCIES:
- USD (if they say dollars, usd, $)
- ZWG (if they say zwg, rtgs, zig, or Zimbabwe currency)

Respond with a JSON object containing ONLY the fields that are present in the message:
{
  "intent": "donate|register|help|cancel|greeting|check_status|unknown",
  "amount": number or null,
  "currency": "USD" or "ZWG" or null,
  "purpose": "exact purpose name" or null,
  "name": "person's name" or null,
  "congregation": "congregation/area name" or null
}

Be conservative - only extract what's clearly stated. Don't guess."""


def extract_with_openai(message: str) -> Optional[AIExtraction]:
    """
    Use OpenAI to extract intent and entities from user message.
    Returns None if API call fails.
    """
    if not OPENAI_ENABLED:
        logger.debug("OpenAI not configured, skipping")
        return None
    
    try:
        import requests
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Extract from this message: \"{message}\""}
                ],
                "temperature": 0.1,  # Low temperature for consistent extraction
                "max_tokens": 200
            },
            timeout=10
        )
        
        if response.status_code != 200:
            logger.warning(f"OpenAI API error: {response.status_code} - {response.text}")
            return None
        
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        
        # Parse JSON response
        # Handle code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        extracted = json.loads(content)
        
        logger.info(f"OpenAI extracted: {extracted}")
        
        return AIExtraction(
            intent=extracted.get("intent", "unknown"),
            amount=extracted.get("amount"),
            currency=extracted.get("currency"),
            purpose=extracted.get("purpose"),
            name=extracted.get("name"),
            congregation=extracted.get("congregation"),
            confidence=0.9,  # High confidence for AI
            raw_response=content
        )
        
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse OpenAI response: {e}")
        return None
    except requests.exceptions.Timeout:
        logger.warning("OpenAI request timed out")
        return None
    except Exception as e:
        logger.error(f"OpenAI extraction failed: {e}")
        return None


def extract_with_regex(message: str) -> AIExtraction:
    """
    Use regex-based NLU as fallback.
    Always returns a result.
    """
    parsed = regex_nlu.parse(message)
    
    return AIExtraction(
        intent=parsed.intent,
        amount=parsed.entities.get("amount"),
        currency=parsed.entities.get("currency"),
        purpose=parsed.entities.get("donation_type"),
        name=parsed.entities.get("name"),
        congregation=None,  # Regex doesn't extract this
        confidence=parsed.confidence,
        raw_response=""
    )


def smart_extract(message: str) -> AIExtraction:
    """
    Smart extraction: Try OpenAI first, fall back to regex.
    """
    # Try OpenAI first
    ai_result = extract_with_openai(message)
    
    if ai_result and ai_result.intent != "unknown":
        logger.debug(f"Using OpenAI extraction for: {message[:50]}...")
        return ai_result
    
    # Fall back to regex
    logger.debug(f"Falling back to regex for: {message[:50]}...")
    return extract_with_regex(message)


def to_session_entities(extraction: AIExtraction) -> Dict[str, Any]:
    """
    Convert AI extraction to session entities format.
    Only includes non-None values.
    """
    entities = {}
    
    if extraction.amount is not None:
        entities["amount"] = extraction.amount
    if extraction.currency:
        entities["currency"] = extraction.currency
    if extraction.purpose:
        entities["donation_type"] = extraction.purpose
    if extraction.name:
        entities["name"] = extraction.name
    if extraction.congregation:
        entities["region"] = extraction.congregation
    
    return entities


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'AIExtraction',
    'smart_extract',
    'extract_with_openai',
    'extract_with_regex',
    'to_session_entities',
    'OPENAI_ENABLED',
]
