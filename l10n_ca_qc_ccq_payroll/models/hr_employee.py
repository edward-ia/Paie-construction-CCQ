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

from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .ccq_referentiel import PERIODE_SELECTION, STATUT_SELECTION

DELAI_ALERTE_CERTIFICAT = 60
RESUME_ALERTE_CERTIFICAT = "Certificat de compétence CCQ à renouveler"


def _nas_valide(numero):
    """Clé de contrôle du numéro d'assurance sociale : neuf chiffres, Luhn.

    Le rapport mensuel identifie la personne salariée par son NAS ou son numéro
    de client, et une identification erronée fait rejeter la ligne, qui n'est
    pas comptabilisée jusqu'à correction. Un chiffre de trop se voit ici plutôt
    que six semaines plus tard, dans un avis de la Commission.
    """
    if len(numero) != 9:
        return False
    somme = 0
    for rang, chiffre in enumerate(reversed(numero)):
        valeur = int(chiffre)
        if rang % 2:
            valeur *= 2
            if valeur > 9:
                valeur -= 9
        somme += valeur
    return somme % 10 == 0


def _verifier_nas(nom, assujetti, ssnid):
    if not (assujetti and ssnid):
        return
    chiffres = ''.join(c for c in ssnid if c.isdigit())
    if not _nas_valide(chiffres):
        raise ValidationError(
            "Le numéro d'assurance sociale de « %s » compte %s chiffre(s) et ne "
            "passe pas la clé de contrôle. Le rapport mensuel identifie la personne "
            "salariée par son NAS ou son numéro de client, et une identification "
            "erronée fait rejeter la ligne." % (nom, len(chiffres))
        )


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
    l10n_ca_qc_ccq_exclu_fonds_indemnisation = fields.Boolean(
        string="Exclu du fonds d'indemnisation",
        help="L'employeur ne verse pas la cotisation au fonds d'indemnisation sur les "
             "heures des personnes visées au deuxième alinéa de l'article 8 du chapitre "
             "R-20, r. 7.01 : membre, administrateur ou dirigeant de la société ; "
             "actionnaire détenant 20 % ou plus des actions avec droit de vote ; "
             "répondant d'une licence de la Régie du bâtiment ; représentant désigné ; "
             "et le conjoint ou le parent en ligne directe de l'une de ces personnes. "
             "La cotisation au fonds de formation, elle, reste due sur ces mêmes heures.",
    )
    l10n_ca_qc_ccq_carte_competence = fields.Char(
        string="Certificat de compétence",
        help="Numéro du certificat délivré par la CCQ.")
    l10n_ca_qc_ccq_carte_expiration = fields.Date(string="Échéance du certificat")
    l10n_ca_qc_ccq_carte_etat = fields.Selection(
        [('valide', "Valide"), ('bientot', "Échoit bientôt"), ('expire', "Échu")],
        string="État du certificat", compute='_compute_carte_etat', store=True,
        help="Un certificat échu transfère à l'employeur les amendes que le salarié "
             "encourrait (convention institutionnel-commercial, article 4.05).",
    )

    @api.depends('l10n_ca_qc_ccq_carte_expiration')
    def _compute_carte_etat(self):
        aujourdhui = fields.Date.context_today(self)
        limite = aujourdhui + timedelta(days=DELAI_ALERTE_CERTIFICAT)
        for employee in self:
            echeance = employee.l10n_ca_qc_ccq_carte_expiration
            if not echeance:
                employee.l10n_ca_qc_ccq_carte_etat = False
            elif echeance < aujourdhui:
                employee.l10n_ca_qc_ccq_carte_etat = 'expire'
            elif echeance <= limite:
                employee.l10n_ca_qc_ccq_carte_etat = 'bientot'
            else:
                employee.l10n_ca_qc_ccq_carte_etat = 'valide'

    @api.model
    def _cron_alerte_certificat_competence(self):
        """Recalcule l'état des certificats et signale ceux qui approchent.

        Le champ est stocké pour rester filtrable, mais il dépend de la date du
        jour : sans ce passage quotidien, un certificat resterait « valide » à
        l'écran le lendemain de son échéance.

        L'activité n'est posée qu'une fois par salarié : on ne veut pas d'un
        rappel neuf chaque matin pendant deux mois.
        """
        employees = self.search([('l10n_ca_qc_ccq_carte_expiration', '!=', False)])
        employees._compute_carte_etat()
        a_signaler = employees.filtered(
            lambda e: e.l10n_ca_qc_ccq_carte_etat in ('bientot', 'expire'))
        if not a_signaler:
            return
        activite = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        modele = self.env['ir.model']._get_id('hr.employee')
        for employee in a_signaler:
            deja = self.env['mail.activity'].search_count([
                ('res_model_id', '=', modele),
                ('res_id', '=', employee.id),
                ('activity_type_id', '=', activite.id if activite else False),
                ('summary', '=', RESUME_ALERTE_CERTIFICAT),
            ])
            if deja:
                continue
            employee.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=employee.l10n_ca_qc_ccq_carte_expiration,
                summary=RESUME_ALERTE_CERTIFICAT,
                note="Le certificat de compétence de %s %s le %s. Sans certificat "
                     "valide, l'employeur répond des amendes encourues par le "
                     "salarié." % (
                         employee.name,
                         "a échu" if employee.l10n_ca_qc_ccq_carte_etat == 'expire'
                         else "échoit",
                         employee.l10n_ca_qc_ccq_carte_expiration),
                user_id=employee.parent_id.user_id.id or self.env.uid,
            )

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

    @api.constrains('l10n_ca_qc_ccq_assujetti')
    def _check_nas(self):
        for employee in self:
            _verifier_nas(employee.name, employee.l10n_ca_qc_ccq_assujetti,
                          employee.ssnid)


class HrVersion(models.Model):
    _inherit = 'hr.version'

    @api.constrains('ssnid')
    def _check_nas_ccq(self):
        """Le NAS vit ici, pas sur l'employé.

        En Odoo 19, `hr.employee.ssnid` est un related NON STOCKÉ vers
        `hr.version`. Une contrainte posée sur l'employé ne se déclencherait
        jamais à l'écriture : Odoo n'évalue les contraintes que sur les champs
        stockés du modèle écrit.
        """
        for version in self:
            employee = version.employee_id
            _verifier_nas(employee.name, employee.l10n_ca_qc_ccq_assujetti,
                          version.ssnid)
