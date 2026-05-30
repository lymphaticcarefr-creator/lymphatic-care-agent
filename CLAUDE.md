# CLAUDE CODE — AGENT QUALIFICATION LYMPHATIC CARE

## Contexte du projet

Tu construis l'agent de qualification automatique des leads pour
**Lymphatic Care**, un réseau de cabinets de drainage lymphatique
paramédical français fondé par Franck Meuric et Émilie.

L'agent doit qualifier automatiquement des candidats qui souhaitent
rejoindre le réseau via un modèle de licence de marque (~36 000€).

---

## Stack technique

- **Python 3.11+** avec FastAPI (serveur webhook)
- **Ollama / Mistral 7B** (VPS local : `http://localhost:11434`)
- **Brevo API** (emails automatiques — séquences nurturing)
- **Notion API** (fiches leads — base de données CRM)
- **Calendly** (liens de réservation appel stratégique)
- **Make / N8N** (orchestrateur externe qui appelle les webhooks)
- **Redis** (gestion état des conversations multi-tours)

---

## Architecture de l'agent

```
Webhook entrant (POST /webhook/lead)
         ↓
   Détection source
   (INDEED | TALLY | INSTAGRAM | LINKEDIN)
         ↓
   Mode SILENCIEUX (Indeed)     Mode CONVERSATIONNEL (autres)
         ↓                               ↓
   Analyse lettre GPT/Mistral    7 questions séquentielles
         ↓                       (état géré via Redis)
         ↓                               ↓
         └──────────── Scoring ──────────┘
                           ↓
                    HOT / WARM / COLD / DISQUALIFIÉ
                           ↓
              ┌────────────┼────────────┐
              ↓            ↓            ↓
           Calendly     Brevo        Brevo
           + Notion    Nurturing      Cold
           + Mail       N8N seq.    30j seq.
           Franck
```

---

## Fichiers clés à construire

### 1. `main.py`
Serveur FastAPI principal. Expose les routes webhook.
Gère le cycle de vie de l'application.

### 2. `config.py`
Toutes les variables d'environnement (clés API, URLs, etc.)
Utilise `python-dotenv`.

### 3. `models/lead.py`
Modèles Pydantic pour valider les données entrantes.
- `LeadIndeed` (email parsé)
- `LeadTally` (formulaire)
- `LeadConversation` (état de conversation)
- `ScoringResult` (résultat de qualification)

### 4. `agents/qualification.py`
Cœur de l'agent. Contient :
- `QualificationAgent` : gère la conversation 7 questions
- `SilentAnalyzer` : analyse silencieuse lettre Indeed
- `ScoringEngine` : calcule HOT/WARM/COLD

### 5. `agents/scoring.py`
Logique de scoring pure :
- Scores Q1→Q7 (0 à 3 pts chacun)
- Bonus/malus
- Classification finale
- Score de confiance

### 6. `integrations/ollama.py`
Client HTTP vers l'API Ollama locale.
- `complete()` : génère une réponse
- `chat()` : mode conversation multi-tours

### 7. `integrations/brevo.py`
Client Brevo API v3 :
- `create_contact()` : crée le contact avec attributs
- `add_to_list()` : ajoute à la liste HOT/WARM/COLD
- `trigger_automation()` : déclenche la séquence email

### 8. `integrations/notion.py`
Client Notion API :
- `create_lead_card()` : crée la fiche dans la bonne base
- `update_status()` : met à jour le statut

### 9. `integrations/calendly.py`
Génère et retourne le lien Calendly approprié.

### 10. `routes/webhook_indeed.py`
Route POST `/webhook/indeed`
Reçoit les données parsées depuis Make (email Indeed).

### 11. `routes/webhook_tally.py`
Route POST `/webhook/tally`
Reçoit les soumissions Tally (landing page, Instagram, LinkedIn).

### 12. `routes/webhook_conversation.py`
Route POST `/webhook/conversation`
Reçoit les réponses email/WhatsApp pour la qualification conversationnelle.

---

## Règles de développement

1. **Toujours utiliser des types Pydantic** pour les données entrantes
2. **Toujours logger** les actions avec le module `logging`
3. **Toujours gérer les erreurs** avec try/except et retourner des réponses HTTP appropriées
4. **Jamais hardcoder** les clés API — toujours via `.env`
5. **Commenter en français** — le client est francophone
6. **Tests unitaires** pour le scoring engine (critique)

---

## Variables d'environnement requises (.env)

```
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral

BREVO_API_KEY=...
BREVO_LIST_HOT=...
BREVO_LIST_WARM=...
BREVO_LIST_COLD=...
BREVO_AUTOMATION_NURTURING=...
BREVO_AUTOMATION_COLD=...

NOTION_API_KEY=...
NOTION_DB_HOT=...
NOTION_DB_WARM=...
NOTION_DB_COLD=...

CALENDLY_LINK=https://calendly.com/lymphaticcare/appel-strategique

MAIL_FRANCK=franck@lymphaticcare.fr
WEBHOOK_SECRET=...

REDIS_URL=redis://localhost:6379
```

---

## Scoring Lymphatic Care

### Questions et points

| Question | Dimension | Max |
|----------|-----------|-----|
| Q1 | Éligibilité profession (éliminatoire si 0) | 3 |
| Q2 | Motivation profonde | 3 |
| Q3 | Maturité du projet | 3 |
| Q4 | Expérience entrepreneuriale | 3 |
| Q5 | Géographie | 3 |
| Q6 | Financement | 3 |
| Q7 | Projection émotionnelle | 3 |
| Bonus | Apport financier / CPF / personnalisation | +8 max |

### Classification

- **HOT** : 15-21 pts → Calendly + Notion + Mail Franck
- **WARM** : 8-14 pts → Brevo nurturing (J+0/J+2/J+5/J+7)
- **COLD** : 0-7 pts → Brevo cold séquence 30j
- **DISQUALIFIÉ** : Q1 = 0 → Email déclin immédiat

---

## Ordre de développement recommandé

1. `config.py` + `.env.example`
2. `models/lead.py`
3. `agents/scoring.py` + tests
4. `integrations/ollama.py`
5. `agents/qualification.py`
6. `integrations/brevo.py`
7. `integrations/notion.py`
8. `routes/webhook_indeed.py`
9. `routes/webhook_tally.py`
10. `routes/webhook_conversation.py`
11. `main.py` (assemble tout)
12. `tests/` complets

---

## Commande de démarrage

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

L'agent sera accessible sur `http://[IP_VPS]:8000`
