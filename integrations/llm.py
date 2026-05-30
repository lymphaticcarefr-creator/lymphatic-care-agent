"""
Client LLM unifié — Lymphatic Care Agent

Stratégie hybride :
- `score()` utilise un modèle rapide+pas cher (gpt-4o-mini par défaut) pour la classification.
- `brief()` utilise un modèle qualité (gpt-4o par défaut) pour rédiger le brief Franck.

Compatible OpenAI API (https://api.openai.com/v1) mais utilisable aussi avec
n'importe quel provider OpenAI-compatible (Mistral Cloud, Groq, Together, etc.)
en changeant `LLM_BASE_URL` et `LLM_API_KEY`.

Garde le client Ollama en fallback si LLM_PROVIDER=ollama.
"""

import json
import httpx
from typing import Optional
from loguru import logger

from config import config


class LLMClient:
    """Client LLM compatible OpenAI API (chat completions, JSON mode)."""

    def __init__(self):
        self.provider = config.LLM_PROVIDER  # "openai" | "mistral" | "ollama"
        self.base_url = config.LLM_BASE_URL.rstrip("/")
        self.api_key = config.LLM_API_KEY
        self.model_fast = config.LLM_MODEL_FAST       # ex: gpt-4o-mini
        self.model_quality = config.LLM_MODEL_QUALITY # ex: gpt-4o
        self.timeout = 60.0

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def _chat(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str:
        """Appel /chat/completions, retourne le contenu du message assistant."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, json=payload, headers=self._headers())
                if r.status_code != 200:
                    logger.error(f"LLM {model} HTTP {r.status_code}: {r.text[:300]}")
                    return ""
                data = r.json()
                return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            logger.error(f"LLM {model} timeout après {self.timeout}s")
            return ""
        except Exception as e:
            logger.error(f"LLM {model} erreur : {e}")
            return ""

    async def score(self, system: str, user: str, temperature: float = 0.2) -> str:
        """Appelle le modèle rapide pour classification / scoring."""
        return await self._chat(self.model_fast, system, user, temperature, json_mode=True)

    async def brief(self, system: str, user: str, temperature: float = 0.5) -> str:
        """Appelle le modèle qualité pour le brief Franck (HOT uniquement)."""
        return await self._chat(self.model_quality, system, user, temperature, json_mode=True)

    @staticmethod
    async def parse_json_response(response: str) -> dict:
        """Parse une réponse JSON. Gère les cas où le modèle enrobe le JSON."""
        if not response:
            return {}
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        try:
            start = response.index("{")
            end = response.rindex("}") + 1
            return json.loads(response[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.error(f"JSON invalide : {response[:200]}")
            return {}

    async def health_check(self) -> bool:
        """Vérifie que l'API LLM répond."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Endpoint /models : standard sur OpenAI et la plupart des providers OpenAI-compatibles
                r = await client.get(f"{self.base_url}/models", headers=self._headers())
                return r.status_code == 200
        except Exception as e:
            logger.error(f"LLM health check échoué : {e}")
            return False


llm_client = LLMClient()
