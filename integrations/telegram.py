"""
Client Telegram Bot — Lymphatic Care Monitoring (@lymphaticcare_alert_bot)
Envoi d'alertes (leads WARM/HOT, alertes système, heartbeat).
Mode silencieux si TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID absent.
"""

import httpx
from loguru import logger
from config import config


TELEGRAM_API_BASE = "https://api.telegram.org"


async def send_message(text: str, parse_mode: str = "HTML", disable_preview: bool = True) -> bool:
    """
    Envoie un message Telegram au chat configuré.
    Retourne True si envoi OK, False si échec (loggé mais ne raise pas).
    """
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        logger.debug("Telegram non configuré (token/chat_id manquant) — message ignoré")
        return False

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],  # Telegram cap 4096 chars
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200 and r.json().get("ok"):
                return True
            logger.warning(f"Telegram send_message KO {r.status_code} : {r.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Telegram send_message exception : {e}")
        return False


async def health_check() -> bool:
    """Vérifie que le bot est joignable (getMe)."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{TELEGRAM_API_BASE}/bot{token}/getMe")
            return r.status_code == 200 and r.json().get("ok", False)
    except Exception:
        return False
