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
    # REGLE METIER FRANCK : toute infirmiere (quelle que soit specialite) + osteopathe + kine = SCORE 3.
    PROFESSIONS_SCORE_3 = [
        # Infirmieres toutes specialites (deja matche via "infirm" en regex generique)
        "infirmière libérale", "ide libérale", "idel",
        "infirmière hospitalière", "ide hospitalière",
        "infirmière coordinatrice", "infirmière coordinateur",
        "infirmière scolaire", "infirmière puéricultrice",
        "infirmière en reconversion", "ancienne infirmière",
        "infirmière dermato", "infirmière dermatologie",
        "iad", "ibode", "iade",
        # Variantes sans accents
        "infirmiere liberale", "infirmiere hospitaliere",
        "infirmiere coordinatrice", "infirmiere scolaire",
        # Kine : toujours score 3
        "kinésithérapeute", "kinesitherapeute", "masseur-kinésithérapeute",
        "masseur-kinesitherapeute", "kiné", "kine",
        # Osteo : toujours score 3 (regle Franck)
        "ostéopathe", "osteopathe", "ostéopathie", "osteopathie",
    ]
    PROFESSIONS_SCORE_2 = [
        "sage-femme", "podologue",
        "diététicien", "ergothérapeute", "orthophoniste",
        # Aides-soignants : ce sont des soignants, on les garde en lice (WARM).
        "aide-soignant", "aide-soignante", "aide soignant", "aide soignante",
        "auxiliaire puéricultrice", "auxiliaire de puériculture",
        "asd", "asc",
        # Variantes sans accents pour matching LLM
        "dieteticien", "ergotherapeute",
    ]
    # NB : plus de PROFESSIONS_SCORE_1 — soit soignant (>=2), soit non-soignant (0).
    # Liste explicite des professions DISQUALIFIANTES (le reste = on garde le doute).
    PROFESSIONS_DISQUALIFIANTES = [
        # Esthétique / bien-être non médical
        "esthéticienne", "estheticienne", "esthétique", "esthetique",
        "praticien en massage", "praticienne en massage",
        "praticien de massage", "praticienne de massage",
        "praticien en bien-être", "praticienne en bien-être",
        "praticien massage", "praticienne massage",
        "spa praticien", "spa praticienne", "spa-praticien",
        "masseuse",  # "masseur" exclu via regex word-boundary (eviter conflit avec masseur-kinesitherapeute)
        # Autres profils hors cible
        "coach", "commercial", "vendeur", "vendeuse",
        "developpeur", "développeur", "informatique",
        "comptable", "secrétaire", "secretaire",
        "agent immobilier", "courtier",
        "arbitre",  # ex: Marcel Eyidi-Emery
    ]

    def classifier_with_profession_check(
        self,
        scores: Scores,
        confiance: Confiance,
        profession_detectee: str = "",
    ) -> tuple[Classification, Action]:
        """
        Classifier complet avec override Python sur profession explicite.
        Si la profession matche un profil non-soignant connu, force DISQUALIFIE
        meme si le LLM n'a pas mis eligibilite_profession=0.
        """
        prof = (profession_detectee or "").lower()

        # Patterns de soignant cible (regle Franck : infirm/ide/kine/osteo)
        SOIGNANT_PATTERNS = [
            "infirm", "ide ", "ide,", "ide-",
            "idel", "iadel", "iade", "ibode", "iad ",
            "kine", "kiné", "masseur-kine", "masseur-kiné",
            "kinesi", "kinési",
            "osteo", "ostéo",
        ]
        is_soignant_cible = bool(prof) and any(kw in prof for kw in SOIGNANT_PATTERNS)

        # === 1) OVERRIDE DQ : profession explicitement non-soignante ===
        if prof:
            for p in self.PROFESSIONS_DISQUALIFIANTES:
                if p in prof:
                    logger.info(
                        f"Override DQ : profession '{profession_detectee}' matche '{p}'"
                    )
                    return Classification.DISQUALIFIED, Action.EMAIL_DECLIN
            # "masseur" mot complet (mais PAS si "kine" present, c'est masseur-kine)
            import re
            if re.search(r"\bmasseur\b", prof) and "kine" not in prof and "kiné" not in prof:
                logger.info(f"Override DQ : profession '{profession_detectee}' = masseur (non kine)")
                return Classification.DISQUALIFIED, Action.EMAIL_DECLIN

        # === 2) Classification normale ===
        classification, action = self.classifier(scores, confiance)

        # === 3) OVERRIDE WARM minimum : profil cible (regle Franck) ===
        # Une infirmiere / osteo / kine ne doit JAMAIS tomber en COLD ou DQ,
        # peu importe ce que le LLM a calcule.
        if is_soignant_cible:
            if classification in (Classification.COLD, Classification.DISQUALIFIED):
                logger.info(
                    f"Override WARM : profession cible '{profession_detectee}' "
                    f"forcee de {classification.value} a WARM"
                )
                return Classification.WARM, Action.BREVO_NURTURING

        return classification, action

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

        # 1a) D'ABORD verifier les soignants prioritaires (score 3)
        # Cas important : "masseur-kinesitherapeute" doit etre attrape par "kine"
        # AVANT que "masseur" tombe dans la liste DQ.
        for p in self.PROFESSIONS_SCORE_3:
            if p in profession_lower:
                return 3
        if any(mot in profession_lower for mot in [
            "infirm", "ide ", "ide,", "ide-",
            "kine", "kiné",
            "osteo", "ostéo",
        ]):
            return 3

        # 1b) Ensuite verifier les profils DISQUALIFIANTS EXPLICITES
        import re
        for p in self.PROFESSIONS_DISQUALIFIANTES:
            if p in profession_lower:
                return 0
        # "masseur" en word-boundary (eviter conflit avec masseur-kine deja capture plus haut)
        if re.search(r"\bmasseur\b", profession_lower):
            return 0

        # 3) Autres soignants (score 2)
        for p in self.PROFESSIONS_SCORE_2:
            if p in profession_lower:
                return 2

        # 4) Detection generique soignant
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
