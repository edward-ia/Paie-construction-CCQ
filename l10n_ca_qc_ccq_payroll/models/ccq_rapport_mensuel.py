"""Rapport mensuel à la Commission — la déclaration, pas la paie.

CE QUI SE DÉCLARE VIENT DE DEUX SOURCES, ET C'EST VOULU. Les heures et leurs
sept dimensions viennent des feuilles de temps ; les sommes à remettre viennent
des BULLETINS DE PAIE de la période. Recalculer les cotisations ici les ferait
diverger de ce qui a réellement été payé et retenu, et c'est exactement le genre
d'écart qu'une vérification de la Commission cherche. Le rapport ne recalcule
donc rien : il additionne.

LA PÉRIODE MENSUELLE N'EST PAS LE MOIS. Elle compte quatre ou cinq semaines
complètes, se termine le DERNIER SAMEDI du mois et commence le dimanche qui suit
le dernier samedi du mois précédent (`r. 11` article 12 alinéa 3). L'enchaînement
est ainsi sans trou ni chevauchement. Le rapport et le paiement sont dus au plus
tard le 15 du mois suivant.

TROIS OBLIGATIONS QUE SEULE LA PÉRIODE MENSUELLE PEUT TRANCHER y sont réglées,
parce qu'un bulletin hebdomadaire ne peut pas les décider : le minimum de 10 $ du
prélèvement patronal, le minimum de 5 $ de la cotisation à l'AECQ, et sa
cotisation annuelle de 240 $ payable avec le rapport d'octobre.

L'ENVOI RESTE MANUEL. Le rapport « doit être produit électroniquement par le
biais des services en ligne de la CCQ, ou par l'entremise d'un logiciel comptable
ou d'un service de paie AUTORISÉ » (PD5277 page 1). Tant que la Commission n'a
pas autorisé ce module et publié sa spécification de transmission, le document
produit ici sert à saisir la déclaration dans les services en ligne — un
imprimé ne vaut pas transmission.
"""

import calendar
from ast import literal_eval
from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .ccq_referentiel import CODE_PERIODE_CCQ, PERIODE_SELECTION, STATUT_SELECTION

MOIS_SELECTION = [
    ('1', "Janvier"), ('2', "Février"), ('3', "Mars"), ('4', "Avril"),
    ('5', "Mai"), ('6', "Juin"), ('7', "Juillet"), ('8', "Août"),
    ('9', "Septembre"), ('10', "Octobre"), ('11', "Novembre"), ('12', "Décembre"),
]

CODES_SALARIE = {
    'prelevement': 'CCQ_PRELEVEMENT',
    'contribution_sectorielle': 'CCQ_CONTRIB_SECT',
    'assurance': 'CCQ_AS_PREVOYANCE',
    'taxe_assurance': 'CCQ_AS_TAXE',
    'retraite': 'CCQ_AS_RETRAITE',
    'frais_participation': 'CCQ_FRAIS_PARTICIPATION',
}

CODES_EMPLOYEUR = {
    'prelevement': 'CCQ_PRELEVEMENT_EMP',
    'contribution_sectorielle': 'CCQ_CONTRIB_SECT_EMP',
    'assurance': 'CCQ_AS_PREVOYANCE_EMP',
    'taxe_assurance': 'CCQ_AS_TAXE_EMP',
    'retraite': 'CCQ_AS_RETRAITE_EMP',
    'frais_participation': 'CCQ_FRAIS_PARTICIPATION_EMP',
    'formation': 'CCQ_FORMATION',
    'indemnisation': 'CCQ_INDEMNISATION',
    'associations_patronales': 'CCQ_ASSOC_PATRONALES',
    'conges': 'CCQ_CONGES',
}


def dernier_samedi(annee, mois):
    """Dernier samedi du mois — la fin de la période mensuelle de la CCQ."""
    dernier_jour = date(annee, mois, calendar.monthrange(annee, mois)[1])
    return dernier_jour - timedelta(days=(dernier_jour.weekday() - 5) % 7)


class CcqRapportMensuel(models.Model):
    _name = 'ccq.rapport.mensuel'
    _description = "CCQ — Rapport mensuel"
    _order = 'date_fin desc'

    name = fields.Char(string="Référence", compute='_compute_name', store=True)
    annee = fields.Integer(
        string="Année", required=True,
        default=lambda self: fields.Date.context_today(self).year)
    mois = fields.Selection(
        MOIS_SELECTION, string="Mois", required=True,
        default=lambda self: str(fields.Date.context_today(self).month))
    date_debut = fields.Date(
        string="Du", compute='_compute_periode', store=True,
        help="Dimanche qui suit le dernier samedi du mois précédent.")
    date_fin = fields.Date(
        string="Au", compute='_compute_periode', store=True,
        help="Dernier samedi du mois.")
    date_echeance = fields.Date(
        string="À transmettre au plus tard le", compute='_compute_periode', store=True,
        help="Le 15 du mois suivant la fin de la période. Passé ce jour, la Commission "
             "réclame des intérêts quotidiens et peut engager une poursuite pénale.")

    state = fields.Selection(
        [('brouillon', "Brouillon"), ('calcule', "Calculé"), ('transmis', "Transmis")],
        string="État", default='brouillon', required=True)
    inactif = fields.Boolean(
        string="Avis d'inactivité", compute='_compute_totaux', store=True,
        help="Aucune heure déclarable dans la période. Le rapport doit être transmis "
             "quand même : un mois sans travaux se déclare.")

    ligne_ids = fields.One2many(
        'ccq.rapport.mensuel.ligne', 'rapport_id', string="Déclarations")
    payslip_ids = fields.Many2many(
        'hr.payslip', string="Bulletins de la période", readonly=True,
        help="Bulletins terminés dont la période tombe entièrement dans celle du "
             "rapport. Les sommes à remettre en sont extraites, jamais recalculées.")

    total_heures = fields.Float(
        string="Heures déclarées", compute='_compute_totaux', store=True, digits=(10, 2))
    total_salaire = fields.Monetary(
        string="Salaire cotisable", compute='_compute_totaux', store=True)
    nb_salaries = fields.Integer(
        string="Salariés déclarés", compute='_compute_totaux', store=True)

    montant_prelevement = fields.Monetary(
        string="Prélèvement", compute='_compute_totaux', store=True)
    montant_conges = fields.Monetary(
        string="Congés, fériés et maladie (13 %)", compute='_compute_totaux', store=True)
    montant_assurance = fields.Monetary(
        string="Caisses d'assurance", compute='_compute_totaux', store=True)
    montant_taxe_assurance = fields.Monetary(
        string="Taxe sur l'assurance", compute='_compute_totaux', store=True)
    montant_retraite = fields.Monetary(
        string="Caisse de retraite", compute='_compute_totaux', store=True)
    montant_contribution_sectorielle = fields.Monetary(
        string="Contribution sectorielle", compute='_compute_totaux', store=True)
    montant_formation = fields.Monetary(
        string="Fonds de formation", compute='_compute_totaux', store=True)
    montant_indemnisation = fields.Monetary(
        string="Fonds d'indemnisation", compute='_compute_totaux', store=True)
    montant_frais_participation = fields.Monetary(
        string="Frais de participation aux régimes", compute='_compute_totaux', store=True)
    montant_associations_patronales = fields.Monetary(
        string="Associations patronales", compute='_compute_totaux', store=True)
    montant_aecq_annuelle = fields.Monetary(
        string="Cotisation annuelle à l'AECQ", compute='_compute_totaux', store=True,
        help="240 $ payables en un seul versement, avec le rapport d'octobre.")
    total_a_remettre = fields.Monetary(
        string="Total à remettre", compute='_compute_totaux', store=True)

    ajustement_prelevement = fields.Monetary(
        string="Ajustement au minimum — prélèvement", compute='_compute_totaux', store=True,
        help="Complément porté au minimum de 10 $ par période mensuelle. Il ne vise que "
             "la part de l'employeur, jamais la retenue salariale.")
    ajustement_aecq = fields.Monetary(
        string="Ajustement au minimum — AECQ", compute='_compute_totaux', store=True,
        help="Complément porté au minimum de 5 $ par mois, dû même sans activité "
             "déclarée. Les parts sectorielles n'entrent pas dans ce minimum.")

    company_id = fields.Many2one(
        'res.company', string="Société", required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)
    note = fields.Text(string="Notes")

    @api.depends('annee', 'mois')
    def _compute_periode(self):
        for rapport in self:
            if not (rapport.annee and rapport.mois):
                rapport.date_debut = rapport.date_fin = rapport.date_echeance = False
                continue
            mois = int(rapport.mois)
            fin = dernier_samedi(rapport.annee, mois)
            precedent = date(rapport.annee, mois, 1) - timedelta(days=1)
            rapport.date_debut = dernier_samedi(
                precedent.year, precedent.month) + timedelta(days=1)
            rapport.date_fin = fin
            suivant = fin + timedelta(days=20)
            rapport.date_echeance = date(suivant.year, suivant.month, 15)

    @api.depends('annee', 'mois')
    def _compute_name(self):
        libelles = dict(MOIS_SELECTION)
        for rapport in self:
            rapport.name = "Rapport mensuel %s %s" % (
                libelles.get(rapport.mois, "?"), rapport.annee or "?")

    @api.depends('ligne_ids.total_heures', 'ligne_ids.salaire', 'payslip_ids',
                 'mois', 'date_fin')
    def _compute_totaux(self):
        for rapport in self:
            lignes = rapport.ligne_ids
            rapport.total_heures = sum(lignes.mapped('total_heures'))
            rapport.total_salaire = sum(lignes.mapped('salaire'))
            rapport.nb_salaries = len(lignes.mapped('employee_id'))
            rapport.inactif = not rapport.total_heures

            montants = rapport._montants_bulletins()
            parametres = rapport._parametres()

            prelevement = montants['prelevement']
            minimum = parametres['prelevement'].get('min_mensuel', 0.0)
            part_employeur = montants['prelevement_employeur']
            rapport.ajustement_prelevement = round(
                max(0.0, minimum - part_employeur), 2) if part_employeur else 0.0
            rapport.montant_prelevement = round(
                prelevement + rapport.ajustement_prelevement, 2)

            aecq = rapport._montant_aecq()
            minimum_aecq = parametres['associations'].get('min_mensuel', 0.0)
            rapport.ajustement_aecq = round(max(0.0, minimum_aecq - aecq), 2)
            rapport.montant_associations_patronales = round(
                montants['associations_patronales'] + rapport.ajustement_aecq, 2)
            rapport.montant_aecq_annuelle = (
                parametres['associations'].get('aecq_annuelle', 0.0)
                if int(rapport.mois or 0) == parametres['associations'].get(
                    'mois_cotisation_annuelle') else 0.0)

            rapport.montant_conges = montants['conges']
            rapport.montant_assurance = montants['assurance']
            rapport.montant_taxe_assurance = montants['taxe_assurance']
            rapport.montant_retraite = montants['retraite']
            rapport.montant_contribution_sectorielle = montants['contribution_sectorielle']
            rapport.montant_formation = montants['formation']
            rapport.montant_indemnisation = montants['indemnisation']
            rapport.montant_frais_participation = montants['frais_participation']

            rapport.total_a_remettre = round(
                rapport.montant_prelevement
                + rapport.montant_conges
                + rapport.montant_assurance
                + rapport.montant_taxe_assurance
                + rapport.montant_retraite
                + rapport.montant_contribution_sectorielle
                + rapport.montant_formation
                + rapport.montant_indemnisation
                + rapport.montant_frais_participation
                + rapport.montant_associations_patronales
                + rapport.montant_aecq_annuelle, 2)

    def _parametre(self, code):
        """Valeur d'un paramètre daté, lue à la fin de la période déclarée.

        La lecture passe par le modèle des valeurs plutôt que par le moteur de
        paie : celui-ci part toujours d'un bulletin, et un rapport mensuel n'en
        est pas un. Le millésime retenu est le dernier entré en vigueur au plus
        tard à la fin de la période — la même règle que pour un bulletin.
        """
        self.ensure_one()
        reference = self.date_fin or fields.Date.context_today(self)
        valeur = self.env['hr.rule.parameter.value'].search([
            ('rule_parameter_id.code', '=', code),
            ('date_from', '<=', reference),
        ], order='date_from desc', limit=1)
        if not valeur:
            return {}
        return literal_eval(valeur.parameter_value)

    def _parametres(self):
        self.ensure_one()
        return {
            'prelevement': self._parametre('l10n_ca_qc_ccq_prelevement'),
            'associations': self._parametre('l10n_ca_qc_ccq_associations_patronales'),
        }

    def _montants_bulletins(self):
        """Somme, par poste, des lignes des bulletins de la période.

        Les retenues salariales sont stockées négatives : on les ramène en
        valeur absolue, une remise n'étant jamais négative.
        """
        self.ensure_one()
        lignes = self.payslip_ids.line_ids
        totaux = {}
        for poste in set(CODES_SALARIE) | set(CODES_EMPLOYEUR):
            codes = [code for code in (CODES_SALARIE.get(poste),
                                       CODES_EMPLOYEUR.get(poste)) if code]
            totaux[poste] = round(sum(
                abs(ligne.total) for ligne in lignes if ligne.code in codes), 2)
        totaux['prelevement_employeur'] = round(sum(
            abs(ligne.total) for ligne in lignes
            if ligne.code == CODES_EMPLOYEUR['prelevement']), 2)
        return totaux

    def _montant_aecq(self):
        """Part commune de la cotisation patronale, seule visée par le minimum.

        Le minimum de 5 $ par mois ne porte que sur l'AECQ : les parts
        sectorielles de l'ACQ et de l'ACRGTQ n'y entrent pas (PD5277 page 5).
        La ligne du bulletin réunit les deux, d'où ce calcul à partir des heures.
        """
        self.ensure_one()
        taux = self._parametres()['associations'].get('aecq_horaire', 0.0)
        return round(self.total_heures * taux, 2)

    def action_calculer(self):
        """Reconstruit les déclarations et rattache les bulletins de la période."""
        for rapport in self:
            if rapport.state == 'transmis':
                raise UserError(
                    "Le rapport de %s a été transmis à la Commission. Remettez-le en "
                    "brouillon avant de le recalculer." % rapport.name
                )
            rapport.ligne_ids.unlink()
            rapport.payslip_ids = [(6, 0, rapport._bulletins_periode().ids)]
            self.env['ccq.rapport.mensuel.ligne'].create(rapport._valeurs_lignes())
            rapport.state = 'calcule'

    def action_transmettre(self):
        """Marque la déclaration comme transmise par les services en ligne."""
        for rapport in self:
            if rapport.state == 'brouillon':
                raise UserError(
                    "Calculez le rapport de %s avant de le marquer transmis." % rapport.name)
        self.write({'state': 'transmis'})

    def action_remettre_brouillon(self):
        self.write({'state': 'brouillon'})

    def _bulletins_periode(self):
        self.ensure_one()
        return self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('done', 'paid')),
            ('date_from', '>=', self.date_debut),
            ('date_to', '<=', self.date_fin),
        ])

    def _lignes_temps(self):
        self.ensure_one()
        return self.env['ccq.feuille.temps.ligne'].search([
            ('feuille_id.state', '=', 'confirme'),
            ('feuille_id.company_id', '=', self.company_id.id),
            ('date', '>=', self.date_debut),
            ('date', '<=', self.date_fin),
            ('assujetti', '=', True),
        ])

    def _valeurs_lignes(self):
        """Une déclaration par combinaison des sept dimensions.

        PD5277 page 2 impose une déclaration séparée par métier ET par période
        d'apprentissage dès que l'un ou l'autre change dans le mois ; le même
        raisonnement vaut pour le secteur, l'annexe et la région, qui commandent
        le taux et la destination des cotisations. Regrouper, c'est perdre la
        ventilation — et elle est irrécupérable une fois le mois clos.
        """
        self.ensure_one()
        groupes = {}
        for ligne in self._lignes_temps():
            cle = (
                ligne.employee_id.id, ligne.metier_id.id, ligne.periode,
                ligne.statut or False, ligne.secteur_id.id, ligne.annexe_id.id,
                ligne.region_id.id,
            )
            groupe = groupes.setdefault(cle, {
                'rapport_id': self.id,
                'employee_id': ligne.employee_id.id,
                'metier_id': ligne.metier_id.id,
                'periode': ligne.periode,
                'statut': ligne.statut or False,
                'secteur_id': ligne.secteur_id.id,
                'annexe_id': ligne.annexe_id.id,
                'region_id': ligne.region_id.id,
                'heures_regulieres': 0.0,
                'heures_supp_50': 0.0,
                'heures_supp_100': 0.0,
                'salaire': 0.0,
                'semaines': set(),
            })
            groupe['heures_regulieres'] += ligne.heures_regulieres
            groupe['heures_supp_50'] += ligne.heures_supp_50
            groupe['heures_supp_100'] += ligne.heures_supp_100
            groupe['salaire'] += ligne.taux_horaire * ligne.total_heures
            if ligne.total_heures:
                groupe['semaines'].add(ligne.feuille_id.id)
        valeurs = []
        for groupe in groupes.values():
            groupe['semaines_travaillees'] = len(groupe.pop('semaines'))
            groupe['salaire'] = round(groupe['salaire'], 2)
            valeurs.append(groupe)
        return valeurs

    @api.constrains('annee', 'mois', 'company_id')
    def _check_unicite(self):
        for rapport in self:
            if self.search_count([
                ('annee', '=', rapport.annee),
                ('mois', '=', rapport.mois),
                ('company_id', '=', rapport.company_id.id),
                ('id', '!=', rapport.id),
            ]):
                raise ValidationError(
                    "Un rapport mensuel existe déjà pour %s." % rapport.name)


class CcqRapportMensuelLigne(models.Model):
    """Une déclaration : un salarié, une combinaison de dimensions, des heures."""

    _name = 'ccq.rapport.mensuel.ligne'
    _description = "CCQ — Déclaration au rapport mensuel"
    _order = 'employee_id, metier_id'

    rapport_id = fields.Many2one(
        'ccq.rapport.mensuel', string="Rapport", required=True, ondelete='cascade')
    employee_id = fields.Many2one(
        'hr.employee', string="Salarié", required=True, ondelete='restrict')
    identifiant = fields.Char(
        string="Identification", compute='_compute_identifiant',
        help="Numéro de client CCQ ou, à défaut, numéro d'assurance sociale. Une "
             "erreur d'identification fait rejeter la ligne, qui n'est pas "
             "comptabilisée jusqu'à correction.")
    metier_id = fields.Many2one('ccq.metier', string="Métier", ondelete='restrict')
    periode = fields.Selection(PERIODE_SELECTION, string="Période")
    code_periode = fields.Char(
        string="Code de période", compute='_compute_code_periode',
        help="Ce que porte la déclaration : le rang de la période pour un "
             "apprenti, « C » pour un compagnon, « O » pour une occupation.")
    statut = fields.Selection(STATUT_SELECTION, string="Statut")
    secteur_id = fields.Many2one('ccq.secteur', string="Secteur", ondelete='restrict')
    annexe_id = fields.Many2one('ccq.annexe', string="Annexe", ondelete='restrict')
    region_id = fields.Many2one('ccq.region', string="Région", ondelete='restrict')

    heures_regulieres = fields.Float(string="Heures régulières", digits=(10, 2))
    heures_supp_50 = fields.Float(string="Heures à +50 %", digits=(10, 2))
    heures_supp_100 = fields.Float(string="Heures à +100 %", digits=(10, 2))
    total_heures = fields.Float(
        string="Total des heures", compute='_compute_total_heures',
        store=True, digits=(10, 2))
    salaire = fields.Monetary(string="Salaire")
    semaines_travaillees = fields.Integer(
        string="Semaines travaillées",
        help="Nombre de semaines comportant au moins une heure. Une fraction de "
             "semaine compte pour une semaine complète.")

    currency_id = fields.Many2one(
        'res.currency', related='rapport_id.currency_id', readonly=True)

    @api.depends('heures_regulieres', 'heures_supp_50', 'heures_supp_100')
    def _compute_total_heures(self):
        for ligne in self:
            ligne.total_heures = (
                ligne.heures_regulieres + ligne.heures_supp_50 + ligne.heures_supp_100)

    @api.depends('periode')
    def _compute_code_periode(self):
        for ligne in self:
            ligne.code_periode = CODE_PERIODE_CCQ.get(ligne.periode, '')

    @api.depends('employee_id')
    def _compute_identifiant(self):
        for ligne in self:
            employee = ligne.employee_id
            ligne.identifiant = (
                employee.l10n_ca_qc_ccq_carte_competence or employee.ssnid or "")
