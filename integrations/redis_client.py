"""
Client Redis — Lymphatic Care Agent
Gère l'état des conversations multi-tours pour la qualification.
"""

import json
from typing import Optional
import redis.asyncio as aioredis
from loguru import logger

from config import config
from models.lead import ConversationState


class ConversationStore:
    """
    Stockage Redis des états de conversation.
    Clé : conv:{lead_email}
    TTL : config.CONVERSATION_TTL (48h par défaut)
    """

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def _get(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                config.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    @staticmethod
    def _key(lead_email: str) -> str:
        return f"conv:{lead_email.lower().strip()}"

    async def get(self, lead_email: str) -> Optional[ConversationState]:
        """Récupère l'état d'une conversation. None si absente."""
        try:
            r = await self._get()
            raw = await r.get(self._key(lead_email))
            if not raw:
                return None
            return ConversationState(**json.loads(raw))
        except Exception as e:
            logger.error(f"Redis get {lead_email} : {e}")
            return None

    async def save(self, state: ConversationState) -> bool:
        """Persiste l'état avec TTL."""
        try:
            r = await self._get()
            await r.setex(
                self._key(state.lead_email),
                config.CONVERSATION_TTL,
                json.dumps(state.model_dump(), ensure_ascii=False),
            )
            return True
        except Exception as e:
            logger.error(f"Redis save {state.lead_email} : {e}")
            return False

    async def delete(self, lead_email: str) -> bool:
        """Supprime l'état (fin de conversation ou abandon)."""
        try:
            r = await self._get()
            await r.delete(self._key(lead_email))
            return True
        except Exception as e:
            logger.error(f"Redis delete {lead_email} : {e}")
            return False

    async def health_check(self) -> bool:
        """Vérifie que Redis est joignable."""
        try:
            r = await self._get()
            await r.ping()
            return True
        except Exception as e:
            logger.error(f"Redis inaccessible : {e}")
            return False


conversation_store = ConversationStore()
