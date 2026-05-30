"""
Tests unitaires — Moteur de scoring Lymphatic Care
Lance avec : pytest tests/ -v
"""

import pytest
from agents.scoring import ScoringEngine
from models.lead import Scores, Classification, Action, Confiance

engine = ScoringEngine()


class TestClassification:

    def test_lead_hot(self):
        scores = Scores(
            q1_profession=3, q2_motivation=3, q3_maturite=3,
            q4_entrepreneuriat=3, q5_geographie=2, q6_financement=2,
            q7_projection=3
        )
        classification, action = engine.classifier(scores, Confiance.HAUTE)
        assert classification == Classification.HOT
        assert action == Action.CALENDLY

    def test_lead_warm(self):
        scores = Scores(
            q1_profession=3, q2_motivation=2, q3_maturite=1,
            q4_entrepreneuriat=1, q5_geographie=1, q6_financement=1,
            q7_projection=2
        )
        classification, action = engine.classifier(scores, Confiance.HAUTE)
        assert classification == Classification.WARM
        assert action == Action.BREVO_NURTURING

    def test_lead_cold(self):
        scores = Scores(
            q1_profession=2, q2_motivation=1, q3_maturite=0,
            q4_entrepreneuriat=0, q5_geographie=1, q6_financement=0,
            q7_projection=1
        )
        classification, action = engine.classifier(scores, Confiance.HAUTE)
        assert classification == Classification.COLD
        assert action == Action.BREVO_COLD

    def test_disqualifie_profession(self):
        scores = Scores(
            q1_profession=0, q2_motivation=3, q3_maturite=3,
            q4_entrepreneuriat=3, q5_geographie=3, q6_financement=3,
            q7_projection=3
        )
        classification, action = engine.classifier(scores, Confiance.HAUTE)
        assert classification == Classification.DISQUALIFIED
        assert action == Action.EMAIL_DECLIN

    def test_confiance_faible_force_warm(self):
        """Un score HOT avec confiance FAIBLE doit être forcé en WARM."""
        scores = Scores(
            q1_profession=3, q2_motivation=3, q3_maturite=3,
            q4_entrepreneuriat=3, q5_geographie=3, q6_financement=0,
            q7_projection=3
        )
        classification, action = engine.classifier(scores, Confiance.FAIBLE)
        assert classification == Classification.WARM

    def test_score_total(self):
        scores = Scores(
            q1_profession=3, q2_motivation=2, q3_maturite=1,
            q4_entrepreneuriat=2, q5_geographie=3, q6_financement=2,
            q7_projection=3, bonus=3
        )
        assert scores.total == 19


class TestScorerProfession:

    def test_ide_liberale(self):
        assert engine.scorer_profession("Infirmière libérale") == 3

    def test_ide_hospitaliere(self):
        assert engine.scorer_profession("Infirmière hospitalière CHU") == 3

    def test_kine(self):
        assert engine.scorer_profession("Kinésithérapeute") == 3

    def test_osteopathe(self):
        assert engine.scorer_profession("Ostéopathe") == 2

    def test_aide_soignante(self):
        assert engine.scorer_profession("Aide-soignante") == 1

    def test_estheticienne(self):
        assert engine.scorer_profession("Esthéticienne") == 0

    def test_coach(self):
        assert engine.scorer_profession("Coach bien-être") == 0


class TestSignaux:

    def test_signaux_positifs(self):
        texte = "Je suis en libéral depuis 3 ans et j'ai un CPF disponible"
        signaux = engine.detecter_signaux_positifs(texte)
        assert len(signaux) > 0

    def test_signaux_negatifs(self):
        texte = "Je cherche un CDI et la sécurité avant tout"
        signaux = engine.detecter_signaux_negatifs(texte)
        assert len(signaux) > 0
