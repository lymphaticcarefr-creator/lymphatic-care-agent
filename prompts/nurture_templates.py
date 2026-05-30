"""
Templates emails nurturing — Lymphatic Care
- Séquence WARM : J+0, J+2, J+5, J+7 (4 emails)
- Séquence COLD : J+0, J+10, J+20, J+30 (4 emails)

Chaque template = (subject, html_body). Le prénom est interpolé via {prenom}.
"""

# Couleurs Lymphatic Care
LC_GREEN = "#2d5c47"
LC_GOLD = "#c9a961"


def _wrap(body: str, cta_url: str = "", cta_label: str = "") -> str:
    """Wrap un contenu HTML avec header/footer Lymphatic Care."""
    cta_block = ""
    if cta_url and cta_label:
        cta_block = f"""
        <p style="text-align:center; margin: 30px 0;">
          <a href="{cta_url}" style="
            background:{LC_GREEN}; color:white; padding:14px 28px;
            text-decoration:none; border-radius:6px; font-weight:bold;
            display:inline-block;
          ">{cta_label}</a>
        </p>
        """
    return f"""<!DOCTYPE html>
<html><body style="font-family: Helvetica, Arial, sans-serif; color:#333; max-width:600px; margin:0 auto; padding: 20px;">
{body}
{cta_block}
<hr style="border:none; border-top:1px solid #eee; margin:30px 0;">
<p style="font-size:12px; color:#888; text-align:center;">
  Lymphatic Care — Réseau de cabinets de drainage lymphatique<br>
  Vous recevez ce mail suite à votre intérêt pour rejoindre notre réseau.<br>
  <a href="{{{{unsubscribe}}}}" style="color:#888;">Se désabonner</a>
</p>
</body></html>"""


# ============================================================
# SÉQUENCE WARM (4 emails)
# ============================================================

WARM_J0 = {
    "subject": "Votre candidature Lymphatic Care — notre équipe l'examine",
    "html": _wrap("""
        <p>Bonjour {prenom},</p>
        <p>Merci pour l'intérêt que vous portez à Lymphatic Care.</p>
        <p>Nous avons bien reçu votre candidature et notre équipe l'examine avec attention. Tous les profils ne correspondent pas à ce que nous recherchons — et c'est précisément pourquoi nous prenons le temps d'étudier chaque dossier individuellement.</p>
        <hr style="border:none; border-top:1px solid #ddd; margin:24px 0;">
        <p><strong>Ce que Lymphatic Care n'est pas :</strong></p>
        <p>Nous ne vendons pas une formation. Nous ne vous formons pas pour vous laisser seul face à votre activité. Ce n'est pas notre modèle, ce ne sont pas nos valeurs.</p>
        <hr style="border:none; border-top:1px solid #ddd; margin:24px 0;">
        <p><strong>Ce que Lymphatic Care est vraiment :</strong></p>
        <p>🤝 <strong>Une vraie équipe, pas un réseau anonyme</strong><br>
        Vous rejoignez une communauté de soignants et d'anciens soignants qui ont choisi de redonner du sens à leur métier. Vous ne serez jamais seul — de l'installation au quotidien, nous vous accompagnons de A à Z.</p>
        <p>🌿 <strong>Une méthode éprouvée depuis près de 4 ans</strong><br>
        Développée par Franck et Émilie, anciens professionnels du soin d'urgence, et validée par des centaines de patients. Le soin reste au cœur de tout ce que nous faisons.</p>
        <p>📍 <strong>Un réseau qui grandit — moderne et structuré</strong><br>
        Cabinet pilote à Narbonne, licencié installé à Montpellier, bientôt Bordeaux, développement national en cours. Un modèle entrepreneurial clé en main, conçu pour des soignants qui veulent entreprendre sans se perdre.</p>
        <hr style="border:none; border-top:1px solid #ddd; margin:24px 0;">
        <p>Nous reviendrons vers vous dans les prochains jours pour un premier échange téléphonique, si votre profil correspond à nos critères de sélection.</p>
        <p>Vous pouvez aussi gagner du temps en réservant directement un créneau pour un appel de 15 minutes :</p>
        <p style="text-align:center; margin: 30px 0;">
          <a href="https://calendly.com/lymphatic-care/nouvelle-reunion" style="
            background:#2d5c47; color:white; padding:14px 28px;
            text-decoration:none; border-radius:6px; font-weight:bold;
            display:inline-block;
          ">📞 Réserver mon créneau (15 min)</a>
        </p>
        <p>À très vite,</p>
        <p><strong>Franck Meuric &amp; Émilie Daulat</strong><br>
        Cofondateurs — Lymphatic Care<br>
        <a href="mailto:reseau@lymphaticcare.fr" style="color:#2d5c47;">reseau@lymphaticcare.fr</a><br>
        <a href="https://www.lymphaticcare.fr" style="color:#2d5c47;">www.lymphaticcare.fr</a></p>
        <p style="color:#888; font-size:13px;">—<br>Sens, Soins &amp; Libertés</p>
    """),
}

WARM_J2 = {
    "subject": "Pourquoi on a tout quitté",
    "html": _wrap("""
        <p>Bonjour {prenom},</p>
        <p>Je voulais vous partager quelque chose de personnel.</p>
        <p>Avant Lymphatic Care, j'étais sapeur-pompier professionnel depuis 25 ans. Émilie était infirmière en réanimation au CHU. Nous étions tous les deux dans le soin d'urgence — passionnés, engagés, mais épuisés par un système qui broie ceux qui donnent le plus.</p>
        <p>Un jour, on a décidé de partir. Sans filet, sans certitude. On s'est installés dans une ville où on ne connaissait absolument personne, avec une méthode que nous avons bâtie pas à pas — au fil de nos formations, de nos recherches, de notre expérience de terrain et de centaines d'heures passées au chevet de nos patients.</p>
        <p>Ce qu'on a retrouvé ? Le sens du soin. Ce sentiment de vraiment soigner — pas à la chaîne, pas sous pression, mais avec du temps, de l'attention et de la gratitude. Avec des patients qui reviennent parce qu'ils vont mieux. Pas parce qu'ils y sont obligés.</p>
        <p>C'est devenu bien plus qu'un projet professionnel. Et très vite, on a voulu que ce ne soit pas qu'une histoire à nous.</p>
        <p>On a créé Lymphatic Care pour offrir cette même opportunité à d'autres soignants — ceux qui se trouvent aujourd'hui exactement là où on était : pris dans un système qui les épuise, avec l'envie profonde de soigner autrement, mais sans savoir par où commencer.</p>
        <p>Pas uniquement pour entreprendre. Pour redevenir la raison pour laquelle ils ont choisi ce métier.</p>
        <p>Si c'est aussi ce que vous cherchez, on a des choses à se dire.</p>
        <p>Réservez directement un appel téléphonique de 15 minutes :</p>
        <p style="text-align:center; margin: 30px 0;">
          <a href="https://calendly.com/lymphatic-care/nouvelle-reunion" style="
            background:#2d5c47; color:white; padding:14px 28px;
            text-decoration:none; border-radius:6px; font-weight:bold;
            display:inline-block;
          ">📞 Réserver mon créneau (15 min)</a>
        </p>
        <p>À très vite,</p>
        <p><strong>Franck Meuric &amp; Émilie Daulat</strong><br>
        Cofondateurs — Lymphatic Care<br>
        <a href="mailto:reseau@lymphaticcare.fr" style="color:#2d5c47;">reseau@lymphaticcare.fr</a><br>
        <a href="https://www.lymphaticcare.fr" style="color:#2d5c47;">www.lymphaticcare.fr</a></p>
        <p style="color:#888; font-size:13px;">—<br>Sens, Soins &amp; Libertés</p>
    """),
}

WARM_J5 = {
    "subject": "{prenom}, on peut en parler ?",
    "html": _wrap("""
        <p>Bonjour {prenom},</p>
        <p>Depuis notre dernier message, j'espère que vous avez pris le temps de réfléchir à ce qui vous a amené à nous écrire.</p>
        <p>Je ne sais pas où vous en êtes aujourd'hui. Peut-être que vous hésitez encore. Peut-être que l'idée fait son chemin. Peut-être que vous avez des questions auxquelles vous ne savez pas encore quoi répondre.</p>
        <p>C'est exactement pour ça qu'on a mis en place un premier appel — simple, sans engagement, sans pression. On ne cherche pas à recruter tout le monde. On cherche les bonnes personnes : celles qui ont envie de reprendre leur vie en main, de retrouver le sens du soin, l'équilibre, la famille. Celles qui veulent entreprendre, mais pas seules.</p>
        <p>Parce que l'entrepreneuriat, ce n'est pas un monde que les soignants connaissent. Et ça, on le sait mieux que personne. C'est pour ça qu'on est là — à chaque étape, tout au long du chemin, pour construire avec vous. Vous n'êtes jamais seul. Jamais.</p>
        <p><strong>Ce que cet appel n'est pas :</strong><br>
        Un pitch de vente. Une présentation commerciale.</p>
        <p><strong>Ce qu'il est :</strong><br>
        Une conversation entre soignants. 15 minutes pour vous écouter, comprendre votre parcours, ce que vous avez envie de construire — et voir si votre profil correspond à ce qu'on développe ensemble.</p>
        <p style="font-style:italic; color:#555; border-left: 3px solid #c9a961; padding-left: 15px; margin: 20px 0;">
          Estella est infirmière. Elle a ouvert son cabinet à Montpellier il y a 6 mois. Aujourd'hui, il la comble — du lundi au vendredi, à son rythme, celui de sa vie de famille, de ses enfants, de ses loisirs.<br><br>
          Elle nous a fait confiance parce qu'on venait du même monde qu'elle. Le soin. Elle a vu qu'Émilie et moi avions tout construit à deux, depuis zéro, avec sérieux. Qu'on lui proposait un cadre réel, un accompagnement concret, et qu'on lui montrait le chemin — parce qu'on l'avait nous-mêmes emprunté.
        </p>
        <p>C'est ça, Lymphatic Care.</p>
        <p>Si vous êtes prêt à faire ce premier pas, prenez directement rendez-vous pour un appel téléphonique de 15 minutes :</p>
        <p>À très vite,</p>
        <p><strong>Franck Meuric &amp; Émilie Daulat</strong><br>
        Cofondateurs — Lymphatic Care<br>
        <a href="mailto:reseau@lymphaticcare.fr" style="color:#2d5c47;">reseau@lymphaticcare.fr</a><br>
        <a href="https://www.lymphaticcare.fr" style="color:#2d5c47;">www.lymphaticcare.fr</a></p>
        <p style="color:#888; font-size:13px;">—<br>Sens, Soins &amp; Libertés</p>
    """, cta_url="https://calendly.com/lymphatic-care/nouvelle-reunion", cta_label="Réserver mon appel téléphonique (15 min)"),
}

WARM_J7 = {
    "subject": "La question que personne n'ose poser",
    "html": _wrap("""
        <p>Bonjour {prenom},</p>
        <p>Je voulais aborder avec vous un sujet que beaucoup de soignants n'osent pas évoquer d'emblée.</p>
        <p>L'argent.</p>
        <p>Plus précisément : la peur que l'investissement ne soit pas à la hauteur. Que ça ne marche pas. Que ça coûte trop cher pour ce que ça rapporte. Et derrière tout ça, souvent, une autre peur encore plus profonde — celle de se lancer seul dans un monde qu'on ne connaît pas.</p>
        <p>Ces peurs sont légitimes. Et on préfère en parler franchement plutôt que de les éluder.</p>
        <p>Mais permettez-moi de vous poser une question.</p>
        <p>Depuis combien d'années investissez-vous déjà — en formations, en DU, en cotisations, en énergie, en années de votre vie — sans jamais rien posséder en retour ?</p>
        <p>Avec Lymphatic Care, vous n'achetez pas une formation. Vous construisez une entreprise. Un cabinet avec un chiffre d'affaires réel, une clientèle fidélisée, une réputation locale. Un actif qui vous appartient. Et le jour où vous déciderez de passer à autre chose — dans 5 ans, dans 10 ans — vous ne repartirez pas les mains vides. Vous revendrez ce que vous avez construit. Et sa valeur sera bien supérieure à ce que vous avez investi.</p>
        <p>C'est ça, la différence entre une dépense et un investissement.</p>
        <p>Lymphatic Care, c'est aussi un modèle conçu pour que vous ne soyez jamais seul face à ce chemin :</p>
        <ul>
          <li><strong>Une redevance mensuelle fixe</strong> — pas un pourcentage de votre chiffre d'affaires. Ce que vous gagnez reste à vous.</li>
          <li><strong>Un plan de financement adapté à votre situation</strong> — on ne vous demande pas de tout régler d'un coup. On construit avec vous, à votre rythme.</li>
          <li><strong>Un accompagnement complet</strong> — formation, marketing, site internet, communication locale. Vous n'avancez jamais seul.</li>
        </ul>
        <p style="font-style:italic; color:#555; border-left: 3px solid #c9a961; padding-left: 15px; margin: 20px 0;">
          Nathalie est l'une de nos futures licenciées. Elle s'installe bientôt à Bordeaux. Elle aussi avait ces questions en tête — sur l'argent, sur le risque, sur l'entrepreneuriat qu'elle ne connaissait pas. Ce qui l'a décidée ? Pas un tableau de projections. Le fait qu'on venait du même monde qu'elle. Le soin. Et qu'on lui a proposé un cadre sérieux, un accompagnement réel — parce qu'on avait nous-mêmes emprunté ce chemin.
        </p>
        <p>Vous n'avez pas à tout savoir avant de commencer. Vous avez juste à vouloir avancer. On est là pour le reste.</p>
        <p>Si ces questions sont ce qui vous retient, c'est exactement ce dont on a besoin de parler ensemble. De vive voix, en 15 minutes.</p>
        <p>Ou répondez simplement à ce message avec vos disponibilités. On s'adapte.</p>
        <p>À très vite,</p>
        <p><strong>Franck Meuric &amp; Émilie Daulat</strong><br>
        Co-Fondateurs — Lymphatic Care<br>
        <a href="mailto:reseau@lymphaticcare.fr" style="color:#2d5c47;">reseau@lymphaticcare.fr</a><br>
        <a href="https://www.lymphaticcare.fr" style="color:#2d5c47;">www.lymphaticcare.fr</a></p>
        <p style="color:#888; font-size:13px;">—<br>Sens, Soins &amp; Libertés</p>
    """, cta_url="https://calendly.com/lymphatic-care/nouvelle-reunion", cta_label="📞 Réserver mon créneau (15 min)"),
}


# ============================================================
# SÉQUENCE COLD (4 emails, plus espacés)
# ============================================================

COLD_J0 = {
    "subject": "Le marché du drainage lymphatique en France — Étude 2026",
    "html": _wrap("""
        <h2 style="color:#2d5c47;">Bonjour {prenom},</h2>
        <p>Merci de votre intérêt pour Lymphatic Care.</p>
        <p>Votre profil actuel ne correspond pas tout à fait à notre cible prioritaire, mais on tenait à vous partager une ressource qui pourrait vous intéresser :</p>
        <h3 style="color:#c9a961;">📊 Étude : Le marché du drainage lymphatique paramédical en France (2026)</h3>
        <ul>
          <li>1,2 million de Français concernés par des problèmes lymphatiques chroniques</li>
          <li>+34% de demande pour les soins paramédicaux depuis 2022</li>
          <li>Moins de 800 praticiens formés sur le territoire</li>
          <li>Un secteur en pénurie chronique avec des tarifs libres</li>
        </ul>
        <p>Si vous changez de situation professionnelle dans les prochains mois, n'hésitez pas à revenir vers nous.</p>
        <p>Bonne lecture,<br>
        <strong>L'équipe Lymphatic Care</strong></p>
    """),
}

COLD_J10 = {
    "subject": "Pourquoi le drainage paramédical explose en France",
    "html": _wrap("""
        <h2 style="color:#2d5c47;">Bonjour {prenom},</h2>
        <p>Vous vous demandez peut-être pourquoi nous mettons autant d'énergie à développer notre réseau.</p>
        <p>Voici les 3 tendances qui rendent le drainage lymphatique paramédical incontournable :</p>
        <ol>
          <li><strong>Vieillissement de la population</strong> → 25% des +60 ans souffrent de troubles lymphatiques</li>
          <li><strong>Post-chirurgie esthétique et oncologique</strong> → besoin croissant en accompagnement paramédical</li>
          <li><strong>Reconversion massive des soignants</strong> → cherchent des modèles libéraux structurés</li>
        </ol>
        <p>Le drainage paramédical n'est pas un effet de mode. C'est une <strong>réponse structurelle</strong> à un besoin de santé publique.</p>
        <p>À bientôt,<br>
        <strong>Franck</strong></p>
    """),
}

COLD_J20 = {
    "subject": "{prenom}, êtes-vous encore en réflexion ?",
    "html": _wrap("""
        <h2 style="color:#2d5c47;">Bonjour {prenom},</h2>
        <p>Cela fait 3 semaines que vous avez exprimé votre intérêt pour Lymphatic Care.</p>
        <p>Beaucoup de soignants nous écrivent en se disant "ce n'est pas le bon moment" — et c'est très bien comme ça.</p>
        <p><strong>Mais parfois, le "bon moment" n'arrive jamais tout seul.</strong></p>
        <p>Si vous voulez explorer sérieusement notre projet, voici 3 façons de garder le contact :</p>
        <ul>
          <li>Vous inscrire à notre newsletter mensuelle (1 email par mois, contenu pédagogique)</li>
          <li>Suivre notre page LinkedIn (témoignages, ouvertures de cabinets)</li>
          <li>Réserver un appel quand vous serez prêt(e)</li>
        </ul>
        <p>Pas de pression, juste un rappel qu'on est là.</p>
        <p>L'équipe Lymphatic Care</p>
    """, cta_url="https://calendly.com/lymphatic-care/nouvelle-reunion", cta_label="Réserver un appel quand je serai prêt(e)"),
}

COLD_J30 = {
    "subject": "Dernière chance — Restons en contact ?",
    "html": _wrap("""
        <h2 style="color:#2d5c47;">Bonjour {prenom},</h2>
        <p>Cela fait maintenant un mois que nos chemins se sont croisés.</p>
        <p>Pour ne pas vous polluer la boîte mail inutilement, c'est notre dernier message dans cette séquence.</p>
        <p>Si vous voulez rester en contact ou vous re-qualifier pour un projet sérieux, c'est ici :</p>
    """, cta_url="https://calendly.com/lymphatic-care/nouvelle-reunion", cta_label="Garder le contact / réserver un appel"),
}


# ============================================================
# Lookup table
# ============================================================

WARM_SEQUENCE = {
    0: WARM_J0,
    2: WARM_J2,
    5: WARM_J5,
    7: WARM_J7,
}

COLD_SEQUENCE = {
    0: COLD_J0,
    10: COLD_J10,
    20: COLD_J20,
    30: COLD_J30,
}


def get_email_for(classification: str, days_since: int) -> dict | None:
    """
    Retourne (subject, html) pour un lead WARM ou COLD à `days_since` jours
    de sa candidature. None si pas d'email à envoyer ce jour-là.
    """
    if classification == "WARM":
        return WARM_SEQUENCE.get(days_since)
    if classification == "COLD":
        return COLD_SEQUENCE.get(days_since)
    return None
