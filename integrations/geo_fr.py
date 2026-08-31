"""
geo_fr — Résolution du département français à partir d'un texte libre.

Sert à renseigner la propriété Notion "Zone" pour les leads qui ne tombent pas
dans l'une des zones de campagne historiques (Alpes-Maritimes, Bordeaux/Arcachon,
Toulouse, Paris/IDF, Narbonne). Objectif : ne plus classer en "Autre" une
candidate de Montpellier, Marseille ou Aix-en-Provence.

Ordre de détection : code postal → nom de département → nom de commune.
Retourne une chaîne du type "34 Hérault", ou None si rien n'est reconnaissable.

La comparaison se fait sur des MOTS ENTIERS : sans cela "Angers" contiendrait
"Gers" et "Saint-Étienne" contiendrait "Ain".
"""

from __future__ import annotations

import re
import unicodedata

DEPARTEMENTS = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse",
    "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure",
    "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine",
    "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura",
    "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne",
    "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne",
    "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse",
    "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme",
    "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales",
    "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône",
    "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines",
    "79": "Deux-Sèvres", "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne",
    "83": "Var", "84": "Vaucluse", "85": "Vendée", "86": "Vienne",
    "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne", "95": "Val-d'Oise", "971": "Guadeloupe",
    "972": "Martinique", "973": "Guyane", "974": "La Réunion", "976": "Mayotte",
}

# Communes les plus peuplées, préfectures et villes cibles du réseau.
VILLES = {
    "paris": "75", "marseille": "13", "lyon": "69", "toulouse": "31",
    "nice": "06", "nantes": "44", "montpellier": "34", "strasbourg": "67",
    "bordeaux": "33", "lille": "59", "rennes": "35", "reims": "51",
    "saint etienne": "42", "toulon": "83", "le havre": "76", "grenoble": "38",
    "dijon": "21", "angers": "49", "nimes": "30", "villeurbanne": "69",
    "clermont ferrand": "63", "aix en provence": "13", "le mans": "72",
    "brest": "29", "tours": "37", "amiens": "80", "limoges": "87",
    "annecy": "74", "perpignan": "66", "boulogne billancourt": "92",
    "metz": "57", "besancon": "25", "orleans": "45", "argenteuil": "95",
    "rouen": "76", "mulhouse": "68", "montreuil": "93", "caen": "14",
    "nancy": "54", "tourcoing": "59", "roubaix": "59", "nanterre": "92",
    "avignon": "84", "creteil": "94", "poitiers": "86", "dunkerque": "59",
    "aubervilliers": "93", "versailles": "78", "colombes": "92",
    "asnieres sur seine": "92", "courbevoie": "92", "cherbourg": "50",
    "rueil malmaison": "92", "levallois perret": "92", "levallois": "92",
    "pau": "64", "champigny sur marne": "94", "antibes": "06",
    "saint maur des fosses": "94", "cannes": "06", "calais": "62",
    "beziers": "34", "colmar": "68", "bourges": "18", "drancy": "93",
    "merignac": "33", "saint nazaire": "44", "valence": "26", "ajaccio": "2A",
    "issy les moulineaux": "92", "villeneuve d ascq": "59", "noisy le grand": "93",
    "quimper": "29", "antony": "92", "troyes": "10", "neuilly sur seine": "92",
    "clichy": "92", "ivry sur seine": "94", "chambery": "73", "lorient": "56",
    "pessac": "33", "montauban": "82", "niort": "79", "sarcelles": "95",
    "villejuif": "94", "hyeres": "83", "saint quentin": "02", "beauvais": "60",
    "cholet": "49", "narbonne": "11", "belfort": "90", "vannes": "56",
    "fontenay sous bois": "94", "bondy": "93", "arles": "13", "laval": "53",
    "bayonne": "64", "evreux": "27", "la rochelle": "17", "carcassonne": "11",
    "cagnes sur mer": "06", "saint malo": "35", "bastia": "2B", "albi": "81",
    "martigues": "13", "brive la gaillarde": "19", "brive": "19", "blois": "41",
    "chartres": "28", "chalons en champagne": "51", "meaux": "77",
    "salon de provence": "13", "grasse": "06", "gap": "05", "agen": "47",
    "compiegne": "60", "annemasse": "74", "thionville": "57", "montlucon": "03",
    "auxerre": "89", "sete": "34", "tarbes": "65", "castres": "81",
    "alencon": "61", "roanne": "42", "bourg en bresse": "01", "vichy": "03",
    "angouleme": "16", "perigueux": "24", "rodez": "12", "mende": "48",
    "aurillac": "15", "moulins": "03", "nevers": "58", "macon": "71",
    "chaumont": "52", "bar le duc": "55", "epinal": "88", "verdun": "55",
    "saint brieuc": "22", "gueret": "23", "tulle": "19", "cahors": "46",
    "auch": "32", "foix": "09", "privas": "07", "digne": "04",
    "draguignan": "83", "frejus": "83", "menton": "06", "monaco": "06",
    "arcachon": "33", "libourne": "33", "talence": "33", "blagnac": "31",
    "colomiers": "31", "muret": "31", "melun": "77", "evry": "91",
    "cergy": "95", "pontoise": "95", "rambouillet": "78",
    "saint germain en laye": "78", "boulogne sur mer": "62", "arras": "62",
    "lens": "62", "valenciennes": "59", "douai": "59", "cambrai": "59",
    "maubeuge": "59", "soissons": "02", "laon": "02", "senlis": "60",
    "creil": "60", "sens": "89", "vesoul": "70", "lons le saunier": "39",
    "dole": "39", "montbeliard": "25", "pontarlier": "25", "thonon": "74",
    "cluses": "74", "albertville": "73", "chamonix": "74", "bourgoin": "38",
    "voiron": "38", "romans": "26", "montelimar": "26", "orange": "84",
    "carpentras": "84", "cavaillon": "84", "aubagne": "13", "istres": "13",
    "vitrolles": "13", "marignane": "13", "saint raphael": "83",
    "six fours": "83", "biarritz": "64", "anglet": "64", "dax": "40",
    "mont de marsan": "40", "royan": "17", "saintes": "17", "rochefort": "17",
    "cognac": "16", "bergerac": "24", "sarlat": "24", "villeneuve sur lot": "47",
    "marmande": "47", "figeac": "46", "millau": "12", "lourdes": "65",
    "pamiers": "09", "castelnaudary": "11", "limoux": "11", "lezignan": "11",
    "gruissan": "11", "leucate": "11", "argeles sur mer": "66", "ceret": "66",
    "prades": "66", "banyuls": "66", "lunel": "34", "lattes": "34",
    "palavas": "34", "agde": "34", "frontignan": "34", "mauguio": "34",
    "castelnau le lez": "34", "ales": "30", "bagnols sur ceze": "30",
    "uzes": "30", "beaucaire": "30", "saint gilles": "30",
    "la grande motte": "34", "balaruc": "34", "saint denis": "93",
    "saint pierre": "974", "fort de france": "972", "pointe a pitre": "971",
    "cayenne": "973", "mamoudzou": "976",
}

_POSTAL = re.compile(r"\b(\d{5})\b")


def _normaliser(texte: str) -> str:
    """minuscules, sans accent, séparateurs réduits à une espace simple."""
    t = unicodedata.normalize("NFD", texte or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return f" {t.strip()} "


def _contient_expression(texte_norm: str, expression: str) -> bool:
    """Cherche une expression en mots entiers (les espaces encadrants suffisent)."""
    return f" {expression.strip()} " in texte_norm


def _code_depuis_code_postal(texte: str) -> str | None:
    m = _POSTAL.search(texte or "")
    if not m:
        return None
    cp = m.group(1)
    if cp.startswith("97"):
        return cp[:3] if cp[:3] in DEPARTEMENTS else None
    if cp.startswith("20"):  # Corse : 200xx/201xx = 2A, 202xx à 206xx = 2B
        return "2A" if cp[2] in "01" else "2B"
    return cp[:2] if cp[:2] in DEPARTEMENTS else None


def _code_depuis_nom_departement(texte_norm: str) -> str | None:
    # Le plus long d'abord : "haute garonne" doit gagner sur "garonne".
    for code, nom in sorted(DEPARTEMENTS.items(), key=lambda kv: -len(kv[1])):
        if _contient_expression(texte_norm, _normaliser(nom)):
            return code
    return None


def _code_depuis_ville(texte_norm: str) -> str | None:
    for ville, code in sorted(VILLES.items(), key=lambda kv: -len(kv[0])):
        if _contient_expression(texte_norm, ville):
            return code
    return None


def departement_from_text(texte: str) -> str | None:
    """
    Renvoie "34 Hérault" (code + nom) si un département est identifiable dans le
    texte libre saisi par le candidat, sinon None.
    """
    if not texte or not texte.strip():
        return None

    code = _code_depuis_code_postal(texte)
    if not code:
        texte_norm = _normaliser(texte)
        code = _code_depuis_nom_departement(texte_norm) or _code_depuis_ville(texte_norm)

    if code and code in DEPARTEMENTS:
        return f"{code} {DEPARTEMENTS[code]}"
    return None
