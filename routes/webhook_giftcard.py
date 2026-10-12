"""
Bons cadeaux Lymphatic Care — Stripe → bon PDF → emails (Brevo) → Notion.

Flux : un client paie un bon cadeau via un lien de paiement Stripe. Stripe
appelle POST /webhook/giftcard/stripe (événement checkout.session.completed).
On génère un code unique, le bon en PDF, on l'envoie à l'acheteur (pièce
jointe), on prévient le cabinet, on inscrit le bon dans la base Notion
« 🎁 Bons cadeaux », et on envoie une alerte Telegram.

Sécurité : pas de secret Stripe stocké ici. Un appel n'est accepté que s'il
provient d'une adresse IP officielle des webhooks Stripe (liste publiée par
Stripe), ou d'un test interne signé par X-Webhook-Secret. Chaque paiement
n'est traité qu'une fois (Redis). Le bon ne sort que si payment_status = paid.

Les liens de paiement Stripe portent des métadonnées :
  soin    = decouverte | corps | visage | jambes | sportif | enceinte
  cabinet = narbonne
et deux champs personnalisés : beneficiaire (obligatoire), message (facultatif).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import time
from datetime import date, datetime, timedelta
from html import escape
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from loguru import logger

from config import config
from integrations import telegram
from integrations.giftcard_pdf import build_giftcard_pdf
import redis.asyncio as aioredis

router = APIRouter()

NOTION_DB_BONS = os.getenv("NOTION_DB_BONS_CADEAUX", "954abeb7a6b0402a999793d5fef0900e")
NOTION_DB_MONTPELLIER = os.getenv("NOTION_DB_BONS_MONTPELLIER", "")
MAIL_CABINET = os.getenv("GIFTCARD_MAIL_CABINET", "contact@lymphaticcare.fr")
PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "https://srv1684819.hstgr.cloud")
VALIDITE_JOURS = 365
DATA_DIR = "/app/data/giftcards"
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")

SOINS = {
    "decouverte": ("Séance Découverte", "60 minutes · bilan corporel complet offert", "Séance Découverte"),
    "corps": ("Drainage corps entier", "60 minutes", "Drainage corps entier"),
    "visage": ("Drainage corps & visage", "90 minutes", "Drainage corps & visage"),
    "jambes": ("Drainage jambes légères", "35 minutes", "Drainage jambes légères"),
    "sportif": ("Drainage sportif", "45 minutes", "Drainage sportif"),
    "enceinte": ("Drainage femme enceinte", "45 minutes", "Drainage femme enceinte"),
}

CABINETS = {
    "narbonne": {
        "nom": "Narbonne",
        "prefixe": "NAR",
        "ligne1": "Lymphatic Care Narbonne · 8 rue Cabirol, 11100 Narbonne",
        "ligne2": "Réservation : 06 62 33 70 45 · www.lymphaticcare.fr/reservation",
        "tel": "06 62 33 70 45",
        "resa": "https://www.lymphaticcare.fr/reservation",
        "adresse": "8 rue Cabirol, 11100 Narbonne",
        "mail": os.getenv("GIFTCARD_MAIL_NARBONNE", "contact@lymphaticcare.fr"),
    },
    "montpellier": {
        "nom": "Montpellier",
        "prefixe": "MTP",
        "ligne1": "Lymphatic Care Montpellier · Tour du Polygone, 265 avenue des États du Languedoc, 34000 Montpellier",
        "ligne2": "Réservation : 06 71 78 73 84 · montpellier.lymphaticcare.fr/reservation",
        "tel": "06 71 78 73 84",
        "resa": "https://montpellier.lymphaticcare.fr/reservation",
        "adresse": "Tour du Polygone, 265 avenue des États du Languedoc, 34000 Montpellier (5e étage, Cabinet Zone 1)",
        "mail": os.getenv("GIFTCARD_MAIL_MONTPELLIER", "estela@lymphaticcare.fr"),
    },
}

_REDIS = None


def _redis():
    global _REDIS
    if _REDIS is None:
        _REDIS = aioredis.from_url(config.REDIS_URL, encoding="utf-8", decode_responses=True)
    return _REDIS


_STRIPE_IPS: set[str] = set()
_STRIPE_IPS_TS = 0.0


# ---------------------------------------------------------------------------
# Sécurité
# ---------------------------------------------------------------------------
async def _stripe_webhook_ips() -> set[str]:
    global _STRIPE_IPS, _STRIPE_IPS_TS
    if _STRIPE_IPS and time.time() - _STRIPE_IPS_TS < 86400:
        return _STRIPE_IPS
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://stripe.com/files/ips/ips_webhooks.json")
            ips = set(r.json().get("WEBHOOKS", []))
            if ips:
                _STRIPE_IPS, _STRIPE_IPS_TS = ips, time.time()
    except Exception as e:
        logger.warning(f"[BON] Liste IP Stripe indisponible ({e}) — on garde le cache")
    return _STRIPE_IPS


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "")


def _sign(code: str) -> str:
    key = (config.WEBHOOK_SECRET or "lymphatic").encode()
    return hmac.new(key, code.encode(), hashlib.sha256).hexdigest()[:24]


def _new_code(prefixe: str, test: bool) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans 0/O/1/I
    core = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"{'TEST-' if test else ''}LC-{prefixe}-{core}"


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------
def _email_acheteur(prenom: str, soin: str, duree: str, beneficiaire: str, code: str,
                    validite: str, cab: dict, lien_pdf: str) -> str:
    p = escape(prenom) if prenom else ""
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;color:#1F2E29;max-width:560px;margin:auto;line-height:1.6">
<div style="background:#3A6155;color:#fff;padding:22px 26px;border-radius:6px 6px 0 0">
  <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;opacity:.85">Lymphatic Care {escape(cab['nom'])}</div>
  <div style="font-size:22px;font-weight:bold;margin-top:4px">Votre bon cadeau est prêt 🎁</div>
</div>
<div style="background:#F5FAF0;padding:24px 26px;border-radius:0 0 6px 6px">
  <p>Bonjour{(' ' + p) if p else ''},</p>
  <p>Merci pour votre achat. Vous trouverez <b>en pièce jointe</b> le bon cadeau, prêt à imprimer ou à transférer :</p>
  <table style="width:100%;background:#fff;border:1px solid #D2E4DE;border-radius:6px;padding:14px 16px;margin:14px 0">
    <tr><td style="color:#5A6B65;font-size:13px;width:40%">Soin offert</td><td><b>{escape(soin)}</b><br><span style="font-size:13px;color:#5A6B65">{escape(duree)}</span></td></tr>
    <tr><td style="color:#5A6B65;font-size:13px">Offert à</td><td><b>{escape(beneficiaire)}</b></td></tr>
    <tr><td style="color:#5A6B65;font-size:13px">Code</td><td><b style="font-family:Courier,monospace;font-size:16px">{escape(code)}</b></td></tr>
    <tr><td style="color:#5A6B65;font-size:13px">Valable jusqu'au</td><td><b>{escape(validite)}</b></td></tr>
  </table>
  <p style="margin-bottom:6px"><b>Comment en profiter ?</b></p>
  <p style="margin-top:0">La personne qui reçoit le bon réserve sa séance en appelant le cabinet au <b>{escape(cab['tel'])}</b>
  ou en ligne sur <a href="{cab['resa']}" style="color:#3A6155">{cab['resa'].replace('https://', '')}</a>, et indique son code.
  Le cabinet se trouve au {escape(cab['adresse'])}.</p>
  <p style="font-size:13px;color:#5A6B65">Pièce jointe introuvable ? <a href="{lien_pdf}" style="color:#3A6155">Télécharger le bon cadeau</a>.</p>
  <p>À très bientôt,<br><b>L'équipe Lymphatic Care {escape(cab['nom'])}</b></p>
</div>
<p style="font-size:11px;color:#5A6B65;text-align:center;margin-top:12px">Bon nominatif, non remboursable, non échangeable contre des espèces.</p>
</div>"""


def _email_cabinet(d: dict, notion_url: str | None, lien_pdf: str) -> str:
    rows = "".join(
        f"<tr><td style='color:#5A6B65;padding:3px 12px 3px 0'>{escape(k)}</td><td><b>{escape(str(v))}</b></td></tr>"
        for k, v in [
            ("Soin", d["soin"]), ("Montant", f"{d['montant']:.2f} €".replace(".", ",")),
            ("Bénéficiaire", d["beneficiaire"]), ("Message", d["message"] or "—"),
            ("Acheteur", d["acheteur"] or "—"), ("Email acheteur", d["email"] or "—"),
            ("Téléphone", d["telephone"] or "—"), ("Code", d["code"]),
            ("Valable jusqu'au", d["validite"]), ("Paiement Stripe", d["session_id"]),
        ]
    )
    notion = f"<p><a href='{notion_url}'>Ouvrir la fiche dans Notion</a></p>" if notion_url else \
        "<p style='color:#b8552e'><b>Attention : la fiche Notion n'a pas pu être créée.</b></p>"
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;color:#1F2E29">
<h2 style="color:#3A6155;margin-bottom:6px">🎁 Nouveau bon cadeau vendu</h2>
<table>{rows}</table>{notion}
<p><a href="{lien_pdf}">Voir le bon cadeau (PDF)</a></p>
<p style="font-size:12px;color:#5A6B65">Le jour du rendez-vous : vérifier le code dans Notion et passer le bon en « Utilisé ».</p>
</div>"""


async def _brevo_send(to_email: str, to_name: str, subject: str, html: str,
                      pdf: bytes | None = None, pdf_name: str = "bon-cadeau.pdf",
                      reply_to: str | None = None) -> bool:
    payload = {
        "sender": {"name": config.BREVO_SENDER_NAME, "email": config.BREVO_SENDER_EMAIL},
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    if pdf:
        payload["attachment"] = [{"name": pdf_name, "content": base64.b64encode(pdf).decode()}]
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            r = await client.post(
                "https://api.brevo.com/v3/smtp/email", json=payload,
                headers={"api-key": config.BREVO_API_KEY, "accept": "application/json",
                         "content-type": "application/json"},
            )
        if r.status_code == 201:
            logger.info(f"[BON] Email envoyé à {to_email} — {subject}")
            return True
        logger.error(f"[BON] Brevo {r.status_code} pour {to_email} : {r.text[:300]}")
    except Exception as e:
        logger.error(f"[BON] Exception Brevo ({to_email}) : {e}")
    return False


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------
async def _notion_create(d: dict, database_id: str | None = None) -> str | None:
    def rt(v):
        return {"rich_text": [{"text": {"content": (v or "")[:1900]}}]} if v else {"rich_text": []}

    props = {
        "Code": {"title": [{"text": {"content": d["code"]}}]},
        "Statut": {"select": {"name": "Valide"}},
        "Soin": {"select": {"name": d["soin_notion"]}},
        "Cabinet": {"select": {"name": d["cabinet"]}},
        "Montant": {"number": d["montant"]},
        "Bénéficiaire": rt(d["beneficiaire"]),
        "Message": rt(d["message"]),
        "Acheteur": rt(d["acheteur"]),
        "Date d'achat": {"date": {"start": d["date_achat"]}},
        "Valable jusqu'au": {"date": {"start": d["validite_iso"]}},
        "PDF du bon": {"url": d["lien_pdf"]},
        "Paiement Stripe": rt(d["session_id"]),
        "Notes": rt("Paiement en mode TEST Stripe — ne pas honorer." if d["test"] else ""),
    }
    if d["email"]:
        props["Email acheteur"] = {"email": d["email"]}
    if d["telephone"]:
        props["Téléphone acheteur"] = {"phone_number": d["telephone"]}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.notion.com/v1/pages",
                headers={"Authorization": f"Bearer {config.NOTION_API_KEY}",
                         "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
                json={"parent": {"database_id": database_id or NOTION_DB_BONS}, "properties": props},
            )
        if r.status_code == 200:
            return r.json().get("url")
        logger.error(f"[BON] Notion {r.status_code} : {r.text[:300]}")
    except Exception as e:
        logger.error(f"[BON] Exception Notion : {e}")
    return None


# ---------------------------------------------------------------------------
# Traitement d'un paiement
# ---------------------------------------------------------------------------
# Liens de paiement Stripe (compte Lymphatic Care) → soin et cabinet.
# Les liens créés depuis le tableau de bord ne transmettent pas toujours de métadonnées.
PAYMENT_LINKS = {
    "plink_1UIPGW0uuz40NttVEFu9uNDR": ("decouverte", "narbonne"),
    "plink_1UIPNF0uuz40NttVfJHieUYU": ("corps", "narbonne"),
    "plink_1UIPPm0uuz40NttVuU7oFNyL": ("visage", "narbonne"),
    "plink_1UIPS70uuz40NttVzTdQMYi3": ("jambes", "narbonne"),
    "plink_1UIPTv0uuz40NttVCqTYgNJJ": ("sportif", "narbonne"),
    "plink_1UIPVy0uuz40NttVEboVHfIX": ("enceinte", "narbonne"),
    # --- Montpellier (compte Stripe d'Estela) : à compléter une fois ses 6 liens créés ---
    # "plink_XXXXXXXXXXXXXXXXXXXXXXXX": ("decouverte", "montpellier"),
    # "plink_XXXXXXXXXXXXXXXXXXXXXXXX": ("corps", "montpellier"),
    # "plink_XXXXXXXXXXXXXXXXXXXXXXXX": ("visage", "montpellier"),
    # "plink_XXXXXXXXXXXXXXXXXXXXXXXX": ("jambes", "montpellier"),
    # "plink_XXXXXXXXXXXXXXXXXXXXXXXX": ("sportif", "montpellier"),
    # "plink_XXXXXXXXXXXXXXXXXXXXXXXX": ("enceinte", "montpellier"),
}


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _custom_field(session: dict, key: str) -> str:
    """Valeur d'un champ personnalisé : par clé exacte, sinon par clé ou libellé approchant
    (la clé générée par Stripe depuis « Prénom et nom du bénéficiaire » n'est pas maîtrisée)."""
    indices = {"beneficiaire": ("beneficiaire", "bnficiaire", "benef"), "message": ("message",)}.get(key, (key,))
    for exact in (True, False):
        for f in session.get("custom_fields") or []:
            k = _norm(f.get("key") or "")
            label = _norm(((f.get("label") or {}).get("custom")) or "")
            ok = (k == key) if exact else any(i in k or i in label for i in indices)
            if ok:
                v = (f.get(f.get("type") or "text") or {}).get("value")
                return (v or "").strip()
    return ""


async def process_session(session: dict, *, livemode: bool, override_to: str | None = None) -> dict:
    session_id = session.get("id") or f"manuel_{int(time.time())}"
    if session.get("payment_status") not in ("paid", "no_payment_required"):
        return {"status": "ignored", "reason": f"payment_status={session.get('payment_status')}"}

    # Idempotence : un paiement = un seul bon
    lock_key = f"giftcard:session:{session_id}"
    try:
        if not await _redis().set(lock_key, "1", nx=True, ex=60 * 60 * 24 * 400):
            logger.info(f"[BON] Session déjà traitée : {session_id}")
            return {"status": "already_processed"}
    except Exception as e:
        logger.warning(f"[BON] Redis indisponible pour l'idempotence ({e}) — on continue")

    meta = session.get("metadata") or {}
    lien_soin, lien_cab = PAYMENT_LINKS.get(session.get("payment_link") or "", ("", ""))
    soin_key = (meta.get("soin") or lien_soin).lower().strip()
    cab_key = (meta.get("cabinet") or lien_cab or "narbonne").lower().strip()
    cab = CABINETS.get(cab_key, CABINETS["narbonne"])
    soin, duree, soin_notion = SOINS.get(soin_key, ("Soin Lymphatic Care", "", "Séance Découverte"))

    cust = session.get("customer_details") or {}
    acheteur = (cust.get("name") or "").strip()
    prenom = acheteur.split(" ")[0] if acheteur else ""
    email = (cust.get("email") or "").strip()
    telephone = (cust.get("phone") or "").strip()
    beneficiaire = _custom_field(session, "beneficiaire") or acheteur or "—"
    message = _custom_field(session, "message")
    montant = (session.get("amount_total") or 0) / 100

    test = not livemode
    code = _new_code(cab["prefixe"], test)
    today = date.today()
    fin = today + timedelta(days=VALIDITE_JOURS)
    validite = fin.strftime("%d/%m/%Y")

    pdf = build_giftcard_pdf(
        soin=soin, duree=duree, beneficiaire=beneficiaire, de_la_part_de=prenom,
        message=message, code=code, valable_jusqu_au=validite,
        cabinet_ligne1=cab["ligne1"], cabinet_ligne2=cab["ligne2"],
        logo_path=os.path.join(ASSETS_DIR, "giftcard_logo.jpg"),
        background_path=os.path.join(ASSETS_DIR, f"giftcard_bg_{soin_key}.jpg"),
    )
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, f"{code}.pdf"), "wb") as fh:
        fh.write(pdf)
    lien_pdf = f"{PUBLIC_BASE}/webhook/giftcard/pdf/{code}?t={_sign(code)}"

    d = dict(code=code, soin=soin, soin_notion=soin_notion, cabinet=cab["nom"], montant=montant,
             beneficiaire=beneficiaire, message=message, acheteur=acheteur, email=email,
             telephone=telephone, date_achat=today.isoformat(), validite=validite,
             validite_iso=fin.isoformat(), lien_pdf=lien_pdf, session_id=session_id, test=test)

    notion_url = await _notion_create(d)

    if cab_key == "montpellier" and NOTION_DB_MONTPELLIER:
        try:
            await _notion_create(d, database_id=NOTION_DB_MONTPELLIER)
        except Exception as e:
            logger.error(f"[BON] Erreur duplication Notion Montpellier : {e}")

    dest_acheteur = override_to or email
    ok_acheteur = False
    if dest_acheteur:
        ok_acheteur = await _brevo_send(
            dest_acheteur, acheteur,
            f"{'[TEST] ' if test else ''}Votre bon cadeau Lymphatic Care — {soin}",
            _email_acheteur(prenom, soin, duree, beneficiaire, code, validite, cab, lien_pdf),
            pdf=pdf, pdf_name=f"Bon-cadeau-Lymphatic-Care-{code}.pdf", reply_to=cab.get("mail", MAIL_CABINET),
        )
    ok_cabinet = await _brevo_send(
        override_to or cab.get("mail", MAIL_CABINET), f"Lymphatic Care {cab['nom']}",
        f"{'[TEST] ' if test else ''}🎁 Bon cadeau vendu — {soin} — {montant:.0f} € — {beneficiaire}",
        _email_cabinet(d, notion_url, lien_pdf), pdf=pdf,
        pdf_name=f"Bon-cadeau-{code}.pdf", reply_to=email or None,
    )

    try:
        await telegram.send_message(
            f"🎁 <b>Bon cadeau vendu</b>{' (TEST)' if test else ''}\n{escape(soin)} — {montant:.0f} €\n"
            f"Pour : {escape(beneficiaire)}\nAcheteur : {escape(acheteur or '—')} ({escape(email or '—')})\n"
            f"Code : <code>{code}</code>\nEmail client : {'✅' if ok_acheteur else '❌'} · "
            f"Notion : {'✅' if notion_url else '❌'}"
        )
    except Exception:
        pass

    logger.info(f"[BON] {code} | {soin} | {montant} € | client={ok_acheteur} cabinet={ok_cabinet} notion={bool(notion_url)}")
    return {"status": "ok", "code": code, "email_client": ok_acheteur, "email_cabinet": ok_cabinet,
            "notion": bool(notion_url), "pdf": lien_pdf}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/giftcard/stripe")
async def giftcard_stripe(request: Request):
    ip = _client_ip(request)
    allowed = await _stripe_webhook_ips()
    if ip not in allowed:
        logger.warning(f"[BON] Appel refusé : IP {ip} hors liste Stripe")
        raise HTTPException(status_code=403, detail="Forbidden")
    event = await request.json()
    if event.get("type") != "checkout.session.completed":
        return {"status": "ignored", "type": event.get("type")}
    session = (event.get("data") or {}).get("object") or {}
    return await process_session(session, livemode=bool(event.get("livemode")))


@router.post("/giftcard/test")
async def giftcard_test(request: Request, x_webhook_secret: Optional[str] = Header(None)):
    """Simule un achat (mode TEST) pour vérifier le PDF, les emails et Notion.
    Corps JSON : {"soin": "visage", "beneficiaire": "...", "message": "...",
                  "acheteur": "...", "email": "...", "to": "adresse de test"}"""
    if not config.WEBHOOK_SECRET or x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret invalide")
    b = await request.json()
    prix_par_cabinet = {
        "narbonne": {"decouverte": 7000, "corps": 13000, "visage": 16000, "jambes": 6000,
                     "sportif": 6000, "enceinte": 6000},
        "montpellier": {"decouverte": 7000, "corps": 14000, "visage": 18000, "jambes": 6000,
                        "sportif": 6000, "enceinte": 6000},
    }
    soin = b.get("soin", "decouverte")
    cabinet = b.get("cabinet", "narbonne")
    prix = prix_par_cabinet.get(cabinet, prix_par_cabinet["narbonne"])
    session = {
        "id": f"test_{int(time.time())}", "payment_status": "paid",
        "amount_total": prix.get(soin, 0), "metadata": {"soin": soin, "cabinet": cabinet},
        "customer_details": {"name": b.get("acheteur", "Sophie Test"), "email": b.get("email", ""),
                             "phone": b.get("telephone", "")},
        "custom_fields": [
            {"key": "beneficiaire", "type": "text", "text": {"value": b.get("beneficiaire", "Marie Test")}},
            {"key": "message", "type": "text", "text": {"value": b.get("message", "")}},
        ],
    }
    return await process_session(session, livemode=False, override_to=b.get("to"))


@router.get("/giftcard/pdf/{code}")
async def giftcard_pdf(code: str, t: str = ""):
    if not hmac.compare_digest(t, _sign(code)):
        raise HTTPException(status_code=404, detail="Introuvable")
    path = os.path.join(DATA_DIR, f"{code}.pdf")
    if not os.path.exists(path) or "/" in code:
        raise HTTPException(status_code=404, detail="Introuvable")
    return Response(open(path, "rb").read(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Bon-cadeau-{code}.pdf"'})
