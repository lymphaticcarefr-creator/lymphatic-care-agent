"""
Nurture Engine — Lymphatic Care Agent

Query les bases Notion Tièdes + Froids, calcule pour chaque lead le délai
écoulé depuis la "Date candidature", et envoie l'email Brevo correspondant
à l'étape de la séquence WARM ou COLD.

Appelé par /campaigns/nurture, planifié quotidiennement via cron.
"""

import asyncio
import httpx
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from config import config
from integrations.brevo import send_template_email


# Mapping (classification, days_since) → Brevo template ID
# Modifiable dans .env. Contenu des emails éditable directement dans Brevo UI.
WARM_TEMPLATE_MAP = {
    0: config.BREVO_TPL_WARM_J0,
    2: config.BREVO_TPL_WARM_J2,
    5: config.BREVO_TPL_WARM_J5,
    7: config.BREVO_TPL_WARM_J7,
}
COLD_TEMPLATE_MAP = {
    0: config.BREVO_TPL_COLD_J0,
    10: config.BREVO_TPL_COLD_J10,
    20: config.BREVO_TPL_COLD_J20,
    30: config.BREVO_TPL_COLD_J30,
}
WARM_MAX_DAY = max(WARM_TEMPLATE_MAP.keys())
COLD_MAX_DAY = max(COLD_TEMPLATE_MAP.keys())


def _get_template_id(classification: str, days_since: int) -> Optional[int]:
    """Retourne l'ID template Brevo pour (classification, jours)."""
    if classification == "WARM":
        return WARM_TEMPLATE_MAP.get(days_since) or None
    if classification == "COLD":
        return COLD_TEMPLATE_MAP.get(days_since) or None
    return None


NOTION_API = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {config.NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _days_since(iso_date: str) -> Optional[int]:
    """Retourne le nombre de jours écoulés depuis une date ISO."""
    if not iso_date:
        return None
    try:
        # Accepte format "2026-05-27" ou "2026-05-27T12:00:00.000Z"
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return delta.days
    except Exception as e:
        logger.warning(f"Date invalide '{iso_date}': {e}")
        return None


async def _query_notion_db(db_id: str) -> list[dict]:
    """Query une DB Notion et retourne toutes les pages."""
    if not db_id:
        return []
    results = []
    payload = {"page_size": 100}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{NOTION_API}/databases/{db_id}/query",
                json=payload,
                headers=NOTION_HEADERS,
            )
            if r.status_code != 200:
                logger.error(f"Notion query DB {db_id}: {r.status_code} {r.text[:200]}")
                return []
            results = r.json().get("results", [])
    except Exception as e:
        logger.error(f"Exception query Notion DB {db_id}: {e}")
    return results


def _get_prop(page: dict, name: str) -> Optional[str]:
    """Extrait la valeur texte d'une propriété Notion."""
    p = page.get("properties", {}).get(name, {})
    t = p.get("type")
    if t == "title":
        arr = p.get("title", [])
        return arr[0]["plain_text"] if arr else None
    if t == "rich_text":
        arr = p.get("rich_text", [])
        return arr[0]["plain_text"] if arr else None
    if t == "email":
        return p.get("email")
    if t == "select":
        sel = p.get("select")
        return sel.get("name") if sel else None
    if t == "date":
        d = p.get("date")
        return d.get("start") if d else None
    if t == "number":
        return p.get("number")
    return None


async def _update_notion_step(page_id: str, step_prop: str, step_value: str) -> bool:
    """Met à jour la propriété d'étape (Étape nurturing / Étape cold) sur une page."""
    payload = {
        "properties": {
            step_prop: {"select": {"name": step_value}},
        }
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.patch(
                f"{NOTION_API}/pages/{page_id}",
                json=payload,
                headers=NOTION_HEADERS,
            )
            if r.status_code != 200:
                logger.error(f"Notion update step {page_id}: {r.status_code} {r.text[:200]}")
                return False
            return True
    except Exception as e:
        logger.error(f"Exception update Notion step: {e}")
        return False


async def _process_lead(page: dict, classification: str, step_prop: str) -> dict:
    """Traite un lead : check délai, envoie email si dû, met à jour étape Notion."""
    page_id = page["id"]
    prenom = _get_prop(page, "Prénom") or "soignant(e)"
    nom = _get_prop(page, "Nom") or ""
    email = _get_prop(page, "Email")
    date_cand = _get_prop(page, "Date candidature")
    current_step = _get_prop(page, step_prop)

    if not email:
        logger.info(f"Lead {prenom} sans email, skip")
        return {"page_id": page_id, "status": "skip_no_email"}

    days = _days_since(date_cand)
    if days is None:
        logger.info(f"Lead {email} sans date candidature, skip")
        return {"page_id": page_id, "status": "skip_no_date", "email": email}

    template_id = _get_template_id(classification, days)
    if not template_id:
        return {"page_id": page_id, "status": "no_email_today", "email": email, "days": days}

    target_step = f"J+{days}"

    # Vérifie si déjà envoyé (current_step >= target_step)
    if current_step == target_step or current_step in ("Terminé", "Archivé", "Basculé HOT", "Basculé COLD", "Re-qualifié"):
        return {"page_id": page_id, "status": "already_sent", "email": email, "step": current_step}

    # Envoie l'email via template Brevo
    success = await send_template_email(
        to_email=email,
        to_name=f"{prenom} {nom}".strip(),
        template_id=template_id,
        params={"prenom": prenom, "nom": nom},
    )
    if not success:
        logger.error(f"Email échoué pour {email} (J+{days}, tpl={template_id})")
        return {"page_id": page_id, "status": "email_failed", "email": email, "days": days}

    # Met à jour Notion
    max_day = WARM_MAX_DAY if classification == "WARM" else COLD_MAX_DAY
    final_step = "Terminé" if days >= max_day else target_step
    await _update_notion_step(page_id, step_prop, final_step)

    logger.info(f"Email {classification} J+{days} envoyé à {email}")
    return {"page_id": page_id, "status": "sent", "email": email, "days": days, "step": final_step}


async def run_nurture_cycle() -> dict:
    """
    Point d'entrée : parcourt les DBs Tièdes + Froids et envoie les emails dus.
    Retourne un résumé.
    """
    logger.info("📬 Démarrage cycle nurturing")
    summary = {"warm": [], "cold": []}

    # WARM (Tièdes)
    if config.NOTION_DB_WARM:
        warm_pages = await _query_notion_db(config.NOTION_DB_WARM)
        logger.info(f"WARM : {len(warm_pages)} leads à traiter")
        for page in warm_pages:
            res = await _process_lead(page, "WARM", "Étape nurturing")
            summary["warm"].append(res)

    # COLD (Froids)
    if config.NOTION_DB_COLD:
        cold_pages = await _query_notion_db(config.NOTION_DB_COLD)
        logger.info(f"COLD : {len(cold_pages)} leads à traiter")
        for page in cold_pages:
            res = await _process_lead(page, "COLD", "Étape cold")
            summary["cold"].append(res)

    sent = sum(1 for r in summary["warm"] + summary["cold"] if r.get("status") == "sent")
    logger.success(f"✅ Cycle nurturing terminé : {sent} emails envoyés")
    summary["total_sent"] = sent
    return summary
