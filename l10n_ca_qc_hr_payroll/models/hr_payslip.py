from odoo import models
from odoo.exceptions import UserError

# Nombre de périodes de paie par année, par fréquence.
# Les clés proviennent de hr.payroll.structure.type._get_selection_schedule_pay().
PERIODS_PER_YEAR = {
    'annually': 1,
    'semi-annually': 2,
    'quarterly': 4,
    'bi-monthly': 6,
    'monthly': 12,
    'semi-monthly': 24,
    'bi-weekly': 26,
    'weekly': 52,
    'daily': 260,
}


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    # ------------------------------------------------------------------
    # Bases de calcul
    # ------------------------------------------------------------------

    def _l10n_ca_qc_periods(self):
        """Nombre de périodes de paie dans l'année (le « P » du TP-1015.F)."""
        self.ensure_one()
        schedule = self.version_id.schedule_pay
        if schedule not in PERIODS_PER_YEAR:
            raise UserError(
                "Fréquence de paie « %s » non prise en charge par la paie du Québec."
                % (schedule or "non définie")
            )
        return PERIODS_PER_YEAR[schedule]

    def _l10n_ca_qc_basic(self):
        """Salaire brut de la période.

        Odoo stocke `wage` comme le montant PAR PÉRIODE DE PAIE et le reconvertit
        automatiquement quand on change la fréquence (55 000 $/an saisi en mode
        annuel devient 2 115,38 $ / 2 semaines dès qu'on passe en bi-weekly). Le
        brut de la période est donc `wage` tel quel — surtout PAS `wage / périodes`,
        sinon on divise deux fois. L'annualisation (× nombre de périodes) est faite
        là où il le faut, dans les formules d'impôt.
          - salaire fixe  : brut = wage ;
          - taux horaire  : (V2) brut = taux horaire × heures travaillées de la
                            période. À implémenter avec les jours travaillés.
        """
        self.ensure_one()
        version = self.version_id
        if version.wage_type == 'hourly':
            raise UserError(
                "La paie horaire sera prise en charge dans une version ultérieure "
                "(brut = taux horaire × heures travaillées de la période)."
            )
        return version.wage

    def _l10n_ca_qc_ytd(self, code):
        """Cumul annuel d'une ligne de paie, hors bulletin courant.

        Sert à plafonner les cotisations : dès que le maximum annuel est atteint,
        la retenue doit cesser. On n'utilise pas _sum() du moteur car il
        inclurait le bulletin courant s'il est déjà validé (recalcul).
        """
        self.ensure_one()
        self.env.cr.execute("""
            SELECT COALESCE(SUM(ABS(pl.total)), 0.0)
              FROM hr_payslip hp
              JOIN hr_payslip_line pl ON pl.slip_id = hp.id
             WHERE hp.employee_id = %s
               AND hp.state IN ('validated', 'paid')
               AND hp.id != %s
               AND hp.date_to >= %s
               AND hp.date_to <= %s
               AND pl.code = %s
        """, (
            self.employee_id.id,
            self.id or 0,
            self.date_to.replace(month=1, day=1),
            self.date_to,
            code,
        ))
        return self.env.cr.fetchone()[0]

    def _l10n_ca_qc_capped(self, amount, code, maximum):
        """Applique un plafond annuel à une cotisation.

        Retourne au plus ce qu'il reste avant d'atteindre le maximum de l'année,
        et zéro une fois le maximum atteint.
        """
        self.ensure_one()
        remaining = maximum - self._l10n_ca_qc_ytd(code)
        return max(0.0, min(amount, remaining))

    # ------------------------------------------------------------------
    # Cotisations sociales (part employé)
    # ------------------------------------------------------------------

    def _l10n_ca_qc_rrq(self, gross):
        """RRQ — cotisation de base + première cotisation supplémentaire (6,30 %)."""
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_rrq')
        periods = self._l10n_ca_qc_periods()
        # L'exemption de base annuelle est répartie sur les périodes de paie.
        cotisable = max(0.0, gross - p['exemption'] / periods)
        return round(self._l10n_ca_qc_capped(cotisable * p['taux'], 'RRQ', p['max']), 2)

    def _l10n_ca_qc_rrq2(self, gross):
        """RRQ2 — deuxième cotisation supplémentaire (4 % entre le MGA et le MSGA)."""
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_rrq2')
        periods = self._l10n_ca_qc_periods()
        # Ne s'applique qu'à la tranche de gains située au-dessus du MGA.
        gains_ytd = self._l10n_ca_qc_ytd('GROSS') + gross
        excess = max(0.0, min(gains_ytd, p['msga']) - p['mga'])
        # On ne cotise que sur la part de l'excédent gagnée dans la période.
        excess_before = max(0.0, min(gains_ytd - gross, p['msga']) - p['mga'])
        base = excess - excess_before
        return round(self._l10n_ca_qc_capped(base * p['taux'], 'RRQ2', p['max']), 2)

    def _l10n_ca_qc_rqap(self, gross):
        """RQAP — part employé."""
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_rqap')
        return round(self._l10n_ca_qc_capped(
            gross * p['taux_employe'], 'RQAP', p['max_employe']), 2)

    def _l10n_ca_qc_ae(self, gross):
        """Assurance-emploi — part employé, taux réduit du Québec."""
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_ae')
        return round(self._l10n_ca_qc_capped(
            gross * p['taux_employe'], 'AE', p['max_employe']), 2)

    # ------------------------------------------------------------------
    # Cotisations sociales (part employeur)
    # ------------------------------------------------------------------

    def _l10n_ca_qc_rrq_employeur(self, gross):
        """La part employeur du RRQ est le miroir de celle de l'employé."""
        self.ensure_one()
        return self._l10n_ca_qc_rrq(gross)

    def _l10n_ca_qc_rrq2_employeur(self, gross):
        self.ensure_one()
        return self._l10n_ca_qc_rrq2(gross)

    def _l10n_ca_qc_rqap_employeur(self, gross):
        """Part employeur du RQAP = part employé × (taux employeur / taux employé).

        Revenu Québec applique le rapport des taux (0,602 / 0,430 = 1,4) à la
        cotisation de l'employé DÉJÀ ARRONDIE — d'où l'appariement au cent avec
        WebRAS (le calcul direct gross × 0,602 % donne 1 ¢ de moins). Le plafond
        employeur reste cohérent car l'employé est déjà plafonné (620,06 = 442,90
        × 1,4).
        """
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_rqap')
        ratio = p['taux_employeur'] / p['taux_employe']
        return round(self._l10n_ca_qc_rqap(gross) * ratio, 2)

    def _l10n_ca_qc_ae_employeur(self, gross):
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_ae')
        return round(self._l10n_ca_qc_capped(
            gross * p['taux_employeur'], 'AE_EMP', p['max_employeur']), 2)

    def _l10n_ca_qc_fss(self, gross):
        """Fonds des services de santé — cotisation de l'employeur."""
        self.ensure_one()
        return round(gross * self._rule_parameter('l10n_ca_qc_fss'), 2)

    def _l10n_ca_qc_cnesst(self, gross):
        """Prime CNESST — taux propre à l'employeur, saisi sur la fiche société."""
        self.ensure_one()
        rate = self.company_id.l10n_ca_qc_cnesst_rate
        return round(gross * rate / 100.0, 2)

    def _l10n_ca_qc_normes_travail(self, gross):
        """Cotisation de l'employeur au financement des normes du travail.

        0,06 % de la rémunération assujettie, plafonnée à 103 000 $ de
        rémunération par employé et par an (2026) — soit une cotisation maximale
        de 61,80 $. La remise à Revenu Québec est annuelle (Sommaire 1,
        formulaire LE-39.0.2), mais on la provisionne à chaque paie via le cumul
        annuel pour que le sommaire employeur soit prêt sans recalcul. Le plafond
        porte sur la cotisation (max × 0,06 %), d'où l'appel à _l10n_ca_qc_capped.
        """
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_normes_travail')
        return round(self._l10n_ca_qc_capped(gross * p['taux'], 'CNT', p['max']), 2)

    def _l10n_ca_qc_anciennete_annees(self):
        """Années de service continu de l'employé à la fin de la période.

        Sert à choisir le taux d'indemnité de vacances (4 % avant 3 ans, 6 %
        ensuite). On lit la date d'entrée via `first_contract_date` ; getattr
        protège d'une éventuelle absence du champ (fallback : début de période
        → 0 an → 4 %).
        """
        self.ensure_one()
        start = getattr(self.employee_id, 'first_contract_date', False) or self.date_from
        return (self.date_to - start).days / 365.25

    def _l10n_ca_qc_vacances(self, gross):
        """Provision d'indemnité de vacances (congé annuel, norme du travail).

        4 % du brut avant 3 ans de service continu, 6 % à compter de 3 ans.
        ⚠️ Ce N'EST NI une retenue NI une remise à un gouvernement : c'est une
        somme DUE à l'employé, provisionnée à chaque paie et versée quand les
        vacances sont prises (elle devient alors un salaire imposable, soumis à
        toutes les retenues à ce moment-là). On ne l'impose donc pas ici et elle
        n'entre pas dans le net (règle en not_computed_in_net). À présenter
        SÉPARÉMENT des remises fiscales dans le sommaire employeur.
        """
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_vacances')
        rate = (p['taux_3_ans_plus']
                if self._l10n_ca_qc_anciennete_annees() >= p['seuil_annees']
                else p['taux_moins_3_ans'])
        return round(gross * rate, 2)

    # ------------------------------------------------------------------
    # Impôts
    # ------------------------------------------------------------------

    def _l10n_ca_qc_deductions_rpa(self):
        """Cotisations à un régime de pension agréé retenues sur la période.

        Elles se déduisent du revenu avant le calcul de l'impôt — le facteur F du
        T4127 au fédéral, la déduction correspondante du TP-1015.F au Québec —
        mais ne réduisent ni le salaire cotisable au RRQ, ni le salaire assurable
        à l'AE, ni celui du RQAP.

        Aucun régime de ce type n'existe dans la paie de base : le point d'entrée
        rend zéro et laisse les couches qui en portent un le renseigner.
        """
        self.ensure_one()
        return 0.0

    def _l10n_ca_qc_bracket(self, brackets, taxable):
        """Retourne (taux, constante K) du palier correspondant au revenu annuel.

        Les paliers sont des triplets (borne supérieure, taux, constante) ;
        la borne du dernier palier vaut None.
        """
        for ceiling, rate, constant in brackets:
            if ceiling is None or taxable <= ceiling:
                return rate, constant
        return brackets[-1][1], brackets[-1][2]

    def _l10n_ca_qc_impot_qc(self, gross):
        """Impôt du Québec retenu à la source (méthode TP-1015.F).

        L'impôt n'est pas un pourcentage de la paie : le revenu de la période est
        annualisé, imposé, puis l'impôt annuel est redivisé par le nombre de
        périodes. La première cotisation supplémentaire au RRQ (portion 1 %) et le
        RRQ2 sont déductibles du revenu imposable — comme au fédéral. Les omettre
        surestime l'impôt (validé au cent contre WebRAS).

        Les cotisations sont recalculées ici plutôt que reçues des autres règles :
        en Odoo 19 le dict `rules` renvoie 0 dans amount_python_compute, ce qui
        rendait la déduction silencieusement nulle.
        """
        self.ensure_one()
        periods = self._l10n_ca_qc_periods()
        brackets = self._rule_parameter('l10n_ca_qc_impot_paliers')
        worker = self._rule_parameter('l10n_ca_qc_deduction_travailleur')
        base_amount = self._rule_parameter('l10n_ca_qc_montant_base')
        rrq_param = self._rule_parameter('l10n_ca_qc_rrq')

        rrq = self._l10n_ca_qc_rrq(gross)
        rrq2 = self._l10n_ca_qc_rrq2(gross)

        annual = gross * periods
        # Déduction pour travailleur : un pourcentage du revenu, plafonné.
        deduction = min(annual * worker['taux'], worker['max'])
        # Part déductible du RRQ : la première cotisation supplémentaire (1 %) et
        # le RRQ2. La cotisation de base n'est PAS déductible (elle donne un crédit).
        rrq_additional = rrq * (rrq_param['taux_supplementaire'] / rrq_param['taux'])
        rrq_deductible = (rrq_additional + rrq2) * periods
        rpa = self._l10n_ca_qc_deductions_rpa() * periods
        taxable = max(0.0, annual - deduction - rrq_deductible - rpa)

        rate, constant = self._l10n_ca_qc_bracket(brackets, taxable)
        # Le montant personnel de base est un crédit, converti au taux du
        # premier palier.
        credit = base_amount * brackets[0][1]
        annual_tax = max(0.0, taxable * rate - constant - credit)
        return round(annual_tax / periods, 2)

    def _l10n_ca_qc_impot_fed(self, gross):
        """Impôt fédéral retenu à la source (méthode T4127), abattement du Québec inclus.

        Les cotisations supplémentaires au RRQ (1 % et 4 %) sont déductibles du
        revenu, tandis que la cotisation de base, le RQAP et l'AE donnent un
        crédit (K2). Confondre les deux fausse le résultat.

        Les cotisations sont recalculées ici (et non reçues des autres règles) :
        en Odoo 19 le dict `rules` renvoie 0 dans amount_python_compute, ce qui
        annulait silencieusement le crédit K2.
        """
        self.ensure_one()
        periods = self._l10n_ca_qc_periods()
        brackets = self._rule_parameter('l10n_ca_fed_paliers')
        base_amount = self._rule_parameter('l10n_ca_fed_montant_base')
        cea = self._rule_parameter('l10n_ca_fed_montant_emploi')
        abatement = self._rule_parameter('l10n_ca_fed_abattement_qc')
        rrq_param = self._rule_parameter('l10n_ca_qc_rrq')
        rqap_param = self._rule_parameter('l10n_ca_qc_rqap')
        ae_param = self._rule_parameter('l10n_ca_qc_ae')

        rrq = self._l10n_ca_qc_rrq(gross)
        rrq2 = self._l10n_ca_qc_rrq2(gross)

        lowest_rate = brackets[0][1]
        gross_annual = gross * periods

        # DÉDUCTION du revenu : la 1re cotisation supplémentaire au RRQ (1 %) et le
        # RRQ2, tels que RETENUS CETTE PÉRIODE (annualisés). Post-plafond, le RRQ de
        # base tombe à 0 donc la part 1 % aussi ; il ne reste que le RRQ2 — conforme
        # à PDOC (la déduction suit la cotisation réelle de la période).
        rrq_additional = rrq * (rrq_param['taux_supplementaire'] / rrq_param['taux'])
        rpa = self._l10n_ca_qc_deductions_rpa() * periods
        annual = max(0.0, gross_annual - (rrq_additional + rrq2) * periods - rpa)

        rate, constant = self._l10n_ca_qc_bracket(brackets, annual)

        # CRÉDIT K2 : la cotisation de BASE au RRQ, le RQAP et l'AE donnent un crédit,
        # calculé sur la cotisation ANNUELLE de l'employé = le taux appliqué au BRUT
        # ANNUALISÉ, plafonné au maximum. On NE se base PAS sur « cotisation de la
        # période × périodes » : une fois le plafond atteint en cours d'année, cette
        # cotisation tombe à 0 et le crédit disparaîtrait à tort (sur-retenue), alors
        # que l'employé a bel et bien versé le maximum sur l'année. Le crédit reste
        # donc stable période après période. Validé au cent contre PDOC/CDRP sur une
        # paie post-plafond (impôt fédéral 431,46 pour un salarié à 104 000 $).
        base_rate = rrq_param['taux'] - rrq_param['taux_supplementaire']
        rrq_base_max = rrq_param['max'] * (base_rate / rrq_param['taux'])
        rrq_base_annual = min(base_rate * max(0.0, gross_annual - rrq_param['exemption']), rrq_base_max)
        rqap_annual = min(rqap_param['taux_employe'] * gross_annual, rqap_param['max_employe'])
        ae_annual = min(ae_param['taux_employe'] * gross_annual, ae_param['max_employe'])

        k1 = base_amount * lowest_rate
        k2 = (rrq_base_annual + rqap_annual + ae_annual) * lowest_rate
        k4 = min(annual, cea) * lowest_rate

        tax = max(0.0, annual * rate - constant - k1 - k2 - k4)
        # Abattement du Québec : le fédéral réduit son impôt car le Québec
        # administre ses propres programmes.
        tax = tax * (1.0 - abatement)
        return round(tax / periods, 2)
