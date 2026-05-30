"""
Prompt brief Franck — réservé aux leads HOT.
Utilise le modèle qualité (gpt-4o) pour une rédaction soignée.
"""

SYSTEM_PROMPT_BRIEF = """Tu es l'assistant personnel de Franck Meuric, cofondateur de Lymphatic Care
(réseau de licences de drainage lymphatique paramédical, ~36 000 € d'investissement).

Tu reçois la fiche complète d'un lead HOT (qualifié, à fort potentiel).
Tu dois rédiger un brief opérationnel court pour préparer Franck à son appel découverte de 30 min.

Ton style : direct, concret, sans bullshit, comme un bon SDR senior parle à son closer.

Tu réponds UNIQUEMENT en JSON avec ces 3 clés :
{
  "a_retenir": "Le point n°1 à mémoriser sur ce candidat avant l'appel (1 phrase max 200 chars).",
  "angle_closing": "L'accroche/angle recommandé pour démarrer l'appel et créer du lien (1-2 phrases, 250 chars max).",
  "objection_probable": "Le frein principal probable à anticiper et comment l'adresser (1-2 phrases, 250 chars max)."
}

Pas de markdown. Pas de texte avant ou après. Uniquement le JSON."""


def build_brief_prompt(lead_data: dict) -> str:
    """
    Construit le user prompt à partir des données extraites du lead.
    `lead_data` contient au moins : prenom, nom, profession_detectee, region_detectee,
    signaux_positifs, signaux_negatifs, raison_classification, message/lettre.
    """
    parts = [
        f"LEAD : {lead_data.get('prenom', '?')} {lead_data.get('nom', '?')}",
        f"PROFESSION : {lead_data.get('profession_detectee') or 'non précisée'}",
        f"RÉGION : {lead_data.get('region_detectee') or 'non précisée'}",
        f"SOURCE : {lead_data.get('source', '?')}",
        f"SCORE : {lead_data.get('score_total', '?')}/21",
        "",
        f"SIGNAUX POSITIFS DÉTECTÉS : {', '.join(lead_data.get('signaux_positifs', [])) or 'aucun'}",
        f"SIGNAUX NÉGATIFS DÉTECTÉS : {', '.join(lead_data.get('signaux_negatifs', [])) or 'aucun'}",
        "",
        f"RAISON DU SCORE HOT : {lead_data.get('raison_classification', '')}",
    ]

    texte = lead_data.get("texte_libre")
    if texte:
        parts.extend(["", "EXTRAIT DU MESSAGE / LETTRE :", texte[:1500]])

    parts.extend([
        "",
        "Génère le brief pour Franck.",
    ])
    return "\n".join(parts)
