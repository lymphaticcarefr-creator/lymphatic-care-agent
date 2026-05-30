"""
Health check quotidien — Lymphatic Care Agent
Vérifie que tout le pipeline fonctionne et envoie une alerte email si problème.

Lancé chaque jour à 8h00 par cron (avant le cron nurturing à 9h00).
"""
import socket
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, family=0, *a, **kw: _orig(h, p, socket.AF_INET, *a, **kw)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from loguru import logger

from config import config
from integrations.brevo import send_transactional_email

NOTION_API = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {config.NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

ALERT_RECIPIENT = config.MAIL_FRANCK or "franck@lymphaticcare.fr"


async def check_vps_health() -> tuple[bool, str]:
    """Vérifie que l'API VPS répond."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("http://localhost:8000/health")
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            data = r.json()
            if data.get("status") != "ok":
                return False, f"status={data.get('status')}, llm={data.get('llm')}"
            return True, "ok"
    except Exception as e:
        return False, f"exception: {e}"


async def check_brevo() -> tuple[bool, str]:
    """Vérifie que Brevo répond et que les 8 templates existent."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.brevo.com/v3/smtp/templates?limit=50",
                headers={"api-key": config.BREVO_API_KEY, "accept": "application/json"},
            )
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            data = r.json()
            templates = data.get("templates", [])
            expected_ids = {13, 14, 15, 16, 17, 18, 19, 20}
            found_ids = {t["id"] for t in templates}
            missing = expected_ids - found_ids
            if missing:
                return False, f"templates manquants : {missing}"
            return True, f"{len(found_ids)} templates OK"
    except Exception as e:
        return False, f"exception: {e}"


async def check_notion_recent_leads() -> tuple[bool, str]:
    """
    Vérifie qu'au moins 1 lead a été créé dans les dernières 48h
    (toutes DBs confondues : HOT + WARM + COLD).
    Si rien depuis 48h ET on est en semaine, c'est suspect (canal cassé).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    cutoff_iso = cutoff.isoformat()

    dbs = {
        "HOT": config.NOTION_DB_HOT,
        "WARM": config.NOTION_DB_WARM,
        "COLD": config.NOTION_DB_COLD,
    }
    counts = {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for name, db_id in dbs.items():
                if not db_id:
                    counts[name] = "?"
                    continue
                r = await client.post(
                    f"{NOTION_API}/databases/{db_id}/query",
                    json={
                        "filter": {
                            "timestamp": "created_time",
                            "created_time": {"on_or_after": cutoff_iso},
                        },
                        "page_size": 100,
                    },
                    headers=NOTION_HEADERS,
                )
                if r.status_code != 200:
                    counts[name] = f"err{r.status_code}"
                    continue
                counts[name] = len(r.json().get("results", []))
    except Exception as e:
        return False, f"exception: {e}"

    total = sum(v for v in counts.values() if isinstance(v, int))
    detail = f"HOT={counts.get('HOT')} WARM={counts.get('WARM')} COLD={counts.get('COLD')} (48h)"

    # On considère qu'il faut au moins 1 lead/48h en moyenne
    # Tolérance week-end : si on est lundi matin, ne pas alerter pour samedi/dimanche
    today = datetime.now().weekday()  # 0=Mon, 6=Sun
    if today in (0, 1) and total == 0:
        # lundi/mardi matin sans leads = pas critique
        return True, f"{detail} — semaine débute"

    if total == 0:
        return False, f"AUCUN lead en 48h — canal probablement coupé ({detail})"

    return True, detail


async def check_systeme_io_health() -> tuple[bool, str]:
    """Check optionnel : Systeme.io répond."""
    # Skip pour l'instant — Systeme.io n'a pas d'endpoint health public
    return True, "skip"


async def main():
    logger.info("🔍 Health check démarré")
    checks = [
        ("VPS Agent FastAPI", check_vps_health()),
        ("Brevo API + templates", check_brevo()),
        ("Leads récents (Notion)", check_notion_recent_leads()),
    ]
    results = []
    for name, coro in checks:
        ok, detail = await coro
        results.append((name, ok, detail))
        status_emoji = "✅" if ok else "❌"
        logger.info(f"  {status_emoji} {name} : {detail}")

    failed = [(n, d) for n, ok, d in results if not ok]
    if not failed:
        logger.success("✅ Tous les checks OK")
        return

    # Construit l'email d'alerte
    rows_html = ""
    for name, ok, detail in results:
        emoji = "✅" if ok else "❌"
        color = "#2d5c47" if ok else "#b83a3a"
        rows_html += f"""
        <tr>
          <td style="padding:8px; border:1px solid #ddd;">{emoji} {name}</td>
          <td style="padding:8px; border:1px solid #ddd; color:{color}; font-weight:bold;">{detail}</td>
        </tr>
        """

    html = f"""
    <h2 style="color:#b83a3a;">⚠️ Alerte health-check Lymphatic Care</h2>
    <p>Le check quotidien a détecté {len(failed)} problème(s) dans le pipeline d'automatisation.</p>
    <table style="border-collapse:collapse; width:100%; max-width:600px;">
      <tr style="background:#f5f5f5;">
        <th style="padding:8px; border:1px solid #ddd; text-align:left;">Composant</th>
        <th style="padding:8px; border:1px solid #ddd; text-align:left;">Détail</th>
      </tr>
      {rows_html}
    </table>
    <p style="margin-top:20px;"><b>Actions à mener :</b></p>
    <ul>
      <li>Vérifier le scenario Make Indeed (ID 9300495)</li>
      <li>Vérifier l'état du VPS : <code>systemctl status lymphatic-agent</code></li>
      <li>Vérifier les logs : <code>tail -100 /opt/lymphatic-care-agent/data/agent.log</code></li>
    </ul>
    <p style="color:#888; font-size:12px;">
      Exécuté le {datetime.now().strftime('%d/%m/%Y à %H:%M')} sur VPS Hostinger
    </p>
    """

    success = await send_transactional_email(
        to_email=ALERT_RECIPIENT,
        to_name="Franck",
        subject=f"⚠️ ALERTE Lymphatic Care — {len(failed)} composant(s) en erreur",
        html_content=html,
    )
    if success:
        logger.warning(f"📧 Alerte email envoyée à {ALERT_RECIPIENT}")
    else:
        logger.error("❌ Échec envoi alerte email — problème critique")


if __name__ == "__main__":
    asyncio.run(main())
