"""
Client Notion API — Lymphatic Care Agent
Crée et met à jour les fiches leads dans Notion.
"""

import httpx
from datetime import datetime
from loguru import logger
from config import config
from models.lead import Classification, ScoringResult


NOTION_BASE_URL = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {config.NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Mapping classification → base Notion
DB_MAP = {
    Classification.HOT: config.NOTION_DB_HOT,
    Classification.WARM: config.NOTION_DB_WARM,
    Classification.COLD: config.NOTION_DB_COLD,
}


async def create_lead_card(result: ScoringResult) -> str | None:
    """
    Crée une fiche lead dans la base Notion correspondante.
    Retourne l'ID de la page créée ou None si erreur.
    """
    database_id = DB_MAP.get(result.classification)

    if not database_id:
        logger.info(f"Pas de base Notion pour {result.classification} — pas de fiche créée")
        return None

    # Construction des propriétés Notion
    properties = {
        "Prénom": {"title": [{"text": {"content": result.prenom}}]},
        "Nom": {"rich_text": [{"text": {"content": result.nom}}]},
        "Email": {"email": result.email},
        "Profession": {"select": {"name": result.profession_detectee or "Non précisé"}},
        "Score": {"number": result.scores.total},
        "Classification": {"select": {"name": result.classification.value}},
        "Source": {"select": {"name": result.source.value}},
        "Région": {"rich_text": [{"text": {"content": result.region_detectee or "Non précisée"}}]},
        "Confiance": {"select": {"name": result.confiance.value}},
        "Statut": {"select": {"name": "Nouveau"}},
        "Date candidature": {"date": {"start": datetime.now().isoformat()}},
    }

    # Ajout téléphone si présent
    if result.telephone:
        properties["Téléphone"] = {
            "phone_number": result.telephone
        }

    # Ajout signaux positifs
    if result.signaux_positifs:
        properties["Signaux positifs"] = {
            "rich_text": [{"text": {"content": "\n".join(result.signaux_positifs)}}]
        }

    # Brief Franck (HOT uniquement)
    if result.brief_franck and result.classification == Classification.HOT:
        properties["Angle closing"] = {
            "rich_text": [{"text": {"content": result.brief_franck.angle_closing}}]
        }
        properties["Objection probable"] = {
            "rich_text": [{"text": {"content": result.brief_franck.objection_probable}}]
        }

    # Notes
    if result.notes:
        properties["Notes Franck"] = {
            "rich_text": [{"text": {"content": result.notes}}]
        }

    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{NOTION_BASE_URL}/pages",
                json=payload,
                headers=HEADERS,
                timeout=30.0,
            )
            if response.status_code == 200:
                page_id = response.json().get("id", "")
                logger.info(f"Fiche Notion créée : {page_id} pour {result.email}")
                return page_id
            else:
                logger.error(f"Erreur Notion : {response.status_code} — {response.text}")
                return None

    except Exception as e:
        logger.error(f"Exception Notion create_lead_card : {e}")
        return None


async def update_status(page_id: str, statut: str) -> bool:
    """Met à jour le statut d'une fiche Notion."""
    payload = {
        "properties": {
            "Statut": {"select": {"name": statut}}
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{NOTION_BASE_URL}/pages/{page_id}",
                json=payload,
                headers=HEADERS,
                timeout=30.0,
            )
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Exception Notion update_status : {e}")
        return False
