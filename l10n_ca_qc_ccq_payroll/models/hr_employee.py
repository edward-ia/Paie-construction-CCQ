"""Dimensions CCQ portées par le salarié.

Quatre des sept dimensions du rapport mensuel vivent ici : le métier, la période
d'apprentissage, le statut et le syndicat (association et local). Elles sont stables — elles
ne changent qu'à une progression d'apprentissage ou à un changement de local.

POURQUOI SUR hr.employee ET NON SUR hr.version : en Odoo 19, tout ce qui
détermine la paie vit normalement sur hr.version, qui historise. Ici ce n'est pas
nécessaire, parce que l'historisation est déjà assurée ailleurs et mieux : chaque
ligne de feuille de temps FIGE les dimensions et le taux au moment du calcul (voir
ccq_feuille_temps.py). Une progression d'apprentissage ne réécrit donc jamais le
passé. Garder ces champs sur l'employé évite de dupliquer une version à chaque
changement de local syndical, qui n'a rien d'un événement contractuel.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .ccq_referentiel import PERIODE_SELECTION, STATUT_SELECTION


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    l10n_ca_qc_ccq_assujetti = fields.Boolean(
        string="Salarié assujetti à la loi R-20",
        help="Décoché pour le personnel de bureau, les vendeurs et les gestionnaires, "
             "qui sont hors du champ d'application même dans une entreprise "
             "entièrement assujettie.",
    )
    l10n_ca_qc_ccq_metier_id = fields.Many2one(
        'ccq.metier', string="Métier CCQ", ondelete='restrict')
    l10n_ca_qc_ccq_periode = fields.Selection(
        PERIODE_SELECTION, string="Période d'apprentissage",
        help="Détermine le taux horaire au croisement avec le secteur et l'annexe du "
             "chantier. Aucun montant n'est saisi sur la fiche de l'employé.",
    )
    l10n_ca_qc_ccq_local_id = fields.Many2one(
        'ccq.local.syndical', string="Local syndical", ondelete='restrict')
    l10n_ca_qc_ccq_association_id = fields.Many2one(
        'ccq.association.syndicale', string="Association syndicale",
        related='l10n_ca_qc_ccq_local_id.association_id', store=True, readonly=True)
    l10n_ca_qc_ccq_statut = fields.Selection(
        STATUT_SELECTION, string="Statut au rapport mensuel",
        help="À laisser vide pour un salarié ordinaire de la construction. Les codes "
             "du tableau B ne servent qu'aux situations particulières et commandent "
             "des exceptions de cotisation.",
    )
    l10n_ca_qc_ccq_carte_competence = fields.Char(
        string="Certificat de compétence",
        help="Numéro du certificat délivré par la CCQ.")
    l10n_ca_qc_ccq_carte_expiration = fields.Date(string="Échéance du certificat")

    @api.constrains('l10n_ca_qc_ccq_assujetti', 'l10n_ca_qc_ccq_metier_id',
                    'l10n_ca_qc_ccq_periode')
    def _check_dimensions_ccq(self):
        """Un salarié assujetti sans métier ni période ne peut pas être payé.

        On bloque tôt : sans ces deux valeurs, aucun taux n'est trouvable dans la
        grille de convention et la feuille de temps échouerait au calcul.
        """
        for employee in self:
            if employee.l10n_ca_qc_ccq_assujetti and not (
                    employee.l10n_ca_qc_ccq_metier_id and employee.l10n_ca_qc_ccq_periode):
                raise ValidationError(
                    "L'employé « %s » est assujetti à la loi R-20 : son métier CCQ et sa "
                    "période d'apprentissage sont obligatoires." % employee.name
                )

    @api.constrains('l10n_ca_qc_ccq_metier_id', 'l10n_ca_qc_ccq_periode')
    def _check_periode_coherente(self):
        """La période doit exister pour ce métier.

        Un métier à 3 périodes d'apprentissage ne peut pas avoir d'apprenti de
        4e période — c'est une erreur de saisie qui produirait un taux introuvable.
        """
        rangs = {'apprenti_1': 1, 'apprenti_2': 2, 'apprenti_3': 3,
                 'apprenti_4': 4, 'apprenti_5': 5}
        for employee in self:
            metier = employee.l10n_ca_qc_ccq_metier_id
            rang = rangs.get(employee.l10n_ca_qc_ccq_periode)
            # nb_periodes_apprentissage = 0 signifie « non renseigné » : on ne
            # contrôle rien plutôt que de rejeter à tort une saisie valide.
            if (metier and rang and metier.nb_periodes_apprentissage
                    and rang > metier.nb_periodes_apprentissage):
                raise ValidationError(
                    "Le métier « %s » compte %s période(s) d'apprentissage : la période "
                    "choisie pour « %s » n'existe pas."
                    % (metier.display_name, metier.nb_periodes_apprentissage, employee.name)
                )
