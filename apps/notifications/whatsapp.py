import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WhatsAppNotConfigured(Exception):
    pass


class WhatsAppError(Exception):
    """A failed send. `retriable` tells the outbox whether trying again can help."""

    def __init__(self, message, *, retriable, status_code=None, code=None):
        super().__init__(message)
        self.retriable = retriable
        self.status_code = status_code
        self.code = code


def is_configured():
    return bool(
        settings.WHATSAPP_ACCESS_TOKEN
        and settings.WHATSAPP_PHONE_NUMBER_ID
        and settings.WHATSAPP_API_VERSION
    )


def send_template(*, to_phone, template_name, params, language=None):
    """Send an approved template message. Returns the Meta message id (wamid...)."""
    if not is_configured():
        raise WhatsAppNotConfigured("WhatsApp is not configured.")

    url = (
        f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}"
        f"/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language or settings.WHATSAPP_TEMPLATE_LANGUAGE},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in params],
                }
            ],
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=settings.WHATSAPP_TIMEOUT)
    except requests.RequestException as exc:
        raise WhatsAppError(f"Network error: {type(exc).__name__}", retriable=True) from None

    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}

    if response.status_code == 200:
        messages = body.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict) and messages[0].get("id"):
            return str(messages[0]["id"])
        # Accepted but no id: the message may have been sent, so do not retry (avoid duplicates).
        raise WhatsAppError("Unexpected API response (no message id)", retriable=False, status_code=200)

    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = error.get("code")
    message = str(error.get("message") or "no details")[:300]
    retriable = response.status_code == 429 or response.status_code >= 500
    raise WhatsAppError(
        f"HTTP {response.status_code} code {code}: {message}",
        retriable=retriable,
        status_code=response.status_code,
        code=code,
    )