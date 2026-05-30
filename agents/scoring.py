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

    # Professions éligibles et leurs scores
    PROFESSIONS_SCORE_3 = [
        "infirmière libérale", "ide libérale", "infirmière hospitalière",
        "ide hospitalière", "iad", "ibode", "kinésithérapeute",
        "infirmière en reconversion", "ancienne infirmière"
    ]
    PROFESSIONS_SCORE_2 = [
        "ostéopathe", "sage-femme", "podologue",
        "diététicien", "ergothérapeute", "orthophoniste"
    ]
    PROFESSIONS_SCORE_1 = [
        "aide-soignant", "auxiliaire puéricultrice",
        "aide soignante", "asc"
    ]

    def classifier(self, scores: Scores, confiance: Confiance) -> tuple[Classification, Action]:
        """
        Retourne la classification et l'action correspondante.
        """
        # Règle éliminatoire : profession non éligible
        if scores.q1_profession == 0:
            logger.info("Lead DISQUALIFIÉ — profession non éligible")
            return Classification.DISQUALIFIED, Action.EMAIL_DECLIN

        total = scores.total
        logger.info(f"Score total : {total}/21")

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
        """Score Q1 à partir du texte de profession."""
        if not profession:
            return 0
        profession_lower = profession.lower()

        for p in self.PROFESSIONS_SCORE_3:
            if p in profession_lower:
                return 3
        for p in self.PROFESSIONS_SCORE_2:
            if p in profession_lower:
                return 2
        for p in self.PROFESSIONS_SCORE_1:
            if p in profession_lower:
                return 1

        # Détection générique infirmier
        if any(mot in profession_lower for mot in ["infirm", "ide ", "kiné"]):
            return 3

        return 0

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
