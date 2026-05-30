"""
Routes campagnes — Lymphatic Care Agent
- POST /campaigns/nurture : déclenche le cycle nurturing WARM + COLD
"""

from fastapi import APIRouter, Header, HTTPException
from typing import Optional
from loguru import logger

from config import config
from agents.nurture_engine import run_nurture_cycle


router = APIRouter()


@router.post("/nurture")
async def trigger_nurture(x_webhook_secret: Optional[str] = Header(None)):
    """
    Déclenche un cycle nurturing complet WARM + COLD.
    Protégé par X-Webhook-Secret. Appelé par cron quotidien.
    """
    if config.WEBHOOK_SECRET and x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret webhook invalide")

    logger.info("📬 Trigger /campaigns/nurture")
    summary = await run_nurture_cycle()
    return {
        "status": "ok",
        "total_sent": summary.get("total_sent", 0),
        "warm_count": len(summary.get("warm", [])),
        "cold_count": len(summary.get("cold", [])),
        "details": summary,
    }
