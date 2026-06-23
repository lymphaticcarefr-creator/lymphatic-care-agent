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
# Les disqualifies sont aussi traces dans la base Froids (avec Statut "Perdu") afin
# de garder un historique complet et eviter de re-traiter le meme lead.
DB_MAP = {
    Classification.HOT: config.NOTION_DB_HOT,
    Classification.WARM: config.NOTION_DB_WARM,
    Classification.COLD: config.NOTION_DB_COLD,
    Classification.DISQUALIFIED: config.NOTION_DB_COLD,
}


_DB_PROPS_CACHE: dict[str, set] = {}


async def _db_props(database_id: str) -> set:
    """Retourne l'ensemble des noms de propriétés réellement présents dans une
    base Notion (avec cache). Sert à n'envoyer que des colonnes existantes,
    pour être robuste aux renommages/suppressions côté Notion."""
    if database_id in _DB_PROPS_CACHE:
        return _DB_PROPS_CACHE[database_id]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{NOTION_BASE_URL}/databases/{database_id}", headers=HEADERS)
            if r.status_code == 200:
                props = set(r.json().get("properties", {}).keys())
                _DB_PROPS_CACHE[database_id] = props
                return props
    except Exception as e:
        logger.warning(f"Lecture schéma Notion échouée ({e})")
    return set()


async def _find_existing_card(prenom: str, nom: str) -> str | None:
    """Cherche une fiche lead existante (non archivée) pour ce candidat dans les
    bases Tièdes/Chauds/Froids, par Prénom + Nom. Sert à éviter les doublons
    (un candidat envoie souvent 2 emails : 'candidature' + 'message')."""
    prenom = (prenom or "").strip()
    nom = (nom or "").strip()
    if not prenom and not nom:
        return None
    # Ne pas dédupliquer les fiches au nom générique de secours
    if prenom.lower() == "candidat" and nom.lower() == "indeed":
        return None
    flt = {"and": [
        {"property": "Prénom", "title": {"equals": prenom}},
        {"property": "Nom", "rich_text": {"equals": nom}},
    ]}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for db in (config.NOTION_DB_WARM, config.NOTION_DB_HOT, config.NOTION_DB_COLD):
                if not db:
                    continue
                r = await client.post(
                    f"{NOTION_BASE_URL}/databases/{db}/query",
                    json={"filter": flt, "page_size": 1},
                    headers=HEADERS,
                )
                if r.status_code == 200 and r.json().get("results"):
                    return r.json()["results"][0].get("id")
    except Exception as e:
        logger.warning(f"Dédup Notion : recherche échouée ({e}) — création quand même")
    return None


async def create_lead_card(result: ScoringResult) -> str | None:
    """
    Crée une fiche lead dans la base Notion correspondante.
    Retourne l'ID de la page créée ou None si erreur.
    """
    database_id = DB_MAP.get(result.classification)

    if not database_id:
        logger.info(f"Pas de base Notion pour {result.classification} — pas de fiche créée")
        return None

    # Anti-doublon : si le candidat a déjà une fiche, on n'en recrée pas
    existing = await _find_existing_card(result.prenom, result.nom)
    if existing:
        logger.info(f"Fiche déjà existante pour {result.prenom} {result.nom} — doublon évité ({existing})")
        return existing

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
        # Disqualifies = Statut "Perdu" pour les distinguer dans Froids
        "Statut": {
            "select": {
                "name": "Perdu" if result.classification == Classification.DISQUALIFIED else "Nouveau"
            }
        },
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

    # Colonnes réellement présentes dans la base (robustesse aux renommages)
    valid = await _db_props(database_id)

    # Notes : la colonne peut s'appeler différemment selon la base
    # (ex. Tièdes = "Notes Franck & Emilie", Froids/Chauds = "Notes Franck")
    if result.notes:
        for nk in ("Notes Franck", "Notes Franck & Emilie", "Notes"):
            if not valid or nk in valid:
                properties[nk] = {"rich_text": [{"text": {"content": result.notes}}]}
                break

    # Ne garder que les propriétés qui existent vraiment → évite les 400
    if valid:
        properties = {k: v for k, v in properties.items() if k in valid}

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
