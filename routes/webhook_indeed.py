"""
Webhook Indeed — Lymphatic Care Agent
Reçoit les candidatures parsées depuis Make (email Indeed).
Effectue une analyse silencieuse via Mistral.
"""

from fastapi import APIRouter, HTTPException, Header, Request
from loguru import logger
from typing import Optional

import re
from pydantic import BaseModel, field_validator

from config import config
from models.lead import LeadIndeed, ScoringResult, Classification, Action, BriefFranck
from agents.scoring import scoring_engine
from integrations.llm import llm_client
from integrations.brevo import create_or_update_contact, trigger_automation, send_transactional_email
from integrations.notion import create_lead_card
from prompts.indeed_prompt import SYSTEM_PROMPT_INDEED, build_user_prompt
from prompts.brief_prompt import SYSTEM_PROMPT_BRIEF, build_brief_prompt


# Prompt pour extraire les champs d'un email Indeed brut
EXTRACT_PROMPT_INDEED = """Tu reçois le contenu brut d'un email de candidature Indeed envoyé à Lymphatic Care.

Extrait les champs suivants en JSON STRICT, sans markdown, sans texte avant/après :
{
  "prenom": "Prénom du candidat",
  "nom": "Nom du candidat",
  "email": "Email du candidat. Accepte les adresses anonymisees @indeedemail.com (format normal Indeed). REFUSE seulement no-reply@indeed.com et indeedapply@indeed.com.",
  "telephone": "Numéro de téléphone FR du candidat si trouvé n'importe où dans le texte. Patterns à chercher : 0X XX XX XX XX (avec espaces, points ou tirets) ou +33 6/7 XX XX XX XX. Cherche AGRESSIVEMENT dans la lettre de motivation, les messages de relance, les questions de présélection, la signature email. Si tu vois 'Mme/Mlle/M. NOM 06.XX.XX.XX.XX' ou 'Téléphone: ...' ou similaire, capture-le. Sinon null.",
  "lettre_motivation": "Texte intégral de la lettre/message de motivation du candidat",
  "reponse_q1_profession": "PROFESSION ACTUELLE DU CANDIDAT. Indeed l'affiche apres 'Expérience pertinente :' dans le corps de l'email (ex: 'Infirmière centre de dermatologie chez Dermae', 'Aide soignante jour/nuit vacataire', 'Kinésithérapeute libérale'). EXTRAIRE le texte qui suit 'Expérience pertinente :' jusqu'a la fin de ligne. C'EST OBLIGATOIRE si le snippet existe.",
  "reponse_q2_situation": "Réponse situation libéral/salarié/reconversion si trouvée, sinon null",
  "reponse_q3_region": "Ville/region trouvee (souvent dans subject ou apres profession), sinon null",
  "reponse_q4_motivation": "Réponses aux 'Questions de présélection' Indeed (financement, délai, motivation) si trouvées, sinon null"
}

REGLES :
1. Email candidat : accepter @indeedemail.com (relais Indeed valide). Refuser uniquement no-reply@indeed.com et indeedapply@indeed.com.
2. reponse_q1_profession : SI le texte contient "Expérience pertinente :", tu DOIS extraire la phrase qui suit. Ne mets jamais null si ce snippet existe.
3. Sinon, mets null."""


class IndeedRawEmail(BaseModel):
    """Payload pour /webhook/indeed/raw — email Indeed brut depuis Make.

    Make envoie `null` (et non "") quand un email n'a pas de partie texte OU
    pas de partie HTML. Sans coercition, pydantic rejette ce null avec un 422
    AVANT que l'endpoint ne tourne → la candidature est silencieusement perdue.
    Le validateur ci-dessous convertit tout null/non-str en chaîne vide.
    """
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    from_email: str = ""

    @field_validator("subject", "body_text", "body_html", "from_email", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return "" if v is None else (v if isinstance(v, str) else str(v))


def _clean_html(html: str) -> str:
    """Nettoie le HTML brut pour extraire le texte utile."""
    if not html:
        return ""
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
    html = html.replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    html = re.sub(r"\s+", " ", html).strip()
    return html


router = APIRouter()


async def envoyer_email_hot(result: ScoringResult):
    """Envoie l'email avec lien Calendly au lead HOT."""
    html = f"""
    <p>Bonjour {result.prenom},</p>
    <p>Votre profil a retenu toute notre attention.</p>
    <p>Franck et Émilie, les fondateurs de Lymphatic Care,
    souhaitent vous rencontrer en visio pour vous présenter
    le modèle en détail.</p>
    <p><a href="{config.CALENDLY_LINK}" style="
        background:#2d5c47;color:white;padding:12px 24px;
        text-decoration:none;border-radius:6px;font-weight:bold;
    ">Réserver mon créneau (30 min)</a></p>
    <p>Cet appel est sans engagement.<br>
    À très bientôt,<br>
    L'équipe Lymphatic Care</p>
    """
    await send_transactional_email(
        to_email=result.email,
        to_name=result.prenom,
        subject="Votre candidature Lymphatic Care — Prochaine étape",
        html_content=html,
    )


async def envoyer_email_declin(result: ScoringResult):
    """Envoie l'email de déclin poli au lead disqualifié."""
    html = f"""
    <p>Bonjour {result.prenom},</p>
    <p>Merci de l'intérêt que vous portez à Lymphatic Care.</p>
    <p>Après étude de votre profil, notre réseau est exclusivement
    accessible aux professionnels de santé diplômés d'État
    (infirmiers, kinésithérapeutes, paramédicaux).</p>
    <p>Votre candidature ne correspond pas aux critères d'accès
    à ce stade. Nous vous souhaitons une belle suite !</p>
    <p>Cordialement,<br>L'équipe Lymphatic Care</p>
    """
    await send_transactional_email(
        to_email=result.email,
        to_name=result.prenom,
        subject="Votre candidature Lymphatic Care",
        html_content=html,
    )


async def alerter_franck_nouveau_lead(result: ScoringResult, indeed_email: str = ""):
    """Alerte email a Franck pour chaque nouveau WARM ou HOT.
    Contient infos du candidat + lien mailto pour repondre via Indeed Messages."""
    import urllib.parse
    classif = result.classification.value
    emoji = "🔥" if result.classification == Classification.HOT else "🟠"

    # Construction du lien mailto avec TEMPLATE WARM J+0 COMPLET en plain text pre-rempli
    mailto_link = ""
    if indeed_email and "@indeedemail.com" in indeed_email:
        subj = "Votre candidature Lymphatic Care — notre équipe l'examine"
        body_plain = (
            f"Bonjour {result.prenom},\n\n"
            "Merci pour l'intérêt que vous portez à Lymphatic Care.\n\n"
            "Nous avons bien reçu votre candidature et notre équipe l'examine avec attention. "
            "Tous les profils ne correspondent pas à ce que nous recherchons — et c'est précisément "
            "pourquoi nous prenons le temps d'étudier chaque dossier individuellement.\n\n"
            "Ce que Lymphatic Care n'est pas :\n"
            "Nous ne vendons pas une formation. Nous ne vous formons pas pour vous laisser seul "
            "face à votre activité. Ce n'est pas notre modèle, ce ne sont pas nos valeurs.\n\n"
            "Ce que Lymphatic Care est vraiment :\n\n"
            "🤝 Une vraie équipe, pas un réseau anonyme\n"
            "Vous rejoignez une communauté de soignants et d'anciens soignants qui ont choisi "
            "de redonner du sens à leur métier. Vous ne serez jamais seul — de l'installation "
            "au quotidien, nous vous accompagnons de A à Z.\n\n"
            "🌿 Une méthode éprouvée depuis près de 4 ans\n"
            "Développée par Franck et Émilie, anciens professionnels du soin d'urgence, et "
            "validée par des centaines de patients. Le soin reste au cœur de tout ce que nous "
            "faisons.\n\n"
            "📍 Un réseau qui grandit — moderne et structuré\n"
            "Cabinet pilote à Narbonne, licencié installé à Montpellier, bientôt Bordeaux, "
            "développement national en cours. Un modèle entrepreneurial clé en main, conçu pour "
            "des soignants qui veulent entreprendre sans se perdre.\n\n"
            "Nous reviendrons vers vous dans les prochains jours pour un premier échange "
            "téléphonique, si votre profil correspond à nos critères de sélection.\n\n"
            "Vous pouvez aussi gagner du temps en réservant directement un créneau pour un appel "
            "de 15 minutes :\n\n"
            "📞 Réserver mon créneau (15 min) :\n"
            "https://calendly.com/lymphatic-care/nouvelle-reunion\n\n"
            "À très vite,\n\n"
            "Franck Meuric & Émilie Daulat\n"
            "Cofondateurs — Lymphatic Care\n"
            "reseau@lymphaticcare.fr\n"
            "www.lymphaticcare.fr\n\n"
            "— Sens, Soin & Liberté"
        )
        mailto_link = (
            f"mailto:{indeed_email}"
            f"?subject={urllib.parse.quote(subj)}"
            f"&body={urllib.parse.quote(body_plain)}"
        )

    html = f"""
    <h2 style="color:#2d5c47;">{emoji} NOUVEAU LEAD {classif} — {result.prenom} {result.nom}</h2>
    <table cellpadding="6" style="border-collapse: collapse;">
      <tr><td><b>Profession</b></td><td>{result.profession_detectee or 'Non précisée'}</td></tr>
      <tr><td><b>Région</b></td><td>{result.region_detectee or 'Non précisée'}</td></tr>
      <tr><td><b>Score</b></td><td>{result.scores.total}/21</td></tr>
      <tr><td><b>Confiance</b></td><td>{result.confiance.value}</td></tr>
      <tr><td><b>Email Indeed (relay)</b></td><td>{indeed_email or result.email}</td></tr>
    </table>
    <h3>Signaux positifs</h3>
    <ul>{"".join(f"<li>{s}</li>" for s in (result.signaux_positifs or [])) or "<li>(aucun détecté)</li>"}</ul>
    <h3>Signaux négatifs</h3>
    <ul>{"".join(f"<li>{s}</li>" for s in (result.signaux_negatifs or [])) or "<li>(aucun détecté)</li>"}</ul>
    {f'<p><a href="{mailto_link}" style="background:#2d5c47;color:white;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block;">📧 Répondre maintenant au candidat</a></p>' if mailto_link else ''}
    <hr>
    <p style="font-size:12px;color:#888;">Auto-alerte agent Lymphatic Care — voir Notion pour la fiche complète</p>
    """
    try:
        await send_transactional_email(
            to_email="lymphaticcare.fr@gmail.com",
            to_name="Franck",
            subject=f"{emoji} {classif} : {result.prenom} {result.nom} ({result.scores.total}/21) — {result.profession_detectee or 'N/A'}",
            html_content=html,
        )
        logger.info(f"Alerte Franck envoyee pour {result.prenom} {result.nom} ({classif})")
    except Exception as e:
        logger.error(f"Echec alerte Franck : {e}")

    # === Alerte Telegram (en parallèle de l'email) ===
    try:
        from integrations.telegram import send_message as tg_send
        sig_pos = ", ".join(result.signaux_positifs[:3]) if result.signaux_positifs else "—"
        tg_text = (
            f"{emoji} <b>NOUVEAU LEAD {classif}</b>\n"
            f"<b>{result.prenom} {result.nom}</b>\n\n"
            f"👤 {result.profession_detectee or 'Profession non précisée'}\n"
            f"📍 {result.region_detectee or 'Région non précisée'}\n"
            f"⭐ Score : <b>{result.scores.total}/21</b> ({result.confiance.value})\n"
            f"📧 {indeed_email or result.email}\n"
        )
        if result.signaux_positifs:
            tg_text += f"\n✅ {sig_pos}"
        if result.notes:
            tg_text += f"\n\n💡 <i>{result.notes[:300]}</i>"
        tg_text += "\n\n→ Voir email pour bouton Répondre + Notion pour la fiche"
        await tg_send(tg_text)
    except Exception as e:
        logger.error(f"Echec alerte Telegram : {e}")


async def alerter_franck(result: ScoringResult):
    """Envoie l'alerte interne à Franck pour un lead HOT."""
    brief = ""
    if result.brief_franck:
        brief = f"""
        <p><b>À retenir :</b> {result.brief_franck.a_retenir}</p>
        <p><b>Angle closing :</b> {result.brief_franck.angle_closing}</p>
        <p><b>Objection probable :</b> {result.brief_franck.objection_probable}</p>
        """

    html = f"""
    <h2>🔥 LEAD HOT — {result.prenom} {result.nom}</h2>
    <table>
      <tr><td><b>Profession</b></td><td>{result.profession_detectee}</td></tr>
      <tr><td><b>Score</b></td><td>{result.scores.total}/21</td></tr>
      <tr><td><b>Source</b></td><td>{result.source.value}</td></tr>
      <tr><td><b>Région</b></td><td>{result.region_detectee or "Non précisée"}</td></tr>
      <tr><td><b>Email</b></td><td>{result.email}</td></tr>
      <tr><td><b>Confiance</b></td><td>{result.confiance.value}</td></tr>
    </table>
    <hr>
    {brief}
    <p><b>Signaux positifs :</b> {", ".join(result.signaux_positifs) or "Aucun détecté"}</p>
    <p><b>Notes :</b> {result.notes or ""}</p>
    """

    await send_transactional_email(
        to_email=config.MAIL_FRANCK,
        to_name="Franck",
        subject=f"🔥 LEAD HOT — {result.prenom} {result.nom} — Score {result.scores.total}/21",
        html_content=html,
    )


@router.post("/indeed")
async def webhook_indeed(
    lead: LeadIndeed,
    x_webhook_secret: Optional[str] = Header(None),
    replay: bool = False,
):
    """
    Reçoit une candidature Indeed depuis Make.
    Analyse silencieuse → scoring → routing.

    replay=True (backfill historique) : on écrit UNIQUEMENT la fiche Notion,
    sans aucun envoi sortant (pas d'email candidat, pas d'alerte Franck/Telegram,
    pas de Brevo). Sert à récupérer les leads perdus sans spammer ni re-contacter.
    """
    # Vérification secret webhook
    if config.WEBHOOK_SECRET and x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret webhook invalide")

    logger.info(f"Nouveau lead Indeed : {lead.email}")

    # Construction du prompt utilisateur
    user_prompt = build_user_prompt(lead)

    # Appel LLM rapide (gpt-4o-mini) pour analyse silencieuse
    try:
        raw_response = await llm_client.score(
            system=SYSTEM_PROMPT_INDEED,
            user=user_prompt,
            temperature=0.2,
        )
        scoring_data = await llm_client.parse_json_response(raw_response)
    except Exception as e:
        logger.error(f"Erreur LLM scoring pour {lead.email} : {e}")
        raise HTTPException(status_code=500, detail="Erreur analyse LLM")

    if not scoring_data:
        logger.error(f"JSON vide pour {lead.email}")
        raise HTTPException(status_code=500, detail="Réponse Mistral invalide")

    # Parsing du résultat
    from models.lead import Scores, Confiance
    scores = Scores(
        q1_profession=scoring_data.get("scores", {}).get("eligibilite_profession", 0),
        q2_motivation=scoring_data.get("scores", {}).get("qualite_motivation", 0),
        q3_maturite=scoring_data.get("scores", {}).get("coherence_geographique", 0),
        q4_entrepreneuriat=scoring_data.get("scores", {}).get("signaux_entrepreneuriaux", 0),
        q5_geographie=scoring_data.get("scores", {}).get("coherence_geographique", 0),
        q6_financement=0,
        q7_projection=0,
        bonus=scoring_data.get("scores", {}).get("bonus", 0),
        malus=scoring_data.get("scores", {}).get("malus", 0),
    )

    confiance_str = scoring_data.get("confiance", "MOYENNE")
    confiance = Confiance(confiance_str) if confiance_str in ["HAUTE", "MOYENNE", "FAIBLE"] else Confiance.MOYENNE

    # On utilise EN PRIORITE reponse_q1_profession (extracted depuis "Expérience pertinente")
    # car le scorer LLM met souvent profession_detectee="NON PRÉCISÉE" même quand le candidat
    # est une infirmière clairement identifiée dans le snippet Indeed.
    profession_effective = (
        (lead.reponse_q1_profession or "").strip()
        or scoring_data.get("profession_detectee", "")
        or ""
    )
    classification, action = scoring_engine.classifier_with_profession_check(
        scores, confiance, profession_effective
    )

    result = ScoringResult(
        prenom=lead.prenom,
        nom=lead.nom,
        email=lead.email,
        telephone=lead.telephone,
        source=lead.source,
        scores=scores,
        classification=classification,
        confiance=confiance,
        profession_detectee=scoring_data.get("profession_detectee"),
        region_detectee=scoring_data.get("region_detectee"),
        signaux_positifs=scoring_data.get("signaux_positifs", []),
        signaux_negatifs=scoring_data.get("signaux_negatifs", []),
        raison_classification=scoring_data.get("raison_classification", ""),
        action=action,
        notes=scoring_data.get("notes_pour_franck"),
    )

    logger.info(f"Lead {lead.email} classé : {classification.value} (score {scores.total})")

    # === Mode REPLAY : backfill Notion uniquement, zéro envoi sortant ===
    if replay:
        await create_lead_card(result)
        logger.info(f"[REPLAY] Fiche Notion seule pour {lead.email} ({classification.value})")
        return {
            "status": "ok",
            "replay": True,
            "email": lead.email,
            "prenom": lead.prenom,
            "nom": lead.nom,
            "classification": classification.value,
            "score": scores.total,
        }

    # Actions selon classification
    await create_or_update_contact(result)

    if classification == Classification.HOT:
        # Génération brief Franck qualité via gpt-4o
        try:
            brief_raw = await llm_client.brief(
                system=SYSTEM_PROMPT_BRIEF,
                user=build_brief_prompt({
                    "prenom": lead.prenom,
                    "nom": lead.nom,
                    "profession_detectee": result.profession_detectee,
                    "region_detectee": result.region_detectee,
                    "source": lead.source.value,
                    "score_total": scores.total,
                    "signaux_positifs": result.signaux_positifs,
                    "signaux_negatifs": result.signaux_negatifs,
                    "raison_classification": result.raison_classification,
                    "texte_libre": lead.lettre_motivation,
                }),
                temperature=0.5,
            )
            brief_data = await llm_client.parse_json_response(brief_raw)
            if brief_data:
                result.brief_franck = BriefFranck(
                    a_retenir=str(brief_data.get("a_retenir", ""))[:500],
                    angle_closing=str(brief_data.get("angle_closing", ""))[:500],
                    objection_probable=str(brief_data.get("objection_probable", ""))[:500],
                )
        except Exception as e:
            logger.error(f"Erreur génération brief Franck pour {lead.email} : {e}")

        await create_lead_card(result)
        await envoyer_email_hot(result)
        await alerter_franck(result)
        # Alerte synthetique a Franck (avec lien mailto pour repondre direct)
        await alerter_franck_nouveau_lead(result, indeed_email=lead.email)

    elif classification == Classification.WARM:
        # Ecrit aussi dans la base Notion correspondante pour visibilite Franck
        await create_lead_card(result)
        await trigger_automation(result)
        # Alerte synthetique a Franck (mailto link pour reply rapide)
        await alerter_franck_nouveau_lead(result, indeed_email=lead.email)

    elif classification == Classification.COLD:
        await create_lead_card(result)
        await trigger_automation(result)

    elif classification == Classification.DISQUALIFIED:
        # Trace aussi le disqualifie dans Notion (base Froids, Statut "Perdu")
        await create_lead_card(result)
        await envoyer_email_declin(result)

    return {
        "status": "ok",
        "email": lead.email,
        "prenom": lead.prenom,
        "nom": lead.nom,
        "classification": classification.value,
        "score": scores.total,
        "action": action.value,
        "profession": result.profession_detectee or "",
        "region": result.region_detectee or "",
    }


async def _parse_raw_payload(request: Request) -> IndeedRawEmail:
    """Lit le corps de la requête de façon TOLÉRANTE.

    Make ne sait pas produire du JSON fiable (le contenu des emails contient des
    guillemets / retours-ligne qui cassent le template → 422 JSON invalide).
    On accepte donc en priorité le form-urlencoded (Make encode chaque champ
    automatiquement, zéro problème d'échappement), avec repli JSON tolérant.
    """
    ct = (request.headers.get("content-type") or "").lower()
    raw = await request.body()

    if "application/x-www-form-urlencoded" in ct or "multipart/form-data" in ct:
        form = await request.form()
        return IndeedRawEmail(
            subject=form.get("subject") or "",
            body_text=form.get("body_text") or "",
            body_html=form.get("body_html") or "",
            from_email=form.get("from_email") or "",
        )

    # Repli JSON tolérant (n'échoue jamais en 422 sur un JSON malformé)
    import json
    data = {}
    try:
        data = json.loads(raw.decode("utf-8", "replace")) if raw else {}
    except Exception as e:
        logger.warning(f"JSON brut illisible, champs vides : {e}")
        data = {}
    if not isinstance(data, dict):
        data = {}
    return IndeedRawEmail(
        subject=data.get("subject") or "",
        body_text=data.get("body_text") or "",
        body_html=data.get("body_html") or "",
        from_email=data.get("from_email") or "",
    )


@router.post("/indeed/raw")
async def webhook_indeed_raw(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
    x_replay: Optional[str] = Header(None),
):
    """
    Reçoit un email Indeed brut depuis Make (subject + body_text + body_html).
    Extrait les champs via LLM puis appelle la logique scoring/routing de /webhook/indeed.
    """
    if config.WEBHOOK_SECRET and x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret webhook invalide")

    payload = await _parse_raw_payload(request)

    logger.info(f"Email Indeed brut reçu (from={payload.from_email}, subject={payload.subject[:60]!r})")

    # === FILTRE MÉTIER (Franck) : garder tous les leads (villes de France) SAUF ===
    # - le recrutement salarié du cabinet pilote de Narbonne ("Temps partiel")
    # - les stagiaires (Stage Community Manager)
    # On filtre sur le TITRE DU POSTE (présent dans le sujet), pas sur le texte
    # libre du candidat (qui pourrait contenir ces mots par hasard).
    _subj = (payload.subject or "").lower()
    EXCLUS = ("temps partiel", "community manager", "stagiaire")
    if any(x in _subj for x in EXCLUS):
        logger.info(f"[SKIP annonce exclue] subject={payload.subject[:80]!r}")
        return {"status": "ignored", "reason": "annonce exclue (salarié Narbonne / stagiaire)"}

    # Compose le corps du mail pour le LLM (préfère text, fallback html nettoyé)
    body = payload.body_text or _clean_html(payload.body_html)
    if not body or len(body) < 30:
        logger.warning("Corps email trop court ou vide, skip")
        raise HTTPException(status_code=400, detail="Corps email vide")

    # Extraction via LLM
    try:
        raw = await llm_client.score(
            system=EXTRACT_PROMPT_INDEED,
            user=f"OBJET : {payload.subject}\n\nCORPS EMAIL :\n{body[:8000]}",
            temperature=0.0,
        )
        extracted = await llm_client.parse_json_response(raw)
    except Exception as e:
        logger.error(f"Erreur extraction LLM Indeed raw : {e}")
        raise HTTPException(status_code=500, detail="Erreur extraction LLM")

    extracted = extracted or {}

    def _clean_val(v):
        s = (str(v) if v is not None else "").strip()
        return "" if s.lower() in ("null", "none", "") else s

    prenom = _clean_val(extracted.get("prenom"))
    nom = _clean_val(extracted.get("nom"))
    cand_email = _clean_val(extracted.get("email"))

    # Email candidat absent du corps → fallback sur l'adresse relais Indeed (expéditeur)
    if "@" not in cand_email:
        relay = _clean_val(payload.from_email)
        cand_email = relay if "@" in relay else ""

    if "@" not in cand_email:
        logger.warning(f"Aucun email exploitable (extrait + relais) : {extracted}")
        raise HTTPException(status_code=422, detail="Aucun email exploitable")

    # Nom/prénom manquants → placeholders (on veut quand même alerter Franck)
    if not prenom:
        prenom = "Candidat"
    if not nom:
        nom = "Indeed"

    extracted["prenom"], extracted["nom"], extracted["email"] = prenom, nom, cand_email

    # Refuse uniquement les vraies no-reply Indeed.
    # On AUTORISE les adresses anonymisées @indeedemail.com qui font office de boîte
    # de relais vers le vrai email du candidat (Indeed forward automatiquement).
    candidate_email = (extracted.get("email") or "").lower()
    if (
        "no-reply@indeed.com" in candidate_email
        or "noreply@indeed.com" in candidate_email
        or "indeedapply@indeed.com" in candidate_email
        or candidate_email.endswith("@indeed.com")
    ):
        logger.warning(f"Email Indeed no-reply détecté : {extracted.get('email')}")
        raise HTTPException(status_code=422, detail="Email no-reply Indeed détecté")

    # Construit LeadIndeed et délègue à la logique existante
    try:
        lead = LeadIndeed(
            prenom=extracted["prenom"][:100],
            nom=extracted["nom"][:100],
            email=extracted["email"][:200],
            telephone=extracted.get("telephone"),
            lettre_motivation=extracted.get("lettre_motivation") or "(aucune lettre)",
            reponse_q1_profession=extracted.get("reponse_q1_profession"),
            reponse_q2_situation=extracted.get("reponse_q2_situation"),
            reponse_q3_region=extracted.get("reponse_q3_region"),
            reponse_q4_motivation=extracted.get("reponse_q4_motivation"),
        )
    except Exception as e:
        logger.error(f"Validation LeadIndeed échouée : {e}")
        raise HTTPException(status_code=422, detail=f"Lead invalide : {e}")

    # Réutilise la logique scoring/routing
    # X-Replay: 1 => backfill Notion seul (aucun envoi sortant)
    replay = str(x_replay).strip() in ("1", "true", "True", "yes")
    return await webhook_indeed(lead, x_webhook_secret, replay=replay)
