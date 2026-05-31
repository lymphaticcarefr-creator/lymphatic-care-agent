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


@router.get("/version")
async def version_info(x_webhook_secret: Optional[str] = Header(None)):
    """Retourne le SHA du commit git deploye + verifie patches actifs."""
    if not config.WEBHOOK_SECRET or x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret invalide")
    import subprocess, os
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd="/app").decode().strip()[:12]
        msg = subprocess.check_output(["git", "log", "-1", "--pretty=%s"], cwd="/app").decode().strip()
    except Exception as e:
        sha = f"ERR: {e}"
        msg = ""
    # Verifie si l'override WARM minimum est dans le code
    from agents.scoring import ScoringEngine
    has_override = hasattr(ScoringEngine, "classifier_with_profession_check")
    src = ""
    try:
        with open("/app/agents/scoring.py") as f:
            src = f.read()
    except: pass
    has_warm_min = "Override WARM" in src
    has_dq_override = "Override DQ" in src
    return {
        "git_sha": sha,
        "git_last_msg": msg,
        "has_method_classifier_with_profession_check": has_override,
        "has_override_WARM_minimum": has_warm_min,
        "has_override_DQ": has_dq_override,
    }


@router.post("/debug-extract")
async def debug_extract(payload: dict, x_webhook_secret: Optional[str] = Header(None)):
    """Debug: appelle le LLM extraction + scoring sans aucun override, retourne tout."""
    if not config.WEBHOOK_SECRET or x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret invalide")
    from integrations.llm import llm_client
    from prompts.indeed_prompt import SYSTEM_PROMPT_INDEED, build_user_prompt
    from routes.webhook_indeed import EXTRACT_PROMPT_INDEED, _clean_html
    from models.lead import LeadIndeed
    body = payload.get("body_text") or _clean_html(payload.get("body_html", ""))
    raw = await llm_client.score(
        system=EXTRACT_PROMPT_INDEED,
        user=f"OBJET : {payload.get('subject','')}\n\nCORPS EMAIL :\n{body[:8000]}",
        temperature=0.0,
    )
    extracted = await llm_client.parse_json_response(raw)
    if not extracted or not all(extracted.get(k) for k in ["prenom", "nom", "email"]):
        return {"step": "extract", "raw": raw[:500], "extracted": extracted}
    lead = LeadIndeed(
        prenom=extracted["prenom"][:100],
        nom=extracted["nom"][:100],
        email=extracted["email"][:200],
        telephone=extracted.get("telephone"),
        lettre_motivation=extracted.get("lettre_motivation") or "(aucune lettre)",
        reponse_q1_profession=extracted.get("reponse_q1_profession"),
        reponse_q2_situation=extracted.get("reponse_q2_situation"),
        reponse_q3_region=extracted.get("reponse_q3_region"),
        reponse_q4_motivation=extracted.get("reponse_q4_motivation"),
    )
    raw_score = await llm_client.score(
        system=SYSTEM_PROMPT_INDEED,
        user=build_user_prompt(lead),
        temperature=0.2,
    )
    scoring_data = await llm_client.parse_json_response(raw_score)
    return {
        "step": "full",
        "extracted": extracted,
        "scoring_data": scoring_data,
        "raw_score_500": raw_score[:500],
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


@router.post("/send-brevo-template")
async def send_brevo_template(body: dict, x_webhook_secret: Optional[str] = Header(None)):
    """Envoie un template Brevo via API. body = {template_id, to_email, to_name, params}."""
    if not config.WEBHOOK_SECRET or x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret invalide")
    headers = {"api-key": config.BREVO_API_KEY, "accept": "application/json", "content-type": "application/json"}
    payload = {
        "to": [{"email": body.get("to_email"), "name": body.get("to_name", "")}],
        "templateId": int(body.get("template_id")),
        "params": body.get("params", {}),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers)
        return {"status": resp.status_code, "body": resp.text[:300]}


@router.put("/update-brevo-template/{template_id}")
async def update_brevo_template(template_id: int, body: dict, x_webhook_secret: Optional[str] = Header(None)):
    """Met a jour subject + htmlContent d'un template Brevo. body = {subject, htmlContent}."""
    if not config.WEBHOOK_SECRET or x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret invalide")
    headers = {"api-key": config.BREVO_API_KEY, "accept": "application/json", "content-type": "application/json"}
    payload = {
        "sender": {"name": config.BREVO_SENDER_NAME, "email": config.BREVO_SENDER_EMAIL},
        "subject": body.get("subject", ""),
        "htmlContent": body.get("htmlContent", ""),
        "isActive": True,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(
            f"https://api.brevo.com/v3/smtp/templates/{template_id}",
            json=payload, headers=headers,
        )
        return {"status": resp.status_code, "body": resp.text[:300]}


@router.get("/get-brevo-template/{template_id}")
async def get_brevo_template(template_id: int, x_webhook_secret: Optional[str] = Header(None)):
    """Retourne le contenu complet d'un template Brevo (sender, subject, htmlContent)."""
    if not config.WEBHOOK_SECRET or x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret invalide")
    headers = {"api-key": config.BREVO_API_KEY, "accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.brevo.com/v3/smtp/templates/{template_id}",
            headers=headers,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text[:200])
        t = resp.json()
        # Nettoie HTML pour retour compact (strip tags + whitespace)
        import re
        html = t.get("htmlContent", "") or ""
        text_plain = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text_plain = re.sub(r"<script[^>]*>.*?</script>", "", text_plain, flags=re.DOTALL | re.IGNORECASE)
        text_plain = re.sub(r"<[^>]+>", " ", text_plain)
        text_plain = re.sub(r"\s+", " ", text_plain).strip()
        return {
            "id": t.get("id"),
            "name": t.get("name"),
            "subject": t.get("subject"),
            "sender": t.get("sender"),
            "isActive": t.get("isActive"),
            "modifiedAt": t.get("modifiedAt"),
            "text_preview": text_plain[:3000],  # 3000 premiers chars du body en texte
            "html_length": len(html),
        }
