"""
Crée les 8 templates Brevo depuis nurture_templates.py
Convertit {prenom} → {{params.prenom}} pour le format Brevo
Imprime les IDs créés à la fin.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import socket
_orig_gai = socket.getaddrinfo
def _ipv4_gai(host, port, family=0, *args, **kw):
    return _orig_gai(host, port, socket.AF_INET, *args, **kw)
socket.getaddrinfo = _ipv4_gai

import json
import urllib.request
import urllib.error
from prompts.nurture_templates import (
    WARM_J0, WARM_J2, WARM_J5, WARM_J7,
    COLD_J0, COLD_J10, COLD_J20, COLD_J30,
)

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "contact@lymphaticcare.fr")
SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Lymphatic Care")
if not BREVO_API_KEY:
    raise SystemExit("BREVO_API_KEY env var is required (load .env or export it)")

TEMPLATES = [
    ("LC - WARM J+0 - Candidature reçue", WARM_J0),
    ("LC - WARM J+2 - Pourquoi on a tout quitté", WARM_J2),
    ("LC - WARM J+5 - On peut en parler", WARM_J5),
    ("LC - WARM J+7 - La question que personne n'ose poser", WARM_J7),
    ("LC - COLD J+0 - Étude marché 2026", COLD_J0),
    ("LC - COLD J+10 - Pourquoi drainage explose", COLD_J10),
    ("LC - COLD J+20 - Encore en réflexion ?", COLD_J20),
    ("LC - COLD J+30 - Dernière chance", COLD_J30),
]


def convert_placeholders(text: str) -> str:
    """Convertit {prenom} en {{params.prenom}} pour Brevo."""
    # Brevo uses {{params.X}} syntax
    return text.replace("{prenom}", "{{params.prenom}}")


def create_template(name: str, subject: str, html_content: str) -> dict:
    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "templateName": name,
        "htmlContent": html_content,
        "subject": subject,
        "isActive": True,
    }
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/templates",
        data=json.dumps(payload).encode("utf-8"),
        headers={"api-key": BREVO_API_KEY, "content-type": "application/json", "accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"  ❌ {name}: {e.code} {body[:200]}")
        return {"error": body}


def main():
    results = []
    for name, tpl in TEMPLATES:
        subject = convert_placeholders(tpl["subject"])
        html = convert_placeholders(tpl["html"])
        print(f"→ Création {name}...")
        res = create_template(name, subject, html)
        if "id" in res:
            print(f"  ✅ ID {res['id']}")
            results.append((name, res["id"]))
        else:
            results.append((name, None))

    print("\n=== Résumé ===")
    for name, tid in results:
        print(f"  {name}: ID={tid}")

    print("\n=== Pour .env ===")
    mapping = {
        "BREVO_TPL_WARM_J0": results[0][1],
        "BREVO_TPL_WARM_J2": results[1][1],
        "BREVO_TPL_WARM_J5": results[2][1],
        "BREVO_TPL_WARM_J7": results[3][1],
        "BREVO_TPL_COLD_J0": results[4][1],
        "BREVO_TPL_COLD_J10": results[5][1],
        "BREVO_TPL_COLD_J20": results[6][1],
        "BREVO_TPL_COLD_J30": results[7][1],
    }
    for k, v in mapping.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
