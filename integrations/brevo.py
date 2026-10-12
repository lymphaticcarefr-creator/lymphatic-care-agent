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


def _is_indeed_relay_address(email: str) -> bool:
    """Detecte les addresses anonymisees Indeed (qui ne sont pas de vraies BAL)."""
    e = (email or "").lower()
    return (
        "@indeedemail.com" in e
        or "@indeed.com" in e
        or "@indeedapply.com" in e
    )

# Mapping classification → liste Brevo
LIST_MAP = {
    Classification.HOT: config.BREVO_LIST_HOT,
    Classification.WARM: config.BREVO_LIST_WARM,
    Classification.COLD: config.BREVO_LIST_COLD,
    Classification.DISQUALIFIED: config.BREVO_LIST_DISQUALIFIED,
}


def _fr_phone_e164(raw) -> str:
    """Normalise un numero FR en E.164 (+33...) pour Brevo. '' si invalide/absent."""
    import re as _re
    if not raw:
        return ""
    d = _re.sub(r"[^0-9+]", "", str(raw))
    if d.startswith("+33"):
        rest = _re.sub(r"[^0-9]", "", d[3:])
        return "+33" + rest if 9 <= len(rest) <= 10 else ""
    if d.startswith("0033"):
        rest = _re.sub(r"[^0-9]", "", d[4:])
        return "+33" + rest if len(rest) == 9 else ""
    digits = _re.sub(r"[^0-9]", "", d)
    if len(digits) == 10 and digits[0] == "0":
        return "+33" + digits[1:]
    if len(digits) == 9 and digits[0] in "67":
        return "+33" + digits
    return ""


async def create_or_update_contact(result: ScoringResult) -> bool:
    """
    Crée ou met à jour un contact dans Brevo
    avec tous les attributs Lymphatic Care.
    """
    if _is_indeed_relay_address(result.email):
        logger.info(f"Skip Brevo contact (adresse relais Indeed): {result.email}")
        return True
    payload = {
        "email": result.email,
        "attributes": {
            "PRENOM": result.prenom,
            "NOM": result.nom,
            "SMS": _fr_phone_e164(result.telephone),
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
    Envoie IMMEDIATEMENT le mail J+0 de la sequence (WARM ou COLD) des la reception
    du lead, et marque l'etape dans Notion pour que le cron quotidien enchaine sur
    J+2 / J+5 / J+7 (WARM) ou J+10 / J+20 / J+30 (COLD).
    """
    if result.classification == Classification.WARM:
        tpl = config.BREVO_TPL_WARM_J0
        step_prop = "\u00c9tape nurturing"
    elif result.classification == Classification.COLD:
        tpl = config.BREVO_TPL_COLD_J0
        step_prop = "\u00c9tape cold"
    else:
        return True

    if not tpl:
        logger.info(f"Pas de template J+0 configure pour {result.classification}")
        return True

    ok = await send_template_email(
        to_email=result.email,
        to_name=f"{result.prenom} {result.nom}".strip(),
        template_id=int(tpl),
        params={"prenom": result.prenom, "nom": result.nom},
    )

    if ok:
        try:
            from integrations.notion import _find_card_by_email
            pid = await _find_card_by_email(result.email)
            if pid:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    await client.patch(
                        f"https://api.notion.com/v1/pages/{pid}",
                        json={"properties": {step_prop: {"select": {"name": "J+0"}}}},
                        headers={
                            "Authorization": f"Bearer {config.NOTION_API_KEY}",
                            "Notion-Version": "2022-06-28",
                            "Content-Type": "application/json",
                        },
                    )
        except Exception as e:
            logger.error(f"Maj etape J+0 Notion echouee pour {result.email}: {e}")

    logger.info(f"Nurture J+0 instantane ({result.classification.value}) -> {result.email}: {ok}")
    return ok


async def send_transactional_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
) -> bool:
    """Envoie un email transactionnel via Brevo."""
    if _is_indeed_relay_address(to_email):
        logger.warning(
            f"Skip envoi email a adresse relais Indeed ({to_email}) — sujet: {subject}"
        )
        return True
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

    if _is_indeed_relay_address(to_email):
        logger.warning(
            f"Skip envoi template {template_id} a adresse relais Indeed ({to_email})"
        )
        return True

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
