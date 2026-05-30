"""
Webhook Conversation — Lymphatic Care Agent
Qualification multi-tours par email / WhatsApp / chat web.

Gère un état via Redis :
- Reçoit une réponse du lead
- Scoring de cette réponse via Mistral
- Renvoie la question suivante OU finalise + déclenche les actions

L'orchestrateur (Make / N8N / webhook chat) est responsable d'envoyer
le texte de la `next_question` au lead.
"""

from fastapi import APIRouter, HTTPException, Header
from loguru import logger
from typing import Optional
from pydantic import BaseModel, EmailStr

from config import config
from models.lead import (
    ConversationState, Scores, ScoringResult, Source, Confiance,
    Classification, BriefFranck,
)
from agents.scoring import scoring_engine
from integrations.llm import llm_client
from integrations.redis_client import conversation_store
from integrations.brevo import (
    create_or_update_contact, trigger_automation, send_transactional_email,
)
from integrations.notion import create_lead_card
from prompts.conversation_prompt import (
    QUESTIONS, MESSAGE_FIN, question_for_step, dimension_for_step,
    SYSTEM_PROMPT_SCORE_REPONSE, build_scoring_prompt,
)
from prompts.brief_prompt import SYSTEM_PROMPT_BRIEF, build_brief_prompt


router = APIRouter()


# ------------------------------------------------------------------
# Modèle d'entrée
# ------------------------------------------------------------------

class ConversationInput(BaseModel):
    """
    Payload reçu pour chaque tour de conversation.
    - 1er appel (initialisation) : il faut prenom, nom, source.
    - Tours suivants : seul `message` est nécessaire (état déjà en Redis).
    """
    lead_email: EmailStr
    message: str = ""
    canal: str = "email"  # email | whatsapp | webui
    # Champs requis uniquement à l'initialisation :
    prenom: Optional[str] = None
    nom: Optional[str] = None
    telephone: Optional[str] = None
    source: Optional[Source] = None


# ------------------------------------------------------------------
# Templates emails (réutilisés de webhook_indeed/tally)
# ------------------------------------------------------------------

async def envoyer_email_hot(result: ScoringResult):
    html = f"""
    <p>Bonjour {result.prenom},</p>
    <p>Merci pour vos réponses détaillées.</p>
    <p>Votre profil correspond à ce que nous recherchons.
    Franck et Émilie, les fondateurs de Lymphatic Care, souhaitent
    vous rencontrer en visio pour vous présenter le modèle.</p>
    <p><a href="{config.CALENDLY_LINK}" style="
        background:#2d5c47;color:white;padding:12px 24px;
        text-decoration:none;border-radius:6px;font-weight:bold;
    ">Réserver mon créneau (30 min)</a></p>
    <p>Sans engagement.<br>À très bientôt,<br>L'équipe Lymphatic Care</p>
    """
    await send_transactional_email(
        to_email=result.email, to_name=result.prenom,
        subject="Votre candidature Lymphatic Care — Prochaine étape",
        html_content=html,
    )


async def envoyer_email_declin(result: ScoringResult):
    html = f"""
    <p>Bonjour {result.prenom},</p>
    <p>Merci pour vos réponses.</p>
    <p>Notre réseau est exclusivement accessible aux professionnels
    de santé diplômés d'État. Votre profil ne correspond pas
    aux critères d'accès à ce stade.</p>
    <p>Cordialement,<br>L'équipe Lymphatic Care</p>
    """
    await send_transactional_email(
        to_email=result.email, to_name=result.prenom,
        subject="Votre candidature Lymphatic Care",
        html_content=html,
    )


async def alerter_franck(result: ScoringResult):
    brief = ""
    if result.brief_franck:
        brief = f"""
        <p><b>À retenir :</b> {result.brief_franck.a_retenir}</p>
        <p><b>Angle closing :</b> {result.brief_franck.angle_closing}</p>
        <p><b>Objection probable :</b> {result.brief_franck.objection_probable}</p>
        """
    html = f"""
    <h2>🔥 LEAD HOT (conversation) — {result.prenom} {result.nom}</h2>
    <table>
      <tr><td><b>Profession</b></td><td>{result.profession_detectee or "?"}</td></tr>
      <tr><td><b>Score</b></td><td>{result.scores.total}/21</td></tr>
      <tr><td><b>Source</b></td><td>{result.source.value}</td></tr>
      <tr><td><b>Région</b></td><td>{result.region_detectee or "?"}</td></tr>
      <tr><td><b>Email</b></td><td>{result.email}</td></tr>
      <tr><td><b>Téléphone</b></td><td>{result.telephone or "—"}</td></tr>
      <tr><td><b>Confiance</b></td><td>{result.confiance.value}</td></tr>
    </table>
    <hr>{brief}
    <p><b>Signaux positifs :</b> {", ".join(result.signaux_positifs) or "—"}</p>
    """
    await send_transactional_email(
        to_email=config.MAIL_FRANCK, to_name="Franck",
        subject=f"🔥 LEAD HOT — {result.prenom} {result.nom} — {result.scores.total}/21",
        html_content=html,
    )


# ------------------------------------------------------------------
# Scoring d'une réponse individuelle via Mistral
# ------------------------------------------------------------------

async def scorer_reponse(dimension: str, question: str, reponse: str) -> dict:
    """
    Appelle Mistral pour scorer une réponse selon sa dimension.
    Retourne {score: int 0-3, extrait_cle, signal_positif, signal_negatif}.
    En cas d'échec retourne un score 0 sûr.
    """
    try:
        raw = await llm_client.score(
            system=SYSTEM_PROMPT_SCORE_REPONSE,
            user=build_scoring_prompt(dimension, question, reponse),
            temperature=0.1,
        )
        data = await llm_client.parse_json_response(raw)
    except Exception as e:
        logger.error(f"Erreur LLM scoring {dimension} : {e}")
        return {"score": 0, "extrait_cle": "", "signal_positif": None, "signal_negatif": None}

    # Garde-fou : score borné 0-3
    try:
        s = int(data.get("score", 0))
        s = max(0, min(3, s))
    except (ValueError, TypeError):
        s = 0

    return {
        "score": s,
        "extrait_cle": str(data.get("extrait_cle") or "")[:150],
        "signal_positif": data.get("signal_positif") or None,
        "signal_negatif": data.get("signal_negatif") or None,
    }


# ------------------------------------------------------------------
# Finalisation de la conversation (Q7 atteinte)
# ------------------------------------------------------------------

async def finaliser_conversation(state: ConversationState) -> dict:
    """
    Construit le ScoringResult final, déclenche les actions,
    supprime l'état Redis et retourne le payload de fin.
    """
    sp = state.scores_partiels
    scores = Scores(
        q1_profession=int(sp.get("q1_profession", 0)),
        q2_motivation=int(sp.get("q2_motivation", 0)),
        q3_maturite=int(sp.get("q3_maturite", 0)),
        q4_entrepreneuriat=int(sp.get("q4_entrepreneuriat", 0)),
        q5_geographie=int(sp.get("q5_geographie", 0)),
        q6_financement=int(sp.get("q6_financement", 0)),
        q7_projection=int(sp.get("q7_projection", 0)),
        bonus=0,
        malus=0,
    )

    # Confiance = HAUTE si 7 réponses non triviales, MOYENNE si <7 ou réponses très courtes
    reponses = [m for m in state.historique if m.get("role") == "user"]
    nb_reponses = len(reponses)
    nb_substantielles = sum(1 for r in reponses if len((r.get("content") or "").strip()) >= 30)
    if nb_reponses >= 7 and nb_substantielles >= 5:
        confiance = Confiance.HAUTE
    elif nb_reponses >= 4 and nb_substantielles >= 2:
        confiance = Confiance.MOYENNE
    else:
        confiance = Confiance.FAIBLE

    classification, action = scoring_engine.classifier(scores, confiance)

    # Détection de signaux globaux sur l'ensemble du texte échangé
    full_text = " ".join(r.get("content", "") for r in reponses)
    signaux_positifs = scoring_engine.detecter_signaux_positifs(full_text)
    signaux_negatifs = scoring_engine.detecter_signaux_negatifs(full_text)

    # Extraction simple : profession = 1ère réponse, région = réponse Q5
    profession_detectee = (reponses[0].get("content", "")[:100] if reponses else None)
    region_detectee = (reponses[4].get("content", "")[:100] if len(reponses) >= 5 else None)

    result = ScoringResult(
        prenom=state.prenom,
        nom=state.nom,
        email=state.lead_email,
        telephone=state.telephone,
        source=state.source,
        scores=scores,
        classification=classification,
        confiance=confiance,
        profession_detectee=profession_detectee,
        region_detectee=region_detectee,
        signaux_positifs=signaux_positifs,
        signaux_negatifs=signaux_negatifs,
        raison_classification=(
            f"Conversation {nb_reponses}/7 réponses, score {scores.total}/21"
        ),
        action=action,
        brief_franck=None,
        notes=f"Lead qualifié par conversation ({state.source.value} / {state.lead_email})",
    )

    logger.info(
        f"Conversation finalisée {state.lead_email} → {classification.value} "
        f"(score {scores.total}, confiance {confiance.value})"
    )

    # Actions routing
    await create_or_update_contact(result)

    if classification == Classification.HOT:
        # Brief Franck via gpt-4o
        try:
            brief_raw = await llm_client.brief(
                system=SYSTEM_PROMPT_BRIEF,
                user=build_brief_prompt({
                    "prenom": state.prenom,
                    "nom": state.nom,
                    "profession_detectee": result.profession_detectee,
                    "region_detectee": result.region_detectee,
                    "source": state.source.value,
                    "score_total": scores.total,
                    "signaux_positifs": result.signaux_positifs,
                    "signaux_negatifs": result.signaux_negatifs,
                    "raison_classification": result.raison_classification,
                    "texte_libre": full_text[:1500],
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
            logger.error(f"Erreur brief Franck conversation {state.lead_email} : {e}")

        await create_lead_card(result)
        await envoyer_email_hot(result)
        await alerter_franck(result)
    elif classification in (Classification.WARM, Classification.COLD):
        await create_lead_card(result)
        await trigger_automation(result)
    elif classification == Classification.DISQUALIFIED:
        await envoyer_email_declin(result)

    # Nettoyage Redis
    await conversation_store.delete(state.lead_email)

    return {
        "status": "completed",
        "email": state.lead_email,
        "classification": classification.value,
        "score": scores.total,
        "confiance": confiance.value,
        "action": action.value,
        "next_question": None,
        "message_to_lead": MESSAGE_FIN.format(prenom=state.prenom),
    }


# ------------------------------------------------------------------
# Route principale
# ------------------------------------------------------------------

@router.post("/conversation")
async def webhook_conversation(
    payload: ConversationInput,
    x_webhook_secret: Optional[str] = Header(None),
):
    """
    Gère un tour de conversation de qualification.

    Retourne :
    - `next_question` : texte à envoyer au lead (None si conversation terminée)
    - `message_to_lead` : message d'accompagnement (accueil ou clôture)
    - `etape` : étape courante (0 = avant Q1, 7 = après Q7)
    - `status` : "in_progress" | "completed"
    """
    if config.WEBHOOK_SECRET and x_webhook_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Secret webhook invalide")

    state = await conversation_store.get(payload.lead_email)

    # --- INITIALISATION (1er appel) ---
    if state is None:
        if not (payload.prenom and payload.nom and payload.source):
            raise HTTPException(
                status_code=400,
                detail="Initialisation : prenom, nom et source sont requis au 1er appel",
            )
        state = ConversationState(
            lead_email=payload.lead_email,
            prenom=payload.prenom,
            nom=payload.nom,
            telephone=payload.telephone,
            source=payload.source,
            etape_courante=0,
            historique=[],
            scores_partiels={},
            termine=False,
        )
        logger.info(f"Conversation initialisée : {payload.lead_email} ({payload.source.value})")
        await conversation_store.save(state)

        # Retourne Q1 directement (pas besoin de message pour scorer puisque rien à scorer)
        state.etape_courante = 1
        state.historique.append({
            "role": "assistant",
            "content": question_for_step(1, state.prenom),
        })
        await conversation_store.save(state)

        return {
            "status": "in_progress",
            "etape": 1,
            "next_question": question_for_step(1, state.prenom),
            "message_to_lead": question_for_step(1, state.prenom),
        }

    # --- CONVERSATION DÉJÀ TERMINÉE ---
    if state.termine:
        return {
            "status": "completed",
            "etape": state.etape_courante,
            "next_question": None,
            "message_to_lead": MESSAGE_FIN.format(prenom=state.prenom),
        }

    # --- TOUR SUIVANT : enregistre + score la réponse ---
    if not payload.message:
        # Pas de réponse → on renvoie la même question
        return {
            "status": "in_progress",
            "etape": state.etape_courante,
            "next_question": question_for_step(state.etape_courante, state.prenom),
            "message_to_lead": question_for_step(state.etape_courante, state.prenom),
        }

    # Enregistre la réponse à l'étape courante (1-7)
    etape = state.etape_courante
    state.historique.append({"role": "user", "content": payload.message})

    # Score la réponse
    dimension = dimension_for_step(etape)
    question_texte = question_for_step(etape, state.prenom)
    scoring = await scorer_reponse(dimension, question_texte, payload.message)
    state.scores_partiels[dimension] = scoring["score"]

    logger.info(
        f"Conversation {payload.lead_email} — Q{etape} ({dimension}) "
        f"→ score {scoring['score']}/3"
    )

    # --- Court-circuit DISQUALIFIÉ si Q1 = 0 ---
    if etape == 1 and scoring["score"] == 0:
        # Profession non éligible → on termine immédiatement
        state.termine = True
        for k in ["q1_profession", "q2_motivation", "q3_maturite",
                  "q4_entrepreneuriat", "q5_geographie", "q6_financement",
                  "q7_projection"]:
            state.scores_partiels.setdefault(k, 0)
        await conversation_store.save(state)
        result = await finaliser_conversation(state)
        return result

    # --- Étape suivante ou finalisation ---
    if etape < 7:
        state.etape_courante = etape + 1
        next_q = question_for_step(state.etape_courante, state.prenom)
        state.historique.append({"role": "assistant", "content": next_q})
        await conversation_store.save(state)
        return {
            "status": "in_progress",
            "etape": state.etape_courante,
            "next_question": next_q,
            "message_to_lead": next_q,
        }
    else:
        # On vient de scorer Q7 → finalisation
        state.termine = True
        await conversation_store.save(state)
        return await finaliser_conversation(state)
