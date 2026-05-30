"""
Configuration centrale — Lymphatic Care Agent
Toutes les variables d'environnement sont chargées ici.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # LLM principal (hybride : fast pour scoring, quality pour brief Franck)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")  # openai | mistral | ollama
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL_FAST: str = os.getenv("LLM_MODEL_FAST", "gpt-4o-mini")
    LLM_MODEL_QUALITY: str = os.getenv("LLM_MODEL_QUALITY", "gpt-4o")

    # Ollama (legacy / fallback / health check Mistral local)
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")

    # Brevo
    BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "")
    BREVO_LIST_HOT: int = int(os.getenv("BREVO_LIST_HOT", "1"))
    BREVO_LIST_WARM: int = int(os.getenv("BREVO_LIST_WARM", "2"))
    BREVO_LIST_COLD: int = int(os.getenv("BREVO_LIST_COLD", "3"))
    BREVO_LIST_DISQUALIFIED: int = int(os.getenv("BREVO_LIST_DISQUALIFIED", "4"))
    BREVO_AUTOMATION_NURTURING: str = os.getenv("BREVO_AUTOMATION_NURTURING", "")
    BREVO_AUTOMATION_COLD: str = os.getenv("BREVO_AUTOMATION_COLD", "")
    BREVO_SENDER_EMAIL: str = os.getenv("BREVO_SENDER_EMAIL", "contact@lymphaticcare.fr")
    BREVO_SENDER_NAME: str = os.getenv("BREVO_SENDER_NAME", "Lymphatic Care")

    # Brevo Template IDs (nurturing) — éditables dans Brevo UI sans toucher au code
    BREVO_TPL_WARM_J0: int = int(os.getenv("BREVO_TPL_WARM_J0", "0"))
    BREVO_TPL_WARM_J2: int = int(os.getenv("BREVO_TPL_WARM_J2", "0"))
    BREVO_TPL_WARM_J5: int = int(os.getenv("BREVO_TPL_WARM_J5", "0"))
    BREVO_TPL_WARM_J7: int = int(os.getenv("BREVO_TPL_WARM_J7", "0"))
    BREVO_TPL_COLD_J0: int = int(os.getenv("BREVO_TPL_COLD_J0", "0"))
    BREVO_TPL_COLD_J10: int = int(os.getenv("BREVO_TPL_COLD_J10", "0"))
    BREVO_TPL_COLD_J20: int = int(os.getenv("BREVO_TPL_COLD_J20", "0"))
    BREVO_TPL_COLD_J30: int = int(os.getenv("BREVO_TPL_COLD_J30", "0"))

    # Notion
    NOTION_API_KEY: str = os.getenv("NOTION_API_KEY", "")
    NOTION_DB_HOT: str = os.getenv("NOTION_DB_HOT", "")
    NOTION_DB_WARM: str = os.getenv("NOTION_DB_WARM", "")
    NOTION_DB_COLD: str = os.getenv("NOTION_DB_COLD", "")

    # Calendly
    CALENDLY_LINK: str = os.getenv(
        "CALENDLY_LINK",
        "https://calendly.com/lymphaticcare/appel-strategique"
    )

    # Emails internes
    MAIL_FRANCK: str = os.getenv("MAIL_FRANCK", "franck@lymphaticcare.fr")
    MAIL_EQUIPE: str = os.getenv("MAIL_EQUIPE", "reseau@lymphaticcare.fr")

    # Sécurité
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    CONVERSATION_TTL: int = int(os.getenv("CONVERSATION_TTL", "172800"))  # 48h

    # Gmail Poller (Indeed leads via IMAP)
    GMAIL_USER: str = os.getenv("GMAIL_USER", "")
    GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")
    GMAIL_POLL_INTERVAL: int = int(os.getenv("GMAIL_POLL_INTERVAL", "120"))  # 2 min

    # App
    APP_ENV: str = os.getenv("APP_ENV", "production")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    PORT: int = int(os.getenv("PORT", "8000"))


config = Config()
