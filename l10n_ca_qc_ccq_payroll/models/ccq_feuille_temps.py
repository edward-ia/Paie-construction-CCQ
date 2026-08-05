"""Feuille de temps hebdomadaire — le cœur du modèle.

Presque rien, dans la paie de la construction, n'est une propriété du salarié :
tout est une propriété de L'HEURE TRAVAILLÉE — quand, où, dans quel secteur, à
quel titre. C'est pourquoi la ligne d'heures est le vrai centre du module. Si elle
ne porte pas ses dimensions dès la saisie, ni la ventilation des taux ni le
rapport mensuel ne sont récupérables, et il faut tout refaire.

LA SEMAINE EST IMPOSÉE par la CCQ : du dimanche 0 h 01 au samedi 0 h. La période
mensuelle regroupe quatre ou cinq de ces semaines et se termine le dernier samedi
du mois ; le rapport et le paiement sont dus au plus tard le 15 du mois suivant,
sous peine d'intérêts et de poursuite pénale. La paie est donc hebdomadaire, et
elle doit s'aligner sur ce découpage — pas sur celui d'Odoo.

LES DIMENSIONS SONT FIGÉES À LA LIGNE. Les champs de dimension et le taux sont
calculés depuis l'employé et le chantier, puis STOCKÉS. Deux conséquences
voulues : une progression d'apprentissage ne réécrit jamais une semaine passée,
et le commis peut forcer une valeur au cas par cas (`readonly=False`) sans devoir
créer un faux chantier — ce qui est exactement comme un rapport mensuel devient
faux dans la vraie vie.
"""

from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .ccq_referentiel import PERIODE_SELECTION, STATUT_SELECTION


class CcqFeuilleTemps(models.Model):
    _name = 'ccq.feuille.temps'
    _description = "CCQ — Feuille de temps hebdomadaire"
    _order = 'date_debut desc, employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string="Employé", required=True, ondelete='restrict')
    date_debut = fields.Date(
        string="Semaine du (dimanche)", required=True,
        help="La semaine CCQ va du dimanche 0 h 01 au samedi 0 h.")
    date_fin = fields.Date(
        string="au (samedi)", compute='_compute_date_fin', store=True)
    ligne_ids = fields.One2many(
        'ccq.feuille.temps.ligne', 'feuille_id', string="Heures")
    total_heures = fields.Float(
        string="Total des heures", compute='_compute_total_heures', store=True, digits=(8, 2))
    state = fields.Selection(
        [('brouillon', "Brouillon"), ('confirme', "Confirmée")],
        string="État", default='brouillon', required=True)
    company_id = fields.Many2one(
        'res.company', string="Société", required=True,
        default=lambda self: self.env.company)
    note = fields.Text(string="Notes")

    @api.depends('date_debut')
    def _compute_date_fin(self):
        for feuille in self:
            feuille.date_fin = (
                feuille.date_debut + timedelta(days=6) if feuille.date_debut else False)

    @api.depends('ligne_ids.total_heures')
    def _compute_total_heures(self):
        for feuille in self:
            feuille.total_heures = sum(feuille.ligne_ids.mapped('total_heures'))

    @api.depends('employee_id', 'date_debut')
    def _compute_display_name(self):
        for feuille in self:
            feuille.display_name = "%s — semaine du %s" % (
                feuille.employee_id.name or "?", feuille.date_debut or "?")

    @api.constrains('date_debut')
    def _check_debut_dimanche(self):
        """La semaine CCQ commence un dimanche — sinon tout le découpage dérape.

        weekday() vaut 6 pour le dimanche en Python.
        """
        for feuille in self:
            if feuille.date_debut and feuille.date_debut.weekday() != 6:
                raise ValidationError(
                    "La semaine CCQ commence un dimanche. Le %s est un %s."
                    % (feuille.date_debut, feuille.date_debut.strftime('%A'))
                )

    @api.constrains('employee_id', 'date_debut')
    def _check_unicite(self):
        for feuille in self:
            if self.search_count([
                ('employee_id', '=', feuille.employee_id.id),
                ('date_debut', '=', feuille.date_debut),
                ('id', '!=', feuille.id),
            ]):
                raise ValidationError(
                    "Une feuille de temps existe déjà pour %s sur la semaine du %s."
                    % (feuille.employee_id.name, feuille.date_debut)
                )

    def action_confirmer(self):
        self.write({'state': 'confirme'})

    def action_remettre_brouillon(self):
        self.write({'state': 'brouillon'})


class CcqFeuilleTempsLigne(models.Model):
    """Une ligne = un employé, un chantier, un jour.

    Le découpage au JOUR n'est pas cosmétique : les seuils d'heures
    supplémentaires de la convention sont à la fois quotidiens et hebdomadaires,
    et le rapport mensuel regroupe par combinaison de dimensions. Un total
    hebdomadaire par employé ne permettrait ni l'un ni l'autre. Une entreprise qui
    ne suit qu'un total par semaine saisit simplement une ligne unique.
    """

    _name = 'ccq.feuille.temps.ligne'
    _description = "CCQ — Ligne d'heures"
    _order = 'date, chantier_id'

    feuille_id = fields.Many2one(
        'ccq.feuille.temps', string="Feuille", required=True, ondelete='cascade')
    employee_id = fields.Many2one(
        'hr.employee', related='feuille_id.employee_id', store=True, string="Employé")
    date = fields.Date(string="Date", required=True)
    chantier_id = fields.Many2one(
        'ccq.chantier', string="Chantier", required=True, ondelete='restrict')

    heures_regulieres = fields.Float(string="Heures régulières", digits=(8, 2))
    heures_supp_50 = fields.Float(string="Heures à +50 %", digits=(8, 2))
    heures_supp_100 = fields.Float(string="Heures à +100 %", digits=(8, 2))
    total_heures = fields.Float(
        string="Total", compute='_compute_total_heures', store=True, digits=(8, 2))

    prime_ids = fields.Many2many(
        'ccq.prime', string="Primes applicables",
        help="Primes de convention déclenchées par les conditions de la journée "
             "(équipe de soir, chef d'équipe, masque à ventilation assistée…).",
    )
    distance_km = fields.Float(
        string="Distance domicile-chantier (km)", digits=(8, 2),
        help="Distance du trajet usuel entre l'adresse du domicile du salarié et "
             "celle du chantier. La convention désigne Google Maps comme arbitre en "
             "cas de désaccord ; la valeur est saisie pour rester vérifiable.",
    )
    chambre_pension = fields.Boolean(
        string="Chambre et pension",
        help="À cocher quand le salarié est logé plutôt qu'indemnisé au déplacement.")

    # ------------------------------------------------------------------
    # Dimensions figées — calculées depuis l'employé et le chantier, stockées,
    # et modifiables au cas par cas. Voir la docstring du module.
    # ------------------------------------------------------------------

    assujetti = fields.Boolean(
        string="Assujetti R-20", compute='_compute_dimensions', store=True, readonly=False,
        help="Vrai seulement si l'employé ET le chantier sont assujettis.")
    metier_id = fields.Many2one(
        'ccq.metier', string="Métier", compute='_compute_dimensions',
        store=True, readonly=False, ondelete='restrict')
    periode = fields.Selection(
        PERIODE_SELECTION, string="Période", compute='_compute_dimensions',
        store=True, readonly=False)
    statut = fields.Selection(
        STATUT_SELECTION, string="Statut", compute='_compute_dimensions',
        store=True, readonly=False)
    local_id = fields.Many2one(
        'ccq.local.syndical', string="Local syndical", compute='_compute_dimensions',
        store=True, readonly=False, ondelete='restrict')
    secteur_id = fields.Many2one(
        'ccq.secteur', string="Secteur", compute='_compute_dimensions',
        store=True, readonly=False, ondelete='restrict')
    annexe_id = fields.Many2one(
        'ccq.annexe', string="Annexe", compute='_compute_dimensions',
        store=True, readonly=False, ondelete='restrict')
    region_id = fields.Many2one(
        'ccq.region', string="Région", compute='_compute_dimensions',
        store=True, readonly=False, ondelete='restrict')
    taux_horaire = fields.Float(
        string="Taux horaire ($)", compute='_compute_taux_horaire',
        store=True, readonly=False, digits=(12, 4),
        help="Lu dans la grille de convention au croisement métier × secteur × annexe "
             "× période, à la date des travaux. Saisi manuellement pour les heures "
             "hors champ R-20, qui ne relèvent d'aucune grille.",
    )

    @api.depends('heures_regulieres', 'heures_supp_50', 'heures_supp_100')
    def _compute_total_heures(self):
        for ligne in self:
            ligne.total_heures = (
                ligne.heures_regulieres + ligne.heures_supp_50 + ligne.heures_supp_100)

    @api.depends('feuille_id.employee_id', 'chantier_id')
    def _compute_dimensions(self):
        """Reconstitue les sept dimensions à partir de l'employé et du chantier."""
        for ligne in self:
            employee = ligne.feuille_id.employee_id
            chantier = ligne.chantier_id
            ligne.assujetti = bool(
                employee.l10n_ca_qc_ccq_assujetti and chantier.assujetti)
            ligne.metier_id = employee.l10n_ca_qc_ccq_metier_id
            ligne.periode = employee.l10n_ca_qc_ccq_periode
            ligne.statut = employee.l10n_ca_qc_ccq_statut
            ligne.local_id = employee.l10n_ca_qc_ccq_local_id
            ligne.secteur_id = chantier.secteur_id
            ligne.annexe_id = chantier.annexe_id
            ligne.region_id = chantier.region_id

    @api.depends('assujetti', 'metier_id', 'secteur_id', 'annexe_id', 'periode', 'date')
    def _compute_taux_horaire(self):
        """Le salaire ne se tape jamais : il se lit dans la grille, à la date des travaux."""
        for ligne in self:
            taux = 0.0
            if (ligne.assujetti and ligne.metier_id and ligne.secteur_id
                    and ligne.annexe_id and ligne.periode and ligne.date):
                grille = self.env['ccq.taux.salaire']._taux_applicable(
                    ligne.metier_id, ligne.secteur_id, ligne.annexe_id,
                    ligne.periode, ligne.date)
                taux = grille.taux_horaire
            ligne.taux_horaire = taux

    @api.constrains('date', 'feuille_id')
    def _check_date_dans_semaine(self):
        for ligne in self:
            feuille = ligne.feuille_id
            if feuille.date_debut and feuille.date_fin and not (
                    feuille.date_debut <= ligne.date <= feuille.date_fin):
                raise ValidationError(
                    "La date %s ne tombe pas dans la semaine du %s au %s."
                    % (ligne.date, feuille.date_debut, feuille.date_fin)
                )

    @api.constrains('heures_regulieres', 'heures_supp_50', 'heures_supp_100')
    def _check_heures_positives(self):
        for ligne in self:
            if min(ligne.heures_regulieres, ligne.heures_supp_50, ligne.heures_supp_100) < 0:
                raise ValidationError("Les heures ne peuvent pas être négatives.")

    @api.constrains('assujetti', 'taux_horaire')
    def _check_taux_trouve(self):
        """Une ligne assujettie sans taux signale une grille manquante.

        Mieux vaut le voir à la saisie que découvrir un brut à zéro au moment de
        produire la paie de la semaine.
        """
        for ligne in self:
            if ligne.assujetti and ligne.total_heures and not ligne.taux_horaire:
                raise ValidationError(
                    "Aucun taux de convention trouvé pour %s (%s, %s, annexe %s) au %s. "
                    "Vérifiez la grille de taux."
                    % (ligne.employee_id.name,
                       ligne.metier_id.display_name or "métier non défini",
                       ligne.periode or "période non définie",
                       ligne.annexe_id.code or "?",
                       ligne.date)
                )
