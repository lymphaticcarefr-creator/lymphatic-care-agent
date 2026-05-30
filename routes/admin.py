"""
Endpoint admin temporaire — Lymphatic Care Agent.
Protege par X-Webhook-Secret. Permet d'executer des actions one-shot
qui doivent partir de l'IP du VPS (deja whitelistee chez Brevo).
"""
import json
from typing import Optional
import httpx
from fastapi import APIRouter, Header, HTTPException
from loguru import logger

from config import config
from prompts.nurture_templates import (
    WARM_J0, WARM_J2, WARM_J5, WARM_J7,
    COLD_J0, COLD_J10, COLD_J20, COLD_J30,
)


router = APIRouter()


TEMPLATES = [
    ("LC - WARM J+0 - Candidature recue", WARM_J0),
    ("LC - WARM J+2 - Pourquoi on a tout quitte", WARM_J2),
    ("LC - WARM J+5 - On peut en parler", WARM_J5),
    ("LC - WARM J+7 - La question que personne n'ose poser", WARM_J7),
    ("LC - COLD J+0 - Etude marche 2026", COLD_J0),
    ("LC - COLD J+10 - Pourquoi drainage explose", COLD_J10),
    ("LC - COLD J+20 - Encore en reflexion", COLD_J20),
    ("LC - COLD J+30 - Derniere chance", COLD_J30),
]


def _convert_placeholders(text: str) -> str:
    """Convertit {prenom} en {{params.prenom}} pour Brevo."""
    return text.replace("{prenom}", "{{params.prenom}}")


@router.post("/seed-brevo-templates")
async def seed_brevo_templates(x_webhook_secret: Optional[str] = Header(None)):
    """
    Cree les 8 templates Brevo (WARM J0/J2/J5/J7 + COLD J0/J10/J20/J30).
    A appeler UNE seule fois pour seed la base de templates.
    Retourne le mapping {key_env: template_id}.
    """
    if not config.WEBHOOK_SECRET or x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret invalide")

    if not config.BREVO_API_KEY:
        raise HTTPException(status_code=500, detail="BREVO_API_KEY manquante")

    results = []
    headers = {
        "api-key": config.BREVO_API_KEY,
        "content-type": "application/json",
        "accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for name, tpl in TEMPLATES:
            payload = {
                "sender": {
                    "name": config.BREVO_SENDER_NAME,
                    "email": config.BREVO_SENDER_EMAIL,
                },
                "templateName": name,
                "htmlContent": _convert_placeholders(tpl["html"]),
                "subject": _convert_placeholders(tpl["subject"]),
                "isActive": True,
            }
            try:
                resp = await client.post(
                    "https://api.brevo.com/v3/smtp/templates",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    tid = data.get("id")
                    logger.info(f"Template Brevo cree: {name} -> ID {tid}")
                    results.append({"name": name, "id": tid, "status": "ok"})
                else:
                    body = resp.text[:300]
                    logger.error(f"Echec template {name}: {resp.status_code} {body}")
                    results.append({"name": name, "id": None, "status": "error", "code": resp.status_code, "body": body})
            except Exception as e:
                logger.exception(f"Exception sur {name}")
                results.append({"name": name, "id": None, "status": "exception", "error": str(e)})

    keys = [
        "BREVO_TPL_WARM_J0", "BREVO_TPL_WARM_J2",
        "BREVO_TPL_WARM_J5", "BREVO_TPL_WARM_J7",
        "BREVO_TPL_COLD_J0", "BREVO_TPL_COLD_J10",
        "BREVO_TPL_COLD_J20", "BREVO_TPL_COLD_J30",
    ]
    env_mapping = {k: r["id"] for k, r in zip(keys, results)}

    return {
        "status": "ok" if all(r.get("id") for r in results) else "partial",
        "results": results,
        "env_mapping": env_mapping,
    }


@router.get("/list-brevo-templates")
async def list_brevo_templates(x_webhook_secret: Optional[str] = Header(None)):
    """Liste les templates Brevo deja crees (pour eviter doublons)."""
    if not config.WEBHOOK_SECRET or x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret invalide")
    headers = {"api-key": config.BREVO_API_KEY, "accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://api.brevo.com/v3/smtp/templates?templateStatus=true&limit=50",
            headers=headers,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text[:200])
        data = resp.json()
        templates = [
            {"id": t["id"], "name": t.get("name", ""), "subject": t.get("subject", "")[:80]}
            for t in data.get("templates", [])
        ]
        return {"count": len(templates), "templates": templates}
