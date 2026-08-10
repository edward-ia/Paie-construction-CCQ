"""Cotisations aux régimes d'avantages sociaux de la construction.

Deux caisses, deux payeurs, un montant par heure travaillée : caisse de
prévoyance collective (assurance) et caisse de retraite, chacune alimentée par
une cotisation patronale et une cotisation salariale précomptée. Fondement :
R-20, r. 10, articles 11 à 13, et clause 27.03 des clauses communes aux quatre
conventions collectives sectorielles.

CES MONTANTS NE SONT PAS SUR LA GRILLE DE TAUX. Ils viennent des clauses
COMMUNES : identiques pour tous les métiers, tous les secteurs et toutes les
annexes, la seule distinction générale étant Apprenti / autres salariés sur la
cotisation patronale de retraite. Les porter sur `ccq.taux.salaire` obligerait à
répéter deux valeurs sur quarante lignes, et une ligne oubliée au millésime
suivant produirait un salarié calculé faux sans que rien ne le signale.

RÈGLE GÉNÉRALE ET RÈGLES PARTICULIÈRES, même mécanique que les barèmes de
déplacement : `metier_ids` vide décrit la règle commune, `metier_ids` renseigné
une règle particulière qui la remplace pour ces métiers seulement. La clause
27.06 en compte vingt-six, chacune de forme différente — le mécanicien en
protection-incendie (416) remplace ainsi le montant fixe de retraite salariale
par un pourcentage du taux de salaire.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

CAISSE_SELECTION = [
    ('prevoyance', "Caisse de prévoyance collective (assurance)"),
    ('retraite', "Caisse de retraite"),
]

PAYEUR_SELECTION = [
    ('salarie', "Salarié (précomptée sur le salaire)"),
    ('employeur', "Employeur"),
]

APPLICATION_SELECTION = [
    ('tous', "Tous les salariés"),
    ('apprenti', "Apprentis"),
    ('autres', "Compagnons et occupations"),
]

MODE_SELECTION = [
    ('fixe', "Montant fixe ($/h)"),
    ('pourcentage', "% du taux de salaire régulier majoré de l'indemnité de congés"),
]


class CcqAvantageSocial(models.Model):
    _name = 'ccq.avantage.social'
    _description = "CCQ — Cotisation d'avantages sociaux (datée)"
    _order = 'date_debut desc, caisse, payeur, application'

    date_debut = fields.Date(string="En vigueur le", required=True)
    caisse = fields.Selection(CAISSE_SELECTION, string="Caisse", required=True)
    payeur = fields.Selection(PAYEUR_SELECTION, string="Payeur", required=True)
    application = fields.Selection(
        APPLICATION_SELECTION, string="S'applique à", required=True, default='tous',
        help="La convention ne distingue l'Apprenti que sur la cotisation patronale "
             "de retraite ; les trois autres montants sont les mêmes pour tous.",
    )
    metier_ids = fields.Many2many(
        'ccq.metier', string="Métiers visés",
        help="Vide = règle générale des clauses communes. Renseigné = règle "
             "particulière de l'article 27.06, prioritaire pour ces métiers.",
    )
    mode = fields.Selection(
        MODE_SELECTION, string="Mode", required=True, default='fixe',
        help="Le pourcentage porte sur le taux de salaire RÉGULIER, jamais sur le "
             "taux majoré des heures supplémentaires.",
    )
    valeur = fields.Float(string="Valeur", digits=(12, 4), required=True)
    note = fields.Text(string="Source")

    @api.depends('caisse', 'payeur', 'date_debut')
    def _compute_display_name(self):
        for cotisation in self:
            cotisation.display_name = "%s — %s au %s" % (
                dict(CAISSE_SELECTION).get(cotisation.caisse, "?"),
                dict(PAYEUR_SELECTION).get(cotisation.payeur, "?"),
                cotisation.date_debut or "?",
            )

    @api.constrains('valeur')
    def _check_valeur_positive(self):
        for cotisation in self:
            if cotisation.valeur < 0:
                raise ValidationError("Une cotisation d'avantages sociaux ne peut pas être négative.")

    @api.constrains('date_debut', 'caisse', 'payeur', 'application', 'metier_ids')
    def _check_recouvrement(self):
        """Interdit deux cotisations concurrentes à la même date.

        Sans cette garde, deux enregistrements qui se recouvrent laisseraient la
        recherche en choisir un au hasard, et la retenue changerait sans que rien
        ne l'annonce. Deux portées de métiers se recouvrent si elles sont toutes
        deux générales ou si elles partagent un métier ; deux portées
        d'application se recouvrent dès que l'une d'elles vaut « tous ».
        """
        for cotisation in self:
            concurrentes = self.search([
                ('id', '!=', cotisation.id),
                ('caisse', '=', cotisation.caisse),
                ('payeur', '=', cotisation.payeur),
                ('date_debut', '=', cotisation.date_debut),
            ])
            for autre in concurrentes:
                memes_metiers = (
                    (not cotisation.metier_ids and not autre.metier_ids)
                    or bool(set(cotisation.metier_ids.ids) & set(autre.metier_ids.ids))
                )
                memes_salaries = (
                    'tous' in (cotisation.application, autre.application)
                    or cotisation.application == autre.application
                )
                if memes_metiers and memes_salaries:
                    raise ValidationError(
                        "Une cotisation concurrente existe déjà pour cette caisse, ce "
                        "payeur et ces salariés au %s." % cotisation.date_debut
                    )

    @api.model
    def _cotisation_applicable(self, metier, caisse, payeur, periode, date):
        """Cotisation en vigueur à `date`, règle particulière prioritaire.

        Si le métier a sa propre règle, on ne retombe PAS sur la règle générale :
        la règle particulière la remplace, elle ne s'y ajoute pas. Pour le 416,
        additionner les deux ferait payer au salarié le pourcentage du 27.06 EN
        PLUS du montant fixe du 27.03, que le pourcentage inclut déjà.
        """
        salaries = 'apprenti' if (periode or '').startswith('apprenti') else 'autres'
        base = [
            ('caisse', '=', caisse),
            ('payeur', '=', payeur),
            ('application', 'in', ['tous', salaries]),
            ('date_debut', '<=', date),
        ]
        particuliere = self.search(
            base + [('metier_ids', 'in', metier.id)], order='date_debut desc', limit=1)
        if particuliere:
            return particuliere
        return self.search(
            base + [('metier_ids', '=', False)], order='date_debut desc', limit=1)

    def _montant_horaire(self, taux_horaire, facteur_conges):
        """Montant dû pour une heure travaillée, à ce taux de convention."""
        self.ensure_one()
        if self.mode == 'pourcentage':
            return self.valeur * taux_horaire * facteur_conges
        return self.valeur
