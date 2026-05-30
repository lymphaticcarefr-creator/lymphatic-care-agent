"""
Client Ollama / Mistral — Lymphatic Care Agent
Gère les appels à l'API Ollama locale.
"""

import httpx
import json
from loguru import logger
from config import config


class OllamaClient:
    """Client HTTP pour l'API Ollama locale."""

    def __init__(self):
        self.base_url = config.OLLAMA_URL
        self.model = config.OLLAMA_MODEL
        self.timeout = 120.0  # Mistral CPU peut être lent

    async def complete(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.3
    ) -> str:
        """
        Génère une réponse simple (mode non-conversationnel).
        Utilisé pour l'analyse silencieuse des lettres Indeed.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "top_k": 40,
                "repeat_penalty": 1.1,
                "num_ctx": 4096,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                return data.get("response", "")

        except httpx.TimeoutException:
            logger.error("Timeout Ollama — modèle trop lent")
            raise
        except Exception as e:
            logger.error(f"Erreur Ollama : {e}")
            raise

    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        temperature: float = 0.3
    ) -> str:
        """
        Génère une réponse en mode conversation multi-tours.
        Utilisé pour la qualification en 7 questions.

        messages format : [{"role": "user"|"assistant", "content": "..."}]
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "top_k": 40,
                "repeat_penalty": 1.1,
                "num_ctx": 4096,
            }
        }

        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                return data.get("message", {}).get("content", "")

        except httpx.TimeoutException:
            logger.error("Timeout Ollama chat")
            raise
        except Exception as e:
            logger.error(f"Erreur Ollama chat : {e}")
            raise

    async def parse_json_response(self, response: str) -> dict:
        """
        Parse la réponse JSON de Mistral.
        Gère les cas où Mistral ajoute du texte autour du JSON.
        """
        # Tentative directe
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Extraction du bloc JSON entre { }
        try:
            start = response.index("{")
            end = response.rindex("}") + 1
            json_str = response[start:end]
            return json.loads(json_str)
        except (ValueError, json.JSONDecodeError):
            logger.error(f"Impossible de parser le JSON Mistral : {response[:200]}")
            return {}

    async def health_check(self) -> bool:
        """Vérifie que Ollama est accessible et Mistral disponible."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                data = response.json()
                models = [m["name"] for m in data.get("models", [])]
                available = any(self.model in m for m in models)
                if not available:
                    logger.warning(f"Modèle {self.model} non trouvé. Modèles dispo : {models}")
                return available
        except Exception as e:
            logger.error(f"Ollama inaccessible : {e}")
            return False


ollama_client = OllamaClient()
