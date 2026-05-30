"""
Lymphatic Care — Agent de Qualification IA
Serveur FastAPI principal.

Démarrage : uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger
import sys
import socket

# Force IPv4 pour toutes les sorties HTTP (sync + async), pour rester sur l'IPv4
# whitelistée Brevo. Patch à la fois socket.getaddrinfo (sync) et la méthode
# asyncio BaseEventLoop.getaddrinfo (utilisée par httpx async).
_original_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(host, port, family=0, *args, **kwargs):
    return _original_getaddrinfo(host, port, socket.AF_INET, *args, **kwargs)
socket.getaddrinfo = _ipv4_only_getaddrinfo

import asyncio.base_events
_orig_async_getaddrinfo = asyncio.base_events.BaseEventLoop.getaddrinfo
async def _ipv4_async_getaddrinfo(self, host, port, *, family=0, type=0, proto=0, flags=0):
    return await _orig_async_getaddrinfo(
        self, host, port, family=socket.AF_INET, type=type, proto=proto, flags=flags,
    )
asyncio.base_events.BaseEventLoop.getaddrinfo = _ipv4_async_getaddrinfo

import asyncio

from config import config
from integrations.llm import llm_client
from routes.webhook_indeed import router as indeed_router
from routes.webhook_tally import router as tally_router
from routes.webhook_conversation import router as conversation_router
from routes.campaigns import router as campaigns_router


# --- Configuration logs ---
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}",
    level=config.LOG_LEVEL,
)
logger.add(
    "data/agent.log",
    rotation="10 MB",
    retention="30 days",
    level="DEBUG",
)


# --- Startup / Shutdown ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Démarrage Agent Qualification — Lymphatic Care")
    logger.info(f"LLM provider : {config.LLM_PROVIDER} → {config.LLM_BASE_URL}")
    logger.info(f"  - modèle fast    : {config.LLM_MODEL_FAST}")
    logger.info(f"  - modèle quality : {config.LLM_MODEL_QUALITY}")

    llm_ok = await llm_client.health_check()
    if llm_ok:
        logger.success("✅ LLM API joignable")
    else:
        logger.warning("⚠️ LLM API non joignable — les webhooks vont échouer")

    logger.info("📬 Pont Gmail : géré par Make scenario 9300495 (polling 15 min)")

    yield

    logger.info("Agent arrêté")


# --- App ---
app = FastAPI(
    title="Lymphatic Care — Agent Qualification",
    description="API de qualification automatique des leads Lymphatic Care",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# --- Routes ---
app.include_router(indeed_router, prefix="/webhook", tags=["Indeed"])
app.include_router(tally_router, prefix="/webhook", tags=["Tally"])
app.include_router(conversation_router, prefix="/webhook", tags=["Conversation"])
app.include_router(campaigns_router, prefix="/campaigns", tags=["Campaigns"])


# --- Endpoints utilitaires ---
@app.get("/")
async def root():
    return {
        "service": "Lymphatic Care — Agent Qualification",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Vérification état de l'agent et de ses dépendances."""
    llm_ok = await llm_client.health_check()
    return {
        "status": "ok" if llm_ok else "degraded",
        "llm": "ok" if llm_ok else "unavailable",
        "provider": config.LLM_PROVIDER,
        "model_fast": config.LLM_MODEL_FAST,
        "model_quality": config.LLM_MODEL_QUALITY,
    }


@app.get("/webhooks")
async def list_webhooks():
    """Liste tous les webhooks disponibles."""
    return {
        "webhooks": [
            {
                "url": "/webhook/indeed",
                "method": "POST",
                "description": "Candidatures Indeed parsées depuis Make"
            },
            {
                "url": "/webhook/tally",
                "method": "POST",
                "description": "Formulaires Tally (landing page, Instagram, LinkedIn)"
            },
            {
                "url": "/webhook/conversation",
                "method": "POST",
                "description": "Réponses email/WhatsApp pour qualification conversationnelle"
            },
        ]
    }
