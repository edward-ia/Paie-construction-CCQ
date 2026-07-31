from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ca_qc_cnesst_rate = fields.Float(
        string="Taux CNESST (%)",
        digits=(5, 4),
        help="Taux de prime CNESST attribué à l'entreprise, en pourcentage de la "
             "masse salariale assurable. Fourni par la CNESST, propre à chaque "
             "employeur et à son unité de classification.",
    )
    l10n_ca_qc_rp_number = fields.Char(
        string="Numéro RP (ARC)",
        help="Numéro de compte de retenues sur la paie auprès de l'Agence du "
             "revenu du Canada (ex. 123456789 RP0001). Sert à remettre l'impôt "
             "fédéral et l'assurance-emploi.",
    )
    l10n_ca_qc_rs_number = fields.Char(
        string="Numéro RS (Revenu Québec)",
        help="Numéro d'identification de retenues à la source auprès de Revenu "
             "Québec (ex. 1234567890 RS0001). Sert à remettre l'impôt du Québec, "
             "le RRQ, le RQAP, le FSS et la cotisation des normes du travail.",
    )
