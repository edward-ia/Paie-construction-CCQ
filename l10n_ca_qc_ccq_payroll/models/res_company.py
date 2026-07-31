"""Identifiants de l'entreprise auprès de la CCQ et de la RBQ.

Ce sont des données PROPRES AU CLIENT, donc saisies dans l'interface — jamais dans
le code. C'est ce qui permet de vendre le même module à plusieurs entrepreneurs :
la partie spécifique est de la configuration, pas du développement.

Les numéros RP (ARC), RS (Revenu Québec) et le taux CNESST sont déjà portés par le
module de base l10n_ca_qc_hr_payroll et ne sont pas redéclarés ici.
"""

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ca_qc_ccq_employeur = fields.Boolean(
        string="Employeur assujetti à la loi R-20",
        help="Active la couche construction. Une entreprise assujettie peut malgré "
             "tout avoir du personnel et des travaux hors champ.",
    )
    l10n_ca_qc_ccq_numero_employeur = fields.Char(
        string="Numéro d'employeur CCQ",
        help="Numéro attribué par la Commission de la construction du Québec. Sert au "
             "rapport mensuel et au paiement des sommes dues.",
    )
    l10n_ca_qc_ccq_licence_rbq = fields.Char(
        string="Licence RBQ",
        help="Numéro de licence de la Régie du bâtiment du Québec.",
    )
