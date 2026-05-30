"""
Gmail Poller — Lymphatic Care Agent

Surveille la boîte Gmail via IMAP pour détecter les candidatures Indeed,
parse le contenu via LLM (gpt-4o-mini), et POST vers /webhook/indeed.

Tourne en background task au démarrage de FastAPI.
"""

import asyncio
import email
import imaplib
import json
import re
from email.header import decode_header
from email.utils import parseaddr
from typing import Optional
from loguru import logger

from config import config
from integrations.llm import llm_client


# Prompt pour extraire les champs d'un email Indeed
EXTRACT_PROMPT = """Tu reçois le contenu brut d'un email de candidature Indeed envoyé à Lymphatic Care.

Extrait les champs suivants en JSON STRICT, sans markdown :
{
  "prenom": "Prénom du candidat",
  "nom": "Nom du candidat",
  "email": "Email du candidat (PAS no-reply@indeed.com)",
  "telephone": "Numéro de téléphone si trouvé, sinon null",
  "lettre_motivation": "Texte intégral de la lettre/message de motivation du candidat",
  "reponse_q1_profession": "Réponse à la question profession si trouvée, sinon null",
  "reponse_q2_situation": "Réponse situation libéral/salarié/reconversion si trouvée, sinon null",
  "reponse_q3_region": "Région/ville cible si trouvée, sinon null",
  "reponse_q4_motivation": "Réponse motivation principale si trouvée, sinon null"
}

Si tu ne trouves pas un champ, mets null. Pour l'email du candidat, NE PAS retourner indeedapply@indeed.com ou toute adresse @indeed.com — cherche l'email réel du candidat dans le corps."""


def _decode(s) -> str:
    """Décode un header email (peut contenir du encoded-word)."""
    if not s:
        return ""
    if isinstance(s, bytes):
        try: return s.decode("utf-8", errors="replace")
        except Exception: return s.decode("latin-1", errors="replace")
    try:
        parts = decode_header(s)
        out = []
        for txt, enc in parts:
            if isinstance(txt, bytes):
                out.append(txt.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(str(txt))
        return "".join(out)
    except Exception:
        return str(s)


def _extract_body(msg: email.message.Message) -> str:
    """Extrait le corps text+html d'un message email."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="replace")
                        parts.append(text)
                except Exception as e:
                    logger.warning(f"Decode body part: {e}")
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                parts.append(payload.decode(charset, errors="replace"))
        except Exception:
            parts.append(str(msg.get_payload()))
    return "\n\n".join(parts)


def _clean_html(html: str) -> str:
    """Nettoie le HTML brut pour ne garder que le texte utile."""
    # Retire les balises HTML simples
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    # Décodage HTML entities basique
    html = html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    # Espaces multiples
    html = re.sub(r"\s+", " ", html).strip()
    return html


async def _extract_lead_via_llm(subject: str, body: str) -> Optional[dict]:
    """Utilise gpt-4o-mini pour extraire les champs structurés du lead."""
    user = f"OBJET : {subject}\n\nCORPS EMAIL :\n{body[:8000]}"
    try:
        raw = await llm_client.score(
            system=EXTRACT_PROMPT,
            user=user,
            temperature=0.0,
        )
        data = await llm_client.parse_json_response(raw)
        return data or None
    except Exception as e:
        logger.error(f"LLM extract error: {e}")
        return None


async def _post_to_webhook(lead: dict) -> bool:
    """POST le lead structuré sur /webhook/indeed local."""
    import httpx
    # Validation minimale avant POST
    if not lead.get("prenom") or not lead.get("nom") or not lead.get("email"):
        logger.warning(f"Lead incomplet, skip: {lead}")
        return False
    if "@indeed.com" in (lead.get("email") or "").lower():
        logger.warning(f"Email Indeed no-reply détecté, skip: {lead.get('email')}")
        return False
    if not lead.get("lettre_motivation"):
        lead["lettre_motivation"] = "(aucune lettre fournie)"
    payload = {
        "prenom": lead["prenom"][:100],
        "nom": lead["nom"][:100],
        "email": lead["email"][:200],
        "telephone": lead.get("telephone"),
        "lettre_motivation": lead["lettre_motivation"][:8000],
        "reponse_q1_profession": lead.get("reponse_q1_profession"),
        "reponse_q2_situation": lead.get("reponse_q2_situation"),
        "reponse_q3_region": lead.get("reponse_q3_region"),
        "reponse_q4_motivation": lead.get("reponse_q4_motivation"),
        "source": "INDEED",
    }
    headers = {"X-Webhook-Secret": config.WEBHOOK_SECRET} if config.WEBHOOK_SECRET else {}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"http://localhost:{config.PORT}/webhook/indeed",
                json=payload,
                headers=headers,
            )
            if r.status_code == 200:
                d = r.json()
                logger.info(f"Lead {lead['email']} → {d.get('classification')} score {d.get('score')}")
                return True
            else:
                logger.error(f"Webhook indeed {r.status_code}: {r.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"POST webhook error: {e}")
        return False


def _list_unread_indeed_uids(conn: imaplib.IMAP4_SSL) -> list[bytes]:
    """Liste les UIDs des emails non lus venant d'Indeed."""
    conn.select("INBOX")
    # Indeed envoie depuis no-reply@notification.indeed.com ou indeedapply@indeed.com
    status, data = conn.uid("search", None, '(UNSEEN FROM "indeed")')
    if status != "OK":
        return []
    return data[0].split()


async def _process_one_email(conn: imaplib.IMAP4_SSL, uid: bytes) -> bool:
    """Récupère un email, extrait les champs, POST sur webhook, marque comme lu."""
    try:
        status, data = conn.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            return False
        raw = data[0][1]
        msg = email.message_from_bytes(raw)
        subject = _decode(msg.get("Subject"))
        from_addr = parseaddr(msg.get("From"))[1]
        logger.info(f"Email Indeed UID={uid.decode()} from={from_addr} subject={subject[:80]!r}")

        body = _extract_body(msg)
        # Si on a du HTML, nettoyer pour LLM
        if "<html" in body.lower() or "<body" in body.lower():
            body = _clean_html(body)

        lead = await _extract_lead_via_llm(subject, body)
        if not lead:
            logger.warning(f"Extraction LLM échouée pour UID={uid.decode()}")
            return False

        success = await _post_to_webhook(lead)
        if success:
            # Marque l'email comme lu (\Seen)
            conn.uid("store", uid, "+FLAGS", "(\\Seen)")
        return success
    except Exception as e:
        logger.error(f"Process email UID={uid}: {e}")
        return False


async def gmail_poller_loop():
    """Boucle principale : poll Gmail toutes les N secondes."""
    interval = config.GMAIL_POLL_INTERVAL
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        logger.warning("Gmail poller désactivé (GMAIL_USER ou GMAIL_APP_PASSWORD vide)")
        return

    logger.info(f"📬 Gmail poller démarré ({config.GMAIL_USER}, interval={interval}s)")

    while True:
        try:
            # Connexion IMAP fraîche à chaque cycle (évite timeouts)
            conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            conn.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            uids = _list_unread_indeed_uids(conn)
            if uids:
                logger.info(f"📬 {len(uids)} email(s) Indeed non lu(s)")
                for uid in uids:
                    await _process_one_email(conn, uid)
            try:
                conn.logout()
            except Exception:
                pass
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP error: {e}")
        except Exception as e:
            logger.error(f"Gmail poller cycle: {e}")

        await asyncio.sleep(interval)
