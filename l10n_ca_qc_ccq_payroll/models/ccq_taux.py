"""Grilles de taux et barèmes de la construction, versionnés par date.

PRINCIPE, identique à celui des barèmes fiscaux du module de base : aucune valeur
n'est un « taux courant ». Chaque montant porte sa date d'entrée en vigueur, et la
recherche se fait toujours à la date des travaux. Il faut pouvoir rejouer en 2028
une paie de 2026 et retrouver le cent près, et prouver quel taux s'appliquait quand.

Les conventions changent à leurs propres dates, distinctes du calendrier fiscal :
27 avril 2025, 26 avril 2026, 25 avril 2027, 30 avril 2028 pour la période
2025-2029.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .ccq_referentiel import PERIODE_SELECTION


class CcqTauxSalaire(models.Model):
    """Taux horaire de convention, par croisement de dimensions.

    Le salaire d'un salarié de la construction ne se saisit JAMAIS : il se lit ici,
    au croisement métier × secteur × annexe × période, à la date des travaux.

    Les cotisations d'avantages sociaux ne figurent pas ici : elles viennent des
    clauses communes aux quatre conventions sectorielles et ne dépendent donc ni du
    secteur, ni de l'annexe, ni — sauf règle particulière de métier — du métier.
    Voir `ccq.avantage.social`.
    """

    _name = 'ccq.taux.salaire'
    _description = "CCQ — Taux de salaire (daté)"
    _order = 'date_debut desc, metier_id, secteur_id, periode'

    metier_id = fields.Many2one('ccq.metier', string="Métier", required=True, ondelete='cascade')
    secteur_id = fields.Many2one('ccq.secteur', string="Secteur", required=True, ondelete='cascade')
    annexe_id = fields.Many2one('ccq.annexe', string="Annexe", required=True, ondelete='cascade')
    periode = fields.Selection(PERIODE_SELECTION, string="Période", required=True)
    date_debut = fields.Date(string="En vigueur le", required=True)

    taux_horaire = fields.Float(string="Taux horaire ($)", digits=(12, 4), required=True)
    note = fields.Text(string="Source")

    @api.constrains('annexe_id', 'secteur_id')
    def _check_annexe_secteur(self):
        for taux in self:
            if taux.annexe_id.secteur_id != taux.secteur_id:
                raise ValidationError(
                    "L'annexe « %s » appartient au secteur « %s » et ne peut pas être "
                    "utilisée pour le secteur « %s »."
                    % (taux.annexe_id.code, taux.annexe_id.secteur_id.code, taux.secteur_id.code)
                )

    @api.constrains('metier_id', 'secteur_id', 'annexe_id', 'periode', 'date_debut')
    def _check_unicite(self):
        for taux in self:
            doublon = self.search_count([
                ('metier_id', '=', taux.metier_id.id),
                ('secteur_id', '=', taux.secteur_id.id),
                ('annexe_id', '=', taux.annexe_id.id),
                ('periode', '=', taux.periode),
                ('date_debut', '=', taux.date_debut),
                ('id', '!=', taux.id),
            ])
            if doublon:
                raise ValidationError(
                    "Un taux existe déjà pour cette combinaison à la date du %s."
                    % taux.date_debut
                )

    @api.model
    def _taux_applicable(self, metier, secteur, annexe, periode, date):
        """Taux en vigueur à `date` pour la combinaison demandée.

        Retourne l'enregistrement dont la date d'entrée en vigueur est la plus
        récente parmi celles antérieures ou égales à la date des travaux — même
        logique que `hr.rule.parameter`, donc pas de date de fin à maintenir.
        """
        return self.search([
            ('metier_id', '=', metier.id),
            ('secteur_id', '=', secteur.id),
            ('annexe_id', '=', annexe.id),
            ('periode', '=', periode),
            ('date_debut', '<=', date),
        ], order='date_debut desc', limit=1)


class CcqTauxQualification(models.Model):
    """Fonds de qualification — cotisation patronale en $/h, propre au métier.

    Tous les métiers n'y sont pas assujettis : le 416, mécanicien en
    protection-incendie, n'apparaît pas dans la table de PD5277. Absence
    d'enregistrement = cotisation nulle, ce qui est le comportement voulu.
    """

    _name = 'ccq.taux.qualification'
    _description = "CCQ — Fonds de qualification (daté)"
    _order = 'date_debut desc, metier_id'

    metier_id = fields.Many2one('ccq.metier', string="Métier", required=True, ondelete='cascade')
    date_debut = fields.Date(string="En vigueur le", required=True)
    taux_horaire = fields.Float(string="Cotisation ($/h)", digits=(12, 4), required=True)

    @api.model
    def _taux_applicable(self, metier, date):
        return self.search([
            ('metier_id', '=', metier.id),
            ('date_debut', '<=', date),
        ], order='date_debut desc', limit=1)


class CcqBaremeDeplacement(models.Model):
    """Barème de frais de déplacement et de chambre et pension.

    ⚠️ Ce n'est PAS un taux au kilomètre. La convention fixe des PALIERS de
    distance entre le domicile du salarié et le chantier, et à chaque palier
    correspond un FORFAIT. Règle générale IC/I : 65 km et plus, puis 90 km et
    plus ; au-delà de 120 km on bascule sur la chambre et pension.

    Certains métiers ont leur propre grille de paliers (le mécanicien d'ascenseur
    en a six). Le métier 416 n'en a pas : la règle générale s'applique, d'où
    `metier_ids` vide = règle générale.

    En cas de désaccord sur la distance, la convention désigne Google Maps comme
    arbitre, sur le trajet usuel entre l'adresse du domicile et celle du chantier.
    Aucune API n'est appelée ici : la distance est saisie et reste vérifiable.
    """

    _name = 'ccq.bareme.deplacement'
    _description = "CCQ — Barème de déplacement (daté)"
    _order = 'date_debut desc, secteur_id, type_indemnite, palier_km'

    secteur_id = fields.Many2one('ccq.secteur', string="Secteur", required=True, ondelete='cascade')
    metier_ids = fields.Many2many(
        'ccq.metier', string="Métiers visés",
        help="Vide = règle générale du secteur. Renseigné = règle particulière, "
             "prioritaire pour ces métiers.",
    )
    type_indemnite = fields.Selection(
        [('deplacement', "Frais de déplacement"),
         ('chambre_pension', "Chambre et pension")],
        string="Type", required=True, default='deplacement',
    )
    palier_km = fields.Float(
        string="Palier (km et plus)", digits=(8, 2), required=True,
        help="Distance minimale déclenchant ce forfait.",
    )
    montant = fields.Float(string="Forfait ($)", digits=(12, 2), required=True)
    date_debut = fields.Date(string="En vigueur le", required=True)
    note = fields.Text(string="Source")

    @api.model
    def _bareme_applicable(self, secteur, metier, type_indemnite, distance_km, date):
        """Forfait applicable : palier le plus élevé atteint par la distance.

        Les règles particulières de métier l'emportent sur la règle générale. On
        cherche donc d'abord une grille propre au métier ; si elle existe, on ne
        retombe PAS sur la générale, sinon on mélangerait deux barèmes.
        """
        base = [
            ('secteur_id', '=', secteur.id),
            ('type_indemnite', '=', type_indemnite),
            ('date_debut', '<=', date),
            ('palier_km', '<=', distance_km),
        ]
        particulier = self.search(
            base + [('metier_ids', 'in', metier.id)], order='palier_km desc, date_debut desc')
        if particulier:
            return particulier[0]
        general = self.search(
            base + [('metier_ids', '=', False)], order='palier_km desc, date_debut desc')
        return general[0] if general else self.browse()
