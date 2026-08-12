"""Feuille de temps hebdomadaire — le cœur du modèle.

Presque rien, dans la paie de la construction, n'est une propriété du salarié :
tout est une propriété de L'HEURE TRAVAILLÉE — quand, où, dans quel secteur, à
quel titre. C'est pourquoi la ligne d'heures est le vrai centre du module. Si elle
ne porte pas ses dimensions dès la saisie, ni la ventilation des taux ni le
rapport mensuel ne sont récupérables, et il faut tout refaire.

LE REGISTRE EST UNE OBLIGATION DISTINCTE DE LA PAIE. La loi exige l'heure précise
à laquelle le travail a commencé, a été interrompu, repris et achevé chaque jour
(R-20 article 82 a) et `r. 11` article 8 paragraphe 3°), ainsi que la ventilation
des heures par chantier ET par donneur d'ouvrage. Ces heures-là ne servent à
aucun calcul : elles servent à répondre à une inspection. Un registre absent,
altéré ou faux se punit de 15 000 à 150 000 $ pour une personne morale
(R-20 article 122.4), et la prescription de douze mois ne court même pas.

LA SEMAINE EST IMPOSÉE par la CCQ : du dimanche 0 h 01 au samedi 24 h
(`r. 11` article 12 alinéa 4). La période
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
        help="La semaine CCQ va du dimanche 0 h 01 au samedi 24 h.")
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

    heure_debut = fields.Float(
        string="Début", digits=(4, 2),
        help="Heure à laquelle le travail a commencé, en heures décimales : 7,5 = 7 h 30. "
             "Exigée au registre par la loi R-20, article 82 a).")
    heure_fin = fields.Float(
        string="Fin", digits=(4, 2),
        help="Heure à laquelle le travail s'est achevé. Une heure de fin antérieure à "
             "l'heure de début se lit comme un quart terminé après minuit.")
    interruption_ids = fields.One2many(
        'ccq.feuille.temps.interruption', 'ligne_id', string="Interruptions",
        help="Repas et arrêts de la journée. Le règlement exige l'heure d'interruption "
             "ET de reprise, et une journée peut en compter plusieurs.")
    heures_registre = fields.Float(
        string="Heures au registre", compute='_compute_heures_registre',
        store=True, digits=(8, 2),
        help="Temps écoulé entre le début et la fin, moins les interruptions.")
    ecart_registre = fields.Float(
        string="Écart", compute='_compute_heures_registre', store=True, digits=(8, 2),
        help="Heures du registre moins heures déclarées. Un écart n'empêche ni la paie "
             "ni la déclaration : il signale une saisie à revoir.")

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

    @api.depends('heure_debut', 'heure_fin', 'interruption_ids.duree', 'total_heures')
    def _compute_heures_registre(self):
        """Durée du quart, interruptions déduites.

        Une heure de fin inférieure à l'heure de début désigne le lendemain : un
        quart de 22 h à 6 h dure huit heures et reste attaché au jour où il a
        commencé, comme le veut la déclaration par journée.
        """
        for ligne in self:
            registre = 0.0
            if ligne.heure_debut or ligne.heure_fin:
                fin = ligne.heure_fin + 24.0 if ligne.heure_fin <= ligne.heure_debut \
                    else ligne.heure_fin
                registre = fin - ligne.heure_debut - sum(
                    ligne.interruption_ids.mapped('duree'))
            ligne.heures_registre = round(registre, 2)
            ligne.ecart_registre = round(registre - ligne.total_heures, 2) if registre else 0.0

    @api.constrains('heure_debut', 'heure_fin', 'interruption_ids')
    def _check_registre(self):
        for ligne in self:
            for heure in (ligne.heure_debut, ligne.heure_fin):
                if not 0.0 <= heure < 24.0:
                    raise ValidationError(
                        "Une heure du registre doit être comprise entre 0 et 24. "
                        "Saisissez 7,5 pour 7 h 30."
                    )
            if ligne.heures_registre < 0:
                raise ValidationError(
                    "Les interruptions du %s durent plus longtemps que le quart de "
                    "travail lui-même." % ligne.date
                )

    @api.constrains('assujetti', 'heure_debut', 'heure_fin', 'total_heures')
    def _check_registre_renseigne(self):
        """Une heure de chantier sans horaire est un registre incomplet.

        On bloque à la saisie : reconstituer des heures de début et de fin un an
        plus tard, devant un inspecteur, n'est pas possible.
        """
        for ligne in self:
            if ligne.assujetti and ligne.total_heures and not (
                    ligne.heure_debut or ligne.heure_fin):
                raise ValidationError(
                    "Le registre exige l'heure de début et de fin du travail. "
                    "Renseignez-les sur la ligne du %s pour %s."
                    % (ligne.date, ligne.employee_id.name or "ce salarié")
                )

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

    @api.constrains('assujetti', 'chantier_id')
    def _check_donneur_ouvrage(self):
        """Le registre ventile les heures par chantier ET par donneur d'ouvrage.

        Le donneur d'ouvrage est porté par le chantier, un chantier étant
        « l'ensemble des travaux effectués par un employeur pour un même projet »
        (`r. 11` article 8) : un projet a un seul donneur d'ouvrage, et ventiler
        par chantier ventile donc par donneur d'ouvrage.
        """
        for ligne in self:
            if ligne.assujetti and not ligne.chantier_id.partner_id:
                raise ValidationError(
                    "Le chantier « %s » n'a pas de donneur d'ouvrage. Le registre "
                    "exige les heures ventilées par chantier et par donneur "
                    "d'ouvrage." % ligne.chantier_id.name
                )

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


class CcqFeuilleTempsInterruption(models.Model):
    """Un arrêt de travail dans la journée, avec son heure de reprise.

    La loi énumère quatre moments à consigner — début, interruption, reprise et
    fin — et le fait « chaque jour ». Deux champs fixes sur la ligne d'heures ne
    couvriraient qu'un seul arrêt : une journée coupée par un repas et par une
    panne d'équipement en compte deux, et le registre doit les porter tous les
    deux.
    """

    _name = 'ccq.feuille.temps.interruption'
    _description = "CCQ — Interruption de travail"
    _order = 'ligne_id, heure_debut'

    ligne_id = fields.Many2one(
        'ccq.feuille.temps.ligne', string="Ligne d'heures", required=True,
        ondelete='cascade')
    motif = fields.Char(string="Motif", help="Repas, panne, intempéries…")
    heure_debut = fields.Float(
        string="Interruption", digits=(4, 2), required=True,
        help="Heure à laquelle le travail a été interrompu, en heures décimales.")
    heure_fin = fields.Float(
        string="Reprise", digits=(4, 2), required=True,
        help="Heure à laquelle le travail a repris.")
    duree = fields.Float(
        string="Durée", compute='_compute_duree', store=True, digits=(8, 2))

    @api.depends('heure_debut', 'heure_fin')
    def _compute_duree(self):
        for interruption in self:
            fin = interruption.heure_fin
            if fin <= interruption.heure_debut:
                fin += 24.0
            interruption.duree = round(fin - interruption.heure_debut, 2)

    @api.constrains('heure_debut', 'heure_fin')
    def _check_heures(self):
        for interruption in self:
            for heure in (interruption.heure_debut, interruption.heure_fin):
                if not 0.0 <= heure < 24.0:
                    raise ValidationError(
                        "Une heure d'interruption doit être comprise entre 0 et 24."
                    )
            if interruption.heure_debut == interruption.heure_fin:
                raise ValidationError(
                    "Une interruption qui reprend à l'heure où elle commence ne dure "
                    "rien : supprimez-la ou corrigez l'heure de reprise."
                )
