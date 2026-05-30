"""
Webhook Tally — Lymphatic Care Agent
Reçoit les formulaires landing page, Instagram, LinkedIn.
Les données arrivent déjà structurées (pas besoin de parser un email).
"""

from fastapi import APIRouter, HTTPException, Header
from loguru import logger
from typing import Optional

from config import config
from models.lead import (
    LeadTally, ScoringResult, Scores, Classification, Confiance, BriefFranck,
)
from agents.scoring import scoring_engine
from integrations.llm import llm_client
from integrations.brevo import (
    create_or_update_contact, trigger_automation, send_transactional_email,
)
from integrations.notion import create_lead_card
from prompts.tally_prompt import SYSTEM_PROMPT_TALLY, build_user_prompt
from prompts.brief_prompt import SYSTEM_PROMPT_BRIEF, build_brief_prompt


router = APIRouter()


# ------------------------------------------------------------------
# Templates emails (réutilisent la logique de webhook_indeed)
# ------------------------------------------------------------------

async def envoyer_email_hot(result: ScoringResult):
    """Email avec lien Calendly pour les leads HOT."""
    html = f"""
    <p>Bonjour {result.prenom},</p>
    <p>Merci pour votre intérêt pour Lymphatic Care.</p>
    <p>Votre profil correspond à ce que nous recherchons.
    Franck et Émilie, les fondateurs, souhaitent vous rencontrer
    en visio pour vous présenter le modèle en détail.</p>
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
        subject="Votre demande Lymphatic Care — Prochaine étape",
        html_content=html,
    )


async def envoyer_email_declin(result: ScoringResult):
    """Email de déclin poli pour les profils non éligibles."""
    html = f"""
    <p>Bonjour {result.prenom},</p>
    <p>Merci de l'intérêt que vous portez à Lymphatic Care.</p>
    <p>Notre réseau est exclusivement accessible aux professionnels
    de santé diplômés d'État (infirmiers, kinésithérapeutes, paramédicaux).</p>
    <p>Votre profil ne correspond pas aux critères d'accès à ce stade.
    Nous vous souhaitons une belle suite !</p>
    <p>Cordialement,<br>L'équipe Lymphatic Care</p>
    """
    await send_transactional_email(
        to_email=result.email,
        to_name=result.prenom,
        subject="Votre demande Lymphatic Care",
        html_content=html,
    )


async def alerter_franck(result: ScoringResult):
    """Alerte interne Franck pour les leads HOT."""
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
      <tr><td><b>Profession</b></td><td>{result.profession_detectee or "?"}</td></tr>
      <tr><td><b>Score</b></td><td>{result.scores.total}/21</td></tr>
      <tr><td><b>Source</b></td><td>{result.source.value}</td></tr>
      <tr><td><b>Région</b></td><td>{result.region_detectee or "Non précisée"}</td></tr>
      <tr><td><b>Email</b></td><td>{result.email}</td></tr>
      <tr><td><b>Téléphone</b></td><td>{result.telephone or "—"}</td></tr>
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


# ------------------------------------------------------------------
# Route principale
# ------------------------------------------------------------------

@router.post("/tally")
async def webhook_tally(
    lead: LeadTally,
    x_webhook_secret: Optional[str] = Header(None),
):
    """
    Reçoit une soumission Tally (landing page, Instagram, LinkedIn).
    Pipeline : Mistral scoring → classification → routing actions.
    """
    # Vérification secret webhook
    if config.WEBHOOK_SECRET and x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret webhook invalide")

    logger.info(f"Nouveau lead Tally ({lead.source.value}) : {lead.email}")

    # Appel LLM rapide (gpt-4o-mini) pour scoring structuré
    user_prompt = build_user_prompt(lead)
    try:
        raw = await llm_client.score(
            system=SYSTEM_PROMPT_TALLY,
            user=user_prompt,
            temperature=0.2,
        )
        data = await llm_client.parse_json_response(raw)
    except Exception as e:
        logger.error(f"Erreur LLM Tally {lead.email} : {e}")
        raise HTTPException(status_code=500, detail="Erreur analyse LLM")

    if not data:
        logger.error(f"JSON LLM vide pour {lead.email}")
        raise HTTPException(status_code=500, detail="Réponse LLM invalide")

    # --- Construction des scores ---
    # Sécurité : si Mistral hallucine un q1=3 pour une esthéticienne,
    # on recalcule q1 côté code à partir du champ profession structuré.
    s = data.get("scores", {})
    q1_llm = int(s.get("q1_profession", 0))
    q1_code = scoring_engine.scorer_profession(lead.profession or "")
    # On garde le plus prudent des deux (min) pour éviter les faux positifs.
    q1 = min(q1_llm, q1_code) if q1_code > 0 else q1_llm

    try:
        scores = Scores(
            q1_profession=q1,
            q2_motivation=int(s.get("q2_motivation", 0)),
            q3_maturite=int(s.get("q3_maturite", 0)),
            q4_entrepreneuriat=int(s.get("q4_entrepreneuriat", 0)),
            q5_geographie=int(s.get("q5_geographie", 0)),
            q6_financement=int(s.get("q6_financement", 0)),
            q7_projection=int(s.get("q7_projection", 0)),
            bonus=max(0, int(s.get("bonus", 0))),
            malus=min(0, int(s.get("malus", 0))),
        )
    except (ValueError, TypeError) as e:
        logger.error(f"Scores invalides pour {lead.email} : {e} — data={s}")
        raise HTTPException(status_code=500, detail="Scores Mistral invalides")

    # --- Confiance ---
    # Calcul code = check sur la richesse des champs structurés
    nb_champs = sum(1 for v in [lead.profession, lead.situation, lead.region, lead.horizon] if v)
    a_message = bool(lead.message and len(lead.message) > 20)
    confiance_code = scoring_engine.calculer_confiance(a_message, nb_champs)
    confiance_llm_str = data.get("confiance", "MOYENNE")
    confiance_llm = (
        Confiance(confiance_llm_str)
        if confiance_llm_str in ("HAUTE", "MOYENNE", "FAIBLE")
        else Confiance.MOYENNE
    )
    # On prend la confiance la plus prudente (FAIBLE > MOYENNE > HAUTE en priorité de prudence)
    priorite = {Confiance.FAIBLE: 0, Confiance.MOYENNE: 1, Confiance.HAUTE: 2}
    confiance = confiance_code if priorite[confiance_code] <= priorite[confiance_llm] else confiance_llm

    # --- Classification (autorité = code, pas LLM) ---
    classification, action = scoring_engine.classifier(scores, confiance)

    # --- Brief Franck si HOT ---
    brief_data = data.get("brief_franck") or {}
    brief = None
    if classification == Classification.HOT and brief_data:
        brief = BriefFranck(
            a_retenir=brief_data.get("a_retenir", "")[:500],
            angle_closing=brief_data.get("angle_closing", "")[:500],
            objection_probable=brief_data.get("objection_probable", "")[:500],
        )

    # --- Signaux additionnels via détection regex (renforce Mistral) ---
    signaux_positifs = list(data.get("signaux_positifs") or [])
    signaux_negatifs = list(data.get("signaux_negatifs") or [])
    if lead.message:
        signaux_positifs += [
            s for s in scoring_engine.detecter_signaux_positifs(lead.message)
            if s not in signaux_positifs
        ]
        signaux_negatifs += [
            s for s in scoring_engine.detecter_signaux_negatifs(lead.message)
            if s not in signaux_negatifs
        ]

    result = ScoringResult(
        prenom=lead.prenom,
        nom=lead.nom,
        email=lead.email,
        telephone=lead.telephone,
        source=lead.source,
        scores=scores,
        classification=classification,
        confiance=confiance,
        profession_detectee=data.get("profession_detectee") or lead.profession,
        situation_detectee=data.get("situation_detectee") or lead.situation,
        region_detectee=data.get("region_detectee") or lead.region,
        signaux_positifs=signaux_positifs[:10],
        signaux_negatifs=signaux_negatifs[:10],
        raison_classification=data.get("raison_classification", "")[:500],
        action=action,
        brief_franck=brief,
        notes=data.get("notes_pour_franck", "")[:500] or None,
    )

    logger.info(
        f"Lead Tally {lead.email} → {classification.value} "
        f"(score {scores.total}, confiance {confiance.value})"
    )

    # --- Routing actions ---
    # Brevo : toujours créer/màj le contact (sauf si DISQUALIFIED ? on le crée quand même pour archivage)
    await create_or_update_contact(result)

    if classification == Classification.HOT:
        # Brief Franck via gpt-4o (regénère ou complète le brief Tally)
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
                    "texte_libre": lead.message,
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
            logger.error(f"Erreur brief Franck Tally {lead.email} : {e}")

        await create_lead_card(result)
        await envoyer_email_hot(result)
        await alerter_franck(result)

    elif classification in (Classification.WARM, Classification.COLD):
        await create_lead_card(result)
        await trigger_automation(result)

    elif classification == Classification.DISQUALIFIED:
        await envoyer_email_declin(result)

    return {
        "status": "ok",
        "email": lead.email,
        "classification": classification.value,
        "score": scores.total,
        "confiance": confiance.value,
        "action": action.value,
    }
