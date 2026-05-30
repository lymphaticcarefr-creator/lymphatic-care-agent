"""
Client Brevo API — Lymphatic Care Agent
Gère les contacts, listes et séquences email automatiques.
"""

import httpx
from loguru import logger
from config import config
from models.lead import Classification, ScoringResult


BREVO_BASE_URL = "https://api.brevo.com/v3"

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "api-key": config.BREVO_API_KEY,
}

# Mapping classification → liste Brevo
LIST_MAP = {
    Classification.HOT: config.BREVO_LIST_HOT,
    Classification.WARM: config.BREVO_LIST_WARM,
    Classification.COLD: config.BREVO_LIST_COLD,
    Classification.DISQUALIFIED: config.BREVO_LIST_DISQUALIFIED,
}


async def create_or_update_contact(result: ScoringResult) -> bool:
    """
    Crée ou met à jour un contact dans Brevo
    avec tous les attributs Lymphatic Care.
    """
    payload = {
        "email": result.email,
        "attributes": {
            "PRENOM": result.prenom,
            "NOM": result.nom,
            "SMS": result.telephone or "",
            "SCORE_LEAD": result.scores.total,
            "CLASSIFICATION": result.classification.value,
            "SOURCE_LEAD": result.source.value,
            "ZONE_GEO": result.region_detectee or "",
            "PROFESSION": result.profession_detectee or "",
            "CONFIANCE": result.confiance.value,
        },
        "listIds": [LIST_MAP.get(result.classification, config.BREVO_LIST_COLD)],
        "updateEnabled": True,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BREVO_BASE_URL}/contacts",
                json=payload,
                headers=HEADERS,
                timeout=30.0,
            )
            if response.status_code in (200, 201):
                logger.info(f"Contact Brevo créé/mis à jour : {result.email}")
                return True
            else:
                logger.error(f"Erreur Brevo contact : {response.status_code} — {response.text}")
                return False

    except Exception as e:
        logger.error(f"Exception Brevo create_contact : {e}")
        return False


async def trigger_automation(result: ScoringResult) -> bool:
    """
    Déclenche la bonne séquence email selon la classification.
    WARM → séquence nurturing (J+0/J+2/J+5/J+7)
    COLD → séquence cold (30 jours)
    """
    automation_id = None

    if result.classification == Classification.WARM:
        automation_id = config.BREVO_AUTOMATION_NURTURING
    elif result.classification == Classification.COLD:
        automation_id = config.BREVO_AUTOMATION_COLD

    if not automation_id:
        logger.info(f"Pas d'automation à déclencher pour {result.classification}")
        return True

    payload = {
        "event": "lead_qualifié",
        "email": result.email,
        "properties": {
            "classification": result.classification.value,
            "score": result.scores.total,
            "profession": result.profession_detectee or "",
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BREVO_BASE_URL}/trackEvent",
                json=payload,
                headers=HEADERS,
                timeout=30.0,
            )
            if response.status_code == 204:
                logger.info(f"Automation Brevo déclenchée pour {result.email}")
                return True
            else:
                logger.error(f"Erreur Brevo automation : {response.status_code}")
                return False

    except Exception as e:
        logger.error(f"Exception Brevo trigger_automation : {e}")
        return False


async def send_transactional_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
) -> bool:
    """Envoie un email transactionnel via Brevo."""
    payload = {
        "sender": {
            "name": config.BREVO_SENDER_NAME,
            "email": config.BREVO_SENDER_EMAIL,
        },
        "to": [{"email": to_email, "name": to_name}],
        "subject": subject,
        "htmlContent": html_content,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BREVO_BASE_URL}/smtp/email",
                json=payload,
                headers=HEADERS,
                timeout=30.0,
            )
            if response.status_code == 201:
                logger.info(f"Email envoyé à {to_email} : {subject}")
                return True
            else:
                logger.error(f"Erreur email Brevo : {response.status_code} — {response.text}")
                return False

    except Exception as e:
        logger.error(f"Exception Brevo send_email : {e}")
        return False


async def send_template_email(
    to_email: str,
    to_name: str,
    template_id: int,
    params: dict | None = None,
) -> bool:
    """
    Envoie un email via un template Brevo (éditable dans Brevo UI).
    Le sujet et le contenu sont gérés dans Brevo.
    `params` sont passés dans la balise {{params.X}} du template.
    """
    if not template_id:
        logger.warning(f"send_template_email : template_id vide pour {to_email}")
        return False

    payload = {
        "to": [{"email": to_email, "name": to_name}],
        "templateId": int(template_id),
        "params": params or {},
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BREVO_BASE_URL}/smtp/email",
                json=payload,
                headers=HEADERS,
                timeout=30.0,
            )
            if response.status_code == 201:
                logger.info(f"Email template {template_id} envoyé à {to_email}")
                return True
            else:
                logger.error(f"Erreur email template Brevo : {response.status_code} — {response.text}")
                return False

    except Exception as e:
        logger.error(f"Exception Brevo send_template_email : {e}")
        return False
