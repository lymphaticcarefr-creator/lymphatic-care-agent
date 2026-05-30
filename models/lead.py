"""
Modèles Pydantic — Lymphatic Care Agent
Validation des données entrantes et structures internes.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from enum import Enum


class Source(str, Enum):
    INDEED = "INDEED"
    LANDING_PAGE = "LANDING_PAGE"
    INSTAGRAM = "INSTAGRAM"
    LINKEDIN = "LINKEDIN"
    FACEBOOK = "FACEBOOK"
    AUTRE = "AUTRE"


class Classification(str, Enum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"
    DISQUALIFIED = "DISQUALIFIÉ"


class Action(str, Enum):
    CALENDLY = "CALENDLY"
    BREVO_NURTURING = "BREVO_NURTURING"
    BREVO_COLD = "BREVO_COLD"
    EMAIL_DECLIN = "EMAIL_DECLIN"


class Confiance(str, Enum):
    HAUTE = "HAUTE"
    MOYENNE = "MOYENNE"
    FAIBLE = "FAIBLE"


# --- Données entrantes ---

class LeadIndeed(BaseModel):
    """Lead provenant d'Indeed via parsing email Make."""
    prenom: str
    nom: str
    email: EmailStr
    telephone: Optional[str] = None
    lettre_motivation: str
    reponse_q1_profession: Optional[str] = None
    reponse_q2_situation: Optional[str] = None
    reponse_q3_region: Optional[str] = None
    reponse_q4_motivation: Optional[str] = None
    source: Source = Source.INDEED


class LeadTally(BaseModel):
    """Lead provenant d'un formulaire Tally (landing page, Instagram, LinkedIn)."""
    prenom: str
    nom: str
    email: EmailStr
    telephone: Optional[str] = None
    profession: Optional[str] = None
    situation: Optional[str] = None
    region: Optional[str] = None
    horizon: Optional[str] = None
    message: Optional[str] = None
    source: Source = Source.LANDING_PAGE


class ConversationMessage(BaseModel):
    """Message dans une conversation de qualification."""
    lead_email: EmailStr
    message: str
    canal: str = "email"  # email | whatsapp | webui


# --- Résultats internes ---

class Scores(BaseModel):
    """Scores par dimension de qualification."""
    q1_profession: int = Field(0, ge=0, le=3)
    q2_motivation: int = Field(0, ge=0, le=3)
    q3_maturite: int = Field(0, ge=0, le=3)
    q4_entrepreneuriat: int = Field(0, ge=0, le=3)
    q5_geographie: int = Field(0, ge=0, le=3)
    q6_financement: int = Field(0, ge=0, le=3)
    q7_projection: int = Field(0, ge=0, le=3)
    bonus: int = Field(0, ge=0)
    malus: int = Field(0, le=0)

    @property
    def total(self) -> int:
        return (
            self.q1_profession + self.q2_motivation +
            self.q3_maturite + self.q4_entrepreneuriat +
            self.q5_geographie + self.q6_financement +
            self.q7_projection + self.bonus + self.malus
        )


class BriefFranck(BaseModel):
    """Résumé pour Franck avant l'appel (leads HOT uniquement)."""
    a_retenir: str
    angle_closing: str
    objection_probable: str


class ScoringResult(BaseModel):
    """Résultat complet de la qualification d'un lead."""
    prenom: str
    nom: str
    email: str
    telephone: Optional[str] = None
    source: Source
    scores: Scores
    classification: Classification
    confiance: Confiance
    profession_detectee: Optional[str] = None
    situation_detectee: Optional[str] = None
    region_detectee: Optional[str] = None
    signaux_positifs: List[str] = []
    signaux_negatifs: List[str] = []
    raison_classification: str
    action: Action
    brief_franck: Optional[BriefFranck] = None
    notes: Optional[str] = None


class ConversationState(BaseModel):
    """État d'une conversation de qualification en cours."""
    lead_email: str
    prenom: str
    nom: str
    telephone: Optional[str] = None
    source: Source
    etape_courante: int = 0  # 0=accueil, 1-7=questions
    historique: List[dict] = []  # messages échangés
    scores_partiels: dict = {}
    termine: bool = False
