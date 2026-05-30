"""
Moteur de scoring — Lymphatic Care Agent
Logique pure de classification HOT / WARM / COLD / DISQUALIFIÉ.
Testable indépendamment des autres modules.
"""

from models.lead import Scores, Classification, Action, Confiance, ScoringResult
from loguru import logger


class ScoringEngine:
    """
    Calcule la classification finale d'un lead
    à partir de ses scores par dimension.
    """

    # Seuils de classification
    SEUIL_HOT = 15
    SEUIL_WARM = 8

    # Professions eligibles et leurs scores
    # PRINCIPE : on ne disqualifie JAMAIS un soignant. Tout profil medical/paramedical
    # est au minimum WARM (score >= 2). Seuls les profils explicitement NON-soignants
    # (esthetique, coach, commercial, IT, etc.) recoivent un score 0 -> DISQUALIFIE.
    PROFESSIONS_SCORE_3 = [
        "infirmière libérale", "ide libérale", "infirmière hospitalière",
        "ide hospitalière", "iad", "ibode", "kinésithérapeute",
        "infirmière en reconversion", "ancienne infirmière",
        "infirmiere liberale", "infirmiere hospitaliere", "kinesitherapeute",
    ]
    PROFESSIONS_SCORE_2 = [
        "ostéopathe", "sage-femme", "podologue",
        "diététicien", "ergothérapeute", "orthophoniste",
        # Aides-soignants : ce sont des soignants, on les garde en lice (WARM).
        "aide-soignant", "aide-soignante", "aide soignant", "aide soignante",
        "auxiliaire puéricultrice", "auxiliaire de puériculture",
        "asd", "asc",
        # Variantes sans accents pour matching LLM
        "osteopathe", "dieteticien", "ergotherapeute",
    ]
    # NB : plus de PROFESSIONS_SCORE_1 — soit soignant (>=2), soit non-soignant (0).
    # Liste explicite des professions DISQUALIFIANTES (le reste = on garde le doute).
    PROFESSIONS_DISQUALIFIANTES = [
        "esthéticienne", "estheticienne", "esthétique", "esthetique",
        "coach", "commercial", "vendeur", "vendeuse",
        "developpeur", "développeur", "informatique",
        "comptable", "secrétaire", "secretaire",
        "agent immobilier", "courtier",
    ]

    def classifier(self, scores: Scores, confiance: Confiance) -> tuple[Classification, Action]:
        """
        Retourne la classification et l'action correspondante.
        REGLE METIER (Franck) : on ne disqualifie JAMAIS un soignant.
        DISQUALIFIE seulement si le LLM a explicitement detecte un profil non-medical
        (signale via signaux_negatifs ou profession_detectee dans des cas connus).
        Par defaut (profession inconnue), on classe en COLD pour nurturing.
        """
        total = scores.total
        logger.info(f"Score total : {total}/21 (q1_profession={scores.q1_profession})")

        # Règle confiance faible : forcer WARM même si score HOT
        if confiance == Confiance.FAIBLE and total >= self.SEUIL_HOT:
            logger.info("Score HOT mais confiance FAIBLE → forçage WARM")
            return Classification.WARM, Action.BREVO_NURTURING

        if total >= self.SEUIL_HOT:
            return Classification.HOT, Action.CALENDLY
        elif total >= self.SEUIL_WARM:
            return Classification.WARM, Action.BREVO_NURTURING
        else:
            return Classification.COLD, Action.BREVO_COLD

    def scorer_profession(self, profession: str) -> int:
        """
        Score Q1 a partir du texte de profession.
        Regle Franck : on ne disqualifie JAMAIS un soignant.
        - 3 = profil cible prioritaire (IDE, kine, IAD, IBODE)
        - 2 = autre soignant / paramedical (aide-soignant inclus !)
        - 1 = profession inconnue/non-precisee (= a creuser, pas disqualifie)
        - 0 = explicitement non-soignant (esthetique, coach, IT, etc.)
        """
        if not profession:
            # Profession inconnue : on NE disqualifie PAS, on classe en a creuser (1).
            return 1
        profession_lower = profession.lower()

        # 1) Verifier d'abord les profils DISQUALIFIANTS EXPLICITES
        for p in self.PROFESSIONS_DISQUALIFIANTES:
            if p in profession_lower:
                return 0

        # 2) Profils cibles prioritaires (score 3)
        for p in self.PROFESSIONS_SCORE_3:
            if p in profession_lower:
                return 3

        # 3) Autres soignants (score 2)
        for p in self.PROFESSIONS_SCORE_2:
            if p in profession_lower:
                return 2

        # 4) Detection generique infirmier/kine (cas frequents)
        if any(mot in profession_lower for mot in ["infirm", "ide ", "kine", "kiné"]):
            return 3

        # 5) Detection generique soignant
        if any(mot in profession_lower for mot in [
            "soignant", "soignante", "medical", "médical", "paramedic", "paramédic",
            "sante", "santé", "hopital", "hôpital", "clinique", "ehpad",
        ]):
            return 2

        # 6) Inconnu : on laisse le benefice du doute (score 1, pas 0)
        return 1

    def calculer_confiance(
        self,
        a_lettre: bool,
        nb_questions_repondues: int
    ) -> Confiance:
        """Évalue la confiance dans l'analyse."""
        if a_lettre and nb_questions_repondues >= 3:
            return Confiance.HAUTE
        elif a_lettre or nb_questions_repondues >= 2:
            return Confiance.MOYENNE
        else:
            return Confiance.FAIBLE

    def detecter_signaux_positifs(self, texte: str) -> list[str]:
        """Détecte les signaux positifs dans le texte libre."""
        signaux = []
        texte_lower = texte.lower()

        mots_cles = {
            "libéral": "Déjà en exercice libéral",
            "cabinet": "Mentionne l'ouverture d'un cabinet",
            "cpf": "CPF ou bilan de compétences mentionné",
            "bilan de compétences": "CPF ou bilan de compétences mentionné",
            "ptp": "PTP (Projet de Transition Pro) mentionné",
            "apport": "Apport financier disponible",
            "épargne": "Épargne disponible mentionnée",
            "burn": "Épuisement professionnel exprimé",
            "reconversion": "Reconversion déjà engagée",
            "lymphatic care": "Connaissance spécifique de Lymphatic Care",
            "franck": "Connaissance du fondateur Franck",
            "émilie": "Connaissance de la fondatrice Émilie",
        }

        for mot, signal in mots_cles.items():
            if mot in texte_lower and signal not in signaux:
                signaux.append(signal)

        return signaux

    def detecter_signaux_negatifs(self, texte: str) -> list[str]:
        """Détecte les signaux négatifs dans le texte libre."""
        signaux = []
        texte_lower = texte.lower()

        mots_cles = {
            "salariat": "Préférence pour le salariat exprimée",
            "cdi": "Recherche d'un CDI",
            "sécurité": "Recherche de sécurité d'emploi",
            "madame, monsieur": "Lettre non personnalisée",
            "trop cher": "Blocage budget fort",
            "pas les moyens": "Blocage budget fort",
        }

        for mot, signal in mots_cles.items():
            if mot in texte_lower and signal not in signaux:
                signaux.append(signal)

        return signaux


scoring_engine = ScoringEngine()
