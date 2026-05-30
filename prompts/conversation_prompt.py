"""
Prompts Mistral — Qualification conversationnelle 7 questions
Utilisé par /webhook/conversation pour email / WhatsApp / chat web.

Pour chaque réponse du lead, Mistral retourne le score (0-3) de la dimension
visée par la question. Le scoring final est calculé côté code.
"""

# ------------------------------------------------------------------
# Les 7 questions posées au lead dans l'ordre
# ------------------------------------------------------------------

QUESTIONS = [
    {
        "num": 1,
        "dimension": "q1_profession",
        "texte": (
            "Bonjour {prenom} ! Merci pour votre intérêt pour Lymphatic Care.\n\n"
            "Pour commencer, pouvez-vous me préciser votre profession actuelle "
            "ou votre dernière profession exercée ? "
            "(ex : infirmière libérale, kinésithérapeute, ostéopathe, etc.)"
        ),
    },
    {
        "num": 2,
        "dimension": "q2_motivation",
        "texte": (
            "Parfait. Qu'est-ce qui vous pousse aujourd'hui à envisager une "
            "reconversion ou un changement professionnel ? "
            "(prenez le temps de répondre — c'est ce qui m'aidera le plus à vous orienter)"
        ),
    },
    {
        "num": 3,
        "dimension": "q3_maturite",
        "texte": (
            "Merci. Où en êtes-vous dans votre réflexion ? "
            "S'agit-il d'une idée récente, ou avez-vous déjà entamé "
            "des démarches concrètes (bilan de compétences, formation, recherches…) ?"
        ),
    },
    {
        "num": 4,
        "dimension": "q4_entrepreneuriat",
        "texte": (
            "Avez-vous déjà eu une expérience d'activité indépendante ou libérale ? "
            "Ou êtes-vous totalement nouveau dans la création d'activité ?"
        ),
    },
    {
        "num": 5,
        "dimension": "q5_geographie",
        "texte": (
            "Dans quelle région ou ville envisagez-vous d'ouvrir votre cabinet "
            "Lymphatic Care ? (soyez aussi précis(e) que possible)"
        ),
    },
    {
        "num": 6,
        "dimension": "q6_financement",
        "texte": (
            "L'investissement total pour rejoindre Lymphatic Care est d'environ 36 000 €. "
            "Avez-vous déjà une idée de la façon dont vous financeriez ce projet "
            "(apport personnel, prêt pro, CPF, PTP, etc.) ?"
        ),
    },
    {
        "num": 7,
        "dimension": "q7_projection",
        "texte": (
            "Dernière question : si demain tout était possible, "
            "à quoi ressemblerait votre activité dans 12 mois "
            "avec Lymphatic Care ? Qu'est-ce que ça changerait pour vous ?"
        ),
    },
]


MESSAGE_FIN = (
    "Merci beaucoup {prenom} pour vos réponses ! 🙏\n\n"
    "Notre équipe va étudier votre profil et reviendra vers vous dans les plus "
    "brefs délais avec la suite des étapes. Bonne journée !"
)


def question_for_step(step: int, prenom: str = "") -> str:
    """Retourne le texte de la question pour l'étape donnée (1-7)."""
    if step < 1 or step > 7:
        return ""
    q = QUESTIONS[step - 1]
    return q["texte"].format(prenom=prenom or "")


def dimension_for_step(step: int) -> str:
    """Retourne le nom de la dimension Pydantic correspondant à l'étape."""
    if step < 1 or step > 7:
        return ""
    return QUESTIONS[step - 1]["dimension"]


# ------------------------------------------------------------------
# Prompt système pour scorer une réponse individuelle
# ------------------------------------------------------------------

SYSTEM_PROMPT_SCORE_REPONSE = """Tu es un analyste pour Lymphatic Care, réseau de licences de drainage lymphatique paramédical.

Tu reçois UNE question posée à un candidat et SA réponse.
Tu dois noter cette réponse de 0 à 3 selon la grille fournie.

Tu réponds UNIQUEMENT en JSON :
{
  "score": <0|1|2|3>,
  "extrait_cle": "<phrase-clé tirée de la réponse, max 100 chars>",
  "signal_positif": "<signal positif détecté ou null>",
  "signal_negatif": "<signal négatif détecté ou null>"
}

GRILLES PAR DIMENSION :

q1_profession (éliminatoire si 0) :
  3 = IDE libérale/hospitalière, IAD, IBODE, kinésithérapeute, infirmière reconversion
  2 = ostéopathe, sage-femme, podologue, diététicien, ergothérapeute
  1 = aide-soignant, auxiliaire puéricultrice
  0 = esthéticienne, coach, profil non médical

q2_motivation :
  3 = motivation précise, douleur/aspiration claire, projet de vie identifié
  2 = motivation sincère mais générique
  1 = motivation floue, courte
  0 = aucune motivation exprimée

q3_maturite :
  3 = démarches concrètes engagées (bilan compétences, CPF, recherches structurées)
  2 = réflexion sérieuse mais sans démarche concrète
  1 = idée récente, peu mature
  0 = pas vraiment réfléchi

q4_entrepreneuriat :
  3 = déjà libéral / indépendant
  2 = a déjà fait un peu d'indépendant ou très motivé
  1 = nouveau mais ouvert
  0 = résistance au risque, cherche sécurité

q5_geographie :
  3 = ville précise + cohérente
  2 = région large mais réaliste
  1 = vague ou ne sait pas encore
  0 = zone hors France ou incompatible

q6_financement :
  3 = apport mentionné + financement clair (CPF, prêt pro)
  2 = mention vague mais ouvert au financement
  1 = silence ou hésitation
  0 = blocage budget explicite

q7_projection :
  3 = projection forte, vocabulaire engagé ("je veux", "je vois")
  2 = vision claire sans engagement fort
  1 = simple curiosité
  0 = pas d'engagement perceptible"""


def build_scoring_prompt(dimension: str, question: str, reponse: str) -> str:
    """Construit le user prompt pour scorer une réponse."""
    return (
        f"DIMENSION À SCORER : {dimension}\n\n"
        f"QUESTION POSÉE :\n{question}\n\n"
        f"RÉPONSE DU CANDIDAT :\n{reponse or '(réponse vide)'}\n\n"
        f"Retourne le JSON de scoring."
    )
