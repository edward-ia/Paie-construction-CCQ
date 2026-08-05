"""Référentiel de la construction assujettie à la loi R-20.

Ces modèles ne portent AUCUN calcul : ils décrivent le vocabulaire imposé par la
CCQ (secteurs, annexes, métiers, régions, syndicats, primes de convention). Tout
le reste du module s'y adosse.

Rappel de conception : le rapport mensuel de la CCQ exige une ligne par
combinaison métier × période × statut × secteur × annexe × région × syndicat.
Ces sept dimensions ne se saisissent jamais à la main sur une feuille de temps —
elles se déduisent de l'employé et du chantier. C'est ce qui rend le système
utilisable ; voir ccq_feuille_temps.py.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Périodes d'apprentissage. Le taux d'un apprenti est un pourcentage de celui du
# compagnon, propre au métier ; on ne stocke donc jamais un montant sur l'employé,
# seulement sa période. « sans_periode » couvre les occupations, qui n'ont pas
# d'apprentissage.
PERIODE_SELECTION = [
    ('apprenti_1', "Apprenti — 1re période"),
    ('apprenti_2', "Apprenti — 2e période"),
    ('apprenti_3', "Apprenti — 3e période"),
    ('apprenti_4', "Apprenti — 4e période"),
    ('apprenti_5', "Apprenti — 5e période"),
    ('compagnon', "Compagnon"),
    ('sans_periode', "Sans période (occupation)"),
]

STATUT_SELECTION = [
    ('A', "A — Contribution volontaire (avec avantages sociaux)"),
    ('C', "C — Entrepreneur autonome (sans avantages sociaux)"),
    ('E', "E — Représentant désigné (avec avantages sociaux)"),
    ('H', "H — Association syndicale (avantages sociaux, assurance et retraite)"),
    ('I', "I — Association syndicale (assurance seulement)"),
    ('J', "J — Association syndicale (retraite seulement)"),
]


class CcqSecteur(models.Model):
    """Un des quatre secteurs de la loi R-20.

    Le secteur est une propriété du CHANTIER, jamais de l'employeur : un même
    entrepreneur peut être sous trois conventions différentes la même semaine.
    Chaque secteur a sa propre convention collective, donc ses propres primes,
    seuils d'heures, majorations et barèmes de déplacement.
    """

    _name = 'ccq.secteur'
    _description = "CCQ — Secteur (loi R-20)"
    _order = 'code'

    name = fields.Char(string="Nom", required=True, translate=True)
    code = fields.Char(
        string="Code", required=True,
        help="Code court utilisé par les tables de taux et les paramètres datés "
             "(RES, IC, IND, GCV).",
    )
    convention_ref = fields.Char(
        string="Référence de la convention",
        help="Numéro du document CCQ de la convention collective en vigueur "
             "(ex. PD5145 pour l'institutionnel et commercial 2025-2029).",
    )
    active = fields.Boolean(default=True)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for secteur in self:
            secteur.display_name = "%s — %s" % (secteur.code, secteur.name)

    @api.constrains('code')
    def _check_code_unique(self):
        for secteur in self:
            if self.search_count([('code', '=', secteur.code), ('id', '!=', secteur.id)]):
                raise ValidationError("Le code de secteur « %s » existe déjà." % secteur.code)


class CcqAnnexe(models.Model):
    """Annexe de salaire d'une convention collective.

    Une annexe est une pièce jointe à la fin de la convention : elle contient une
    GRILLE DE TAUX. Ce n'est pas une région — deux chantiers de la même région
    administrative peuvent relever d'annexes différentes selon qu'ils sont en
    milieu urbain ou isolé.

    ⚠️ Une annexe ne se contente pas de changer les prix : elle peut aussi
    surcharger des RÈGLES. Exemple vérifié à la section XXI de PD5145 — sur les
    chantiers isolés, le territoire de la Baie-James et au nord du 55e parallèle
    (annexe C-1), les CINQ premières heures supplémentaires sont à +50 % avant le
    passage à +100 %, contre UNE seule en régime normal. D'où le champ
    `heures_supp_a_taux_simple` porté ici plutôt que codé en dur.
    """

    _name = 'ccq.annexe'
    _description = "CCQ — Annexe de salaire"
    _order = 'secteur_id, code'

    name = fields.Char(string="Nom", required=True, translate=True)
    code = fields.Char(string="Code", required=True, help="Ex. « C », « C-1 », « B-1 », « R-2 ».")
    secteur_id = fields.Many2one('ccq.secteur', string="Secteur", required=True, ondelete='restrict')
    chantier_isole = fields.Boolean(
        string="Chantier isolé / territoire nordique",
        help="Coché pour les annexes couvrant les chantiers isolés, le territoire "
             "de la Baie-James et les projets au nord du 55e parallèle.",
    )
    heures_supp_a_taux_simple = fields.Integer(
        string="Heures supp. à +50 % avant +100 %",
        default=1,
        help="Nombre d'heures supplémentaires majorées de 50 % avant le passage à "
             "100 %. Régime normal : 1. Chantiers isolés / Baie-James / nord du "
             "55e parallèle : 5 (PD5145, section XXI).",
    )
    note = fields.Text(string="Portée")
    active = fields.Boolean(default=True)

    @api.depends('code', 'secteur_id.code')
    def _compute_display_name(self):
        for annexe in self:
            annexe.display_name = "%s — %s" % (annexe.secteur_id.code or '?', annexe.code)


class CcqRegion(models.Model):
    """Région administrative de la CCQ.

    Sert à la DÉCLARATION au rapport mensuel (une des sept dimensions), pas au
    calcul du taux — c'est l'annexe qui porte la grille. À ne pas confondre avec
    l'annexe : la région dit OÙ, l'annexe dit QUELLE GRILLE.

    ⚠️ La liste officielle des régions n'est volontairement pas livrée en données :
    elle doit être saisie depuis la source CCQ, pas devinée.
    """

    _name = 'ccq.region'
    _description = "CCQ — Région"
    _order = 'code'

    name = fields.Char(string="Nom", required=True, translate=True)
    code = fields.Char(string="Code", required=True)
    active = fields.Boolean(default=True)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for region in self:
            region.display_name = "%s — %s" % (region.code, region.name)


class CcqMetier(models.Model):
    """Métier, spécialité ou occupation reconnu par la CCQ."""

    _name = 'ccq.metier'
    _description = "CCQ — Métier / occupation"
    _order = 'code'

    name = fields.Char(string="Nom", required=True, translate=True)
    code = fields.Char(
        string="Code CCQ", required=True,
        help="Code officiel du métier (ex. 416 pour mécanicien en protection-incendie).",
    )
    type_emploi = fields.Selection(
        [('metier', "Métier"), ('specialite', "Spécialité"), ('occupation', "Occupation")],
        string="Type", required=True, default='metier',
    )
    nb_periodes_apprentissage = fields.Integer(
        string="Nombre de périodes d'apprentissage",
        help="0 pour les occupations, qui n'ont pas d'apprentissage.",
    )
    active = fields.Boolean(default=True)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for metier in self:
            metier.display_name = "%s — %s" % (metier.code, metier.name)

    @api.constrains('code')
    def _check_code_unique(self):
        for metier in self:
            if self.search_count([('code', '=', metier.code), ('id', '!=', metier.id)]):
                raise ValidationError("Le code de métier « %s » existe déjà." % metier.code)


class CcqAssociationSyndicale(models.Model):
    """Association syndicale du salarié — il y en a cinq dans la construction."""

    _name = 'ccq.association.syndicale'
    _description = "CCQ — Association syndicale"
    _order = 'code'

    name = fields.Char(string="Nom", required=True, translate=True)
    code = fields.Char(string="Code", required=True)
    active = fields.Boolean(default=True)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for asso in self:
            asso.display_name = "%s — %s" % (asso.code, asso.name)


class CcqLocalSyndical(models.Model):
    """Local (section locale) rattaché à une association syndicale.

    La cotisation syndicale ne se calcule PAS de la même façon d'un local à
    l'autre : PD5277 décrit des formules hétéroclites — pourcentage de la première
    heure travaillée de la semaine, forfait hebdomadaire, parfois un supplément à
    l'heure par-dessus. C'est pour ça que le mode de calcul vit sur le local et
    non dans le code.
    """

    _name = 'ccq.local.syndical'
    _description = "CCQ — Local syndical"
    _order = 'association_id, numero'

    name = fields.Char(string="Nom", translate=True)
    numero = fields.Char(string="Numéro du local", required=True)
    association_id = fields.Many2one(
        'ccq.association.syndicale', string="Association", required=True, ondelete='restrict')
    metier_ids = fields.Many2many(
        'ccq.metier', string="Métiers représentés",
        help="Laisser vide si le local n'est pas restreint à certains métiers.",
    )
    cotisation_ids = fields.One2many(
        'ccq.cotisation.syndicale', 'local_id', string="Cotisations datées")
    active = fields.Boolean(default=True)

    @api.depends('numero', 'name', 'association_id.code')
    def _compute_display_name(self):
        for local in self:
            local.display_name = "%s — local %s%s" % (
                local.association_id.code or '?',
                local.numero,
                " (%s)" % local.name if local.name else "",
            )


class CcqCotisationSyndicale(models.Model):
    """Formule de cotisation syndicale d'un local, à une date donnée.

    Deux composantes possibles, cumulables : une base (pourcentage ou forfait)
    et un supplément à l'heure. Versionné par date d'entrée en vigueur, comme
    tout le reste — on doit pouvoir rejouer une paie de l'an dernier.
    """

    _name = 'ccq.cotisation.syndicale'
    _description = "CCQ — Cotisation syndicale (datée)"
    _order = 'local_id, date_debut desc'

    local_id = fields.Many2one(
        'ccq.local.syndical', string="Local", required=True, ondelete='cascade')
    date_debut = fields.Date(string="En vigueur le", required=True)
    mode_base = fields.Selection(
        [
            ('pct_premiere_heure', "Pourcentage de la 1re heure travaillée de la semaine"),
            ('forfait_hebdo', "Forfait hebdomadaire"),
            ('pct_salaire', "Pourcentage du salaire"),
            ('montant_horaire', "Montant par heure travaillée"),
        ],
        string="Mode de calcul", required=True,
    )
    valeur_base = fields.Float(
        string="Valeur", digits=(12, 4),
        help="Pourcentage exprimé en décimal (0,015 pour 1,5 %) ou montant en dollars "
             "selon le mode choisi.",
    )
    supplement_horaire = fields.Float(
        string="Supplément par heure ($)", digits=(12, 4),
        help="S'ajoute à la base. Zéro si le local n'en prévoit pas.",
    )
    note = fields.Text(string="Note")


class CcqPrime(models.Model):
    """Prime prévue par une convention collective.

    ⚠️ Règle d'ordre de calcul — PD5145, article 22.01 : la rémunération des
    heures supplémentaires est établie AVANT que les primes ne soient ajoutées.
    Le pourcentage de majoration ne s'applique donc PAS aux primes, à la SEULE
    exception de celles de l'article 22.03 (chef d'équipe et chef de groupe).

    Écrire « (taux + prime) × 1,5 » fait payer trop ; oublier l'exception du chef
    d'équipe fait payer trop peu. Les deux erreurs sont invisibles sur un talon et
    très visibles en vérification CCQ. D'où deux drapeaux DISTINCTS :

      - `majorable`            : la prime suit-elle la majoration des heures supp ?
      - `versee_heures_supp`   : la prime est-elle versée sur les heures supp ?

    Ce sont bien deux questions différentes. Le chaudronnier en est la preuve :
    sa prime est explicitement versée en heures supplémentaires mais non majorée.
    """

    _name = 'ccq.prime'
    _description = "CCQ — Prime de convention"
    _order = 'secteur_id, article, code'

    name = fields.Char(string="Nom", required=True, translate=True)
    code = fields.Char(string="Code", required=True)
    article = fields.Char(
        string="Article de la convention",
        help="Référence exacte, ex. « 22.02 j) ». Sert à justifier un calcul en vérification.",
    )
    secteur_id = fields.Many2one('ccq.secteur', string="Secteur", required=True, ondelete='restrict')
    metier_ids = fields.Many2many(
        'ccq.metier', string="Métiers visés",
        help="Vide = règle générale du secteur. Renseigné = règle particulière, qui "
             "l'emporte sur la règle générale pour ces métiers.",
    )
    mode = fields.Selection(
        [('pourcentage', "Pourcentage du taux de salaire"),
         ('montant_horaire', "Montant par heure ($)")],
        string="Mode de calcul", required=True, default='pourcentage',
    )
    valeur = fields.Float(
        string="Valeur", digits=(12, 4), required=True,
        help="Pourcentage exprimé en décimal (0,10 pour 10 %) ou montant en dollars. "
             "Un pourcentage s'applique au taux de salaire DU SALARIÉ — un apprenti "
             "reçoit donc un pourcentage de SON taux, pas de celui du compagnon.",
    )
    majorable = fields.Boolean(
        string="Majorée en heures supplémentaires",
        help="Faux pour presque toutes les primes (art. 22.01). Vrai uniquement pour "
             "les primes de chef d'équipe et de chef de groupe (art. 22.03).",
    )
    versee_heures_supp = fields.Boolean(
        string="Versée sur les heures supplémentaires", default=True,
        help="Indépendant de « majorée ». Certains articles le précisent explicitement.",
    )
    date_debut = fields.Date(string="En vigueur le", required=True)
    note = fields.Text(string="Note")
    active = fields.Boolean(default=True)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for prime in self:
            prime.display_name = "%s — %s" % (prime.code, prime.name)

    @api.model
    def _version_applicable(self, prime, date):
        return self.search([
            ('code', '=', prime.code),
            ('secteur_id', '=', prime.secteur_id.id),
            ('date_debut', '<=', date),
        ], order='date_debut desc', limit=1)
