"""Cotisations aux régimes d'avantages sociaux de la construction.

Trois caisses, deux payeurs, un montant par heure travaillée : caisse de
prévoyance collective (assurance), caisse supplémentaire d'assurance et caisse
de retraite, chacune alimentée par une cotisation patronale et une cotisation
salariale précomptée. Fondement : R-20, r. 10, articles 11 à 13, et clause 27.03
des clauses communes aux quatre conventions collectives sectorielles.

CES MONTANTS NE SONT PAS SUR LA GRILLE DE TAUX. Ils viennent des clauses
COMMUNES : identiques pour tous les métiers, tous les secteurs et toutes les
annexes, la seule distinction générale étant Apprenti / autres salariés sur la
cotisation patronale de retraite. Les porter sur `ccq.taux.salaire` obligerait à
répéter deux valeurs sur quarante lignes, et une ligne oubliée au millésime
suivant produirait un salarié calculé faux sans que rien ne le signale.

RÈGLE GÉNÉRALE ET RÈGLES PARTICULIÈRES, même mécanique que les barèmes de
déplacement : `metier_ids` vide décrit la règle commune, `metier_ids` renseigné
une règle particulière. La clause 27.06 en compte vingt-six, chacune de forme
différente. Deux rapports possibles à la règle générale, et la convention les
distingue au texte pour un même métier — le mécanicien en protection-incendie
(416) REMPLACE le montant fixe de retraite salariale par un pourcentage, que la
clause dit inclure le montant commun, mais AJOUTE un supplément au montant
commun de prévoyance patronale. D'où `cumul_regle_generale`, qui évite de
recopier le montant commun dans la règle du métier : recopié, il cesserait de
suivre ses propres millésimes.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

CAISSE_SELECTION = [
    ('prevoyance', "Caisse de prévoyance collective (assurance)"),
    ('supplementaire', "Caisse supplémentaire d'assurance"),
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
    ('pct_taux_majore', "% du taux de salaire régulier majoré de l'indemnité de congés"),
    ('pct_taux_compagnon', "% du taux de salaire du compagnon, non majoré"),
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
        help="Les deux pourcentages n'ont pas la même assiette, et la convention "
             "les distingue au texte : la cotisation de retraite du salarié est "
             "majorée de l'indemnité de congés, la cotisation de prévoyance de "
             "l'employeur ne l'est pas et se calcule sur le taux du compagnon, "
             "même pour un apprenti. Dans les deux cas le taux de référence est le "
             "taux RÉGULIER, jamais celui des heures supplémentaires.",
    )
    valeur = fields.Float(string="Valeur", digits=(12, 4), required=True)
    cumul_regle_generale = fields.Boolean(
        string="S'ajoute à la règle générale",
        help="Coché, le montant s'ajoute à celui des clauses communes au lieu de "
             "le remplacer. Le montant commun n'est alors pas recopié ici : il "
             "reste lu dans la règle générale et suit donc ses millésimes de "
             "lui-même. Réservé aux règles particulières de métier.",
    )
    ajustement = fields.Float(
        string="Ajustement ($/h)", digits=(12, 4),
        help="Montant ajouté au résultat, négatif s'il en est retranché.",
    )
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

    @api.constrains('cumul_regle_generale', 'metier_ids')
    def _check_cumul_particulier(self):
        """Une règle générale ne peut pas s'ajouter à elle-même."""
        for cotisation in self:
            if cotisation.cumul_regle_generale and not cotisation.metier_ids:
                raise ValidationError(
                    "Seule une règle particulière de métier peut s'ajouter à la "
                    "règle générale."
                )

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
        """Cotisations en vigueur à `date`, règle particulière prioritaire.

        Rend un ensemble, dont les montants s'additionnent. Il compte une seule
        règle dans le cas ordinaire : si le métier a sa propre règle, on ne
        retombe PAS sur la règle générale, car la règle particulière la remplace.
        Pour la retraite salariale du 416, additionner les deux ferait payer le
        pourcentage du 27.06 EN PLUS du montant fixe du 27.03, que le
        pourcentage inclut déjà.

        Il en compte deux quand la règle particulière est cochée
        `cumul_regle_generale`, forme de la prévoyance patronale du 416, qui part
        du montant commun et lui ajoute un supplément.
        """
        salaries = 'apprenti' if (periode or '').startswith('apprenti') else 'autres'
        base = [
            ('caisse', '=', caisse),
            ('payeur', '=', payeur),
            ('application', 'in', ['tous', salaries]),
            ('date_debut', '<=', date),
        ]
        generale = self.search(
            base + [('metier_ids', '=', False)], order='date_debut desc', limit=1)
        if not metier:
            return generale
        particuliere = self.search(
            base + [('metier_ids', 'in', metier.id)], order='date_debut desc', limit=1)
        if not particuliere:
            return generale
        if not particuliere.cumul_regle_generale:
            return particuliere
        if not generale:
            raise UserError(
                "La règle particulière « %s » du métier %s s'ajoute à la règle "
                "générale, mais aucune règle générale n'est définie pour cette "
                "caisse et ce payeur au %s."
                % (particuliere.display_name, metier.display_name, date)
            )
        return generale + particuliere

    def _montant_horaire(self, taux_horaire, taux_compagnon, facteur_conges):
        """Montant dû pour une heure travaillée, à ce taux de convention."""
        total = 0.0
        for cotisation in self:
            if cotisation.mode == 'pct_taux_majore':
                total += cotisation.valeur * taux_horaire * facteur_conges
            elif cotisation.mode == 'pct_taux_compagnon':
                total += cotisation.valeur * taux_compagnon
            else:
                total += cotisation.valeur
            total += cotisation.ajustement
        return total
