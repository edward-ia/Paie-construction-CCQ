from odoo import models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    """Rémunération des heures de chantier.

    Le brut d'un salarié assujetti à la loi R-20 ne se tape jamais : il se
    reconstitue à partir des feuilles de temps hebdomadaires, où chaque ligne
    porte déjà son taux de convention — lu dans la grille au croisement
    métier × secteur × annexe × période, à la date des travaux.

    Ce module ne recalcule AUCUNE retenue fiscale. L'impôt fédéral, l'impôt du
    Québec, le RRQ, le RRQ2, l'AE et le RQAP restent ceux du module de base,
    qui partent tous du brut de la période. En changeant la façon dont ce brut
    est établi, on alimente donc tout le reste sans y toucher, et la validation
    au cent près contre WebRAS et PDOC reste valable.
    """
    _inherit = 'hr.payslip'

    # ------------------------------------------------------------------
    # Heures de la période
    # ------------------------------------------------------------------

    def _ccq_lignes_temps(self):
        """Lignes de feuille de temps confirmées couvertes par le bulletin.

        Les feuilles restées en brouillon sont ignorées : une semaine non
        confirmée n'est pas une semaine payable. Un salarié non assujetti ne
        remonte rien — le personnel de bureau reste payé par le module de base.
        """
        self.ensure_one()
        Ligne = self.env['ccq.feuille.temps.ligne']
        if not self.employee_id.l10n_ca_qc_ccq_assujetti:
            return Ligne.browse()
        return Ligne.search([
            ('employee_id', '=', self.employee_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('feuille_id.state', '=', 'confirme'),
        ])

    def _ccq_remuneration(self, champ_heures, multiplicateur):
        """Somme de (heures × taux de la ligne × multiplicateur).

        Le taux est pris LIGNE PAR LIGNE, jamais globalement : un même salarié
        peut travailler la même semaine sur deux chantiers de secteurs ou
        d'annexes différents, donc à deux taux de convention différents. Un
        taux moyen produirait un brut faux et une remise fausse.
        """
        self.ensure_one()
        total = sum(
            ligne[champ_heures] * ligne.taux_horaire * multiplicateur
            for ligne in self._ccq_lignes_temps()
        )
        return round(total, 2)

    def _ccq_majorations(self):
        """Multiplicateurs d'heures supplémentaires, datés comme les barèmes."""
        self.ensure_one()
        return self._rule_parameter('l10n_ca_qc_ccq_heures_supp')

    def _ccq_lignes_assujetties(self):
        self.ensure_one()
        return self._ccq_lignes_temps().filtered('assujetti')

    def _ccq_primes(self):
        self.ensure_one()
        majorations = self._ccq_majorations()
        Prime = self.env['ccq.prime']
        total = 0.0
        for ligne in self._ccq_lignes_assujetties():
            for prime in ligne.prime_ids:
                version = Prime._version_applicable(prime, ligne.date)
                if not version:
                    continue
                unitaire = (version.valeur * ligne.taux_horaire
                            if version.mode == 'pourcentage' else version.valeur)
                heures = ligne.heures_regulieres
                if version.versee_heures_supp:
                    if version.majorable:
                        heures += (
                            ligne.heures_supp_50 * majorations['majoration_50']
                            + ligne.heures_supp_100 * majorations['majoration_100'])
                    else:
                        heures += ligne.heures_supp_50 + ligne.heures_supp_100
                total += unitaire * heures
        return round(total, 2)

    def _ccq_salaire_cotisable(self):
        self.ensure_one()
        majorations = self._ccq_majorations()
        total = sum(
            ligne.taux_horaire * (
                ligne.heures_regulieres
                + ligne.heures_supp_50 * majorations['majoration_50']
                + ligne.heures_supp_100 * majorations['majoration_100'])
            for ligne in self._ccq_lignes_assujetties()
        )
        return round(total + self._ccq_primes(), 2)

    # ------------------------------------------------------------------
    # Règles de paie
    # ------------------------------------------------------------------

    def _l10n_ca_qc_basic(self):
        """Brut des heures régulières, au taux simple de la convention.

        Pour un salarié non assujetti, on rend la main au module de base : son
        salaire fixe est calculé exactement comme avant.
        """
        self.ensure_one()
        if not self.employee_id.l10n_ca_qc_ccq_assujetti:
            return super()._l10n_ca_qc_basic()
        return self._ccq_remuneration('heures_regulieres', 1.0)

    def _ccq_heures_supp_50(self):
        """Heures majorées de 50 % — convention IC 2025-2029, article 21.02 a).

        Première heure supplémentaire DE LA SEMAINE, et non de la journée : la
        deuxième heure supplémentaire de la semaine est déjà à +100 %, même si
        elle tombe un autre jour. Sur chantier isolé, ce sont les cinq premières
        (art. 21.03 3) a), d'où `heures_supp_a_taux_simple` sur l'annexe).
        La majoration s'ajoute à l'heure elle-même : l'heure est donc payée
        1,5 fois le taux, pas 0,5.

        ⚠️ Article 22.01 : la rémunération des heures supplémentaires est
        établie AVANT l'ajout des primes. Le multiplicateur ne s'applique donc
        pas aux primes, sauf celles de l'article 22.03 (chef d'équipe et chef
        de groupe). Les primes sont ajoutées par la règle CCQ_PRIMES.
        """
        self.ensure_one()
        return self._ccq_remuneration(
            'heures_supp_50', self._ccq_majorations()['majoration_50'])

    def _ccq_heures_supp_100(self):
        """Heures majorées de 100 % — convention IC 2025-2029, section XXI.

        À compter de la deuxième heure supplémentaire, et dès la première le
        dimanche et les jours fériés chômés.
        """
        self.ensure_one()
        return self._ccq_remuneration(
            'heures_supp_100', self._ccq_majorations()['majoration_100'])

    def _ccq_taux_conges(self):
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_ccq_conges')
        return p['conges_annuels'] + p['jours_feries'] + p['maladie']

    def _ccq_conges(self):
        self.ensure_one()
        return round(self._ccq_salaire_cotisable() * self._ccq_taux_conges(), 2)

    # ------------------------------------------------------------------
    # Avantages sociaux — part précomptée sur le salaire
    # ------------------------------------------------------------------

    def _ccq_cotisation_horaire(self, ligne, caisse, payeur, facteur_conges):
        """Cotisation due pour une heure travaillée sur cette ligne d'heures.

        Lue ligne par ligne comme le taux de salaire : la règle particulière du
        métier et le pourcentage du taux de convention se lisent tous deux au
        croisement que porte la ligne, jamais sur une moyenne de la semaine.
        """
        self.ensure_one()
        cotisation = self.env['ccq.avantage.social']._cotisation_applicable(
            ligne.metier_id, caisse, payeur, ligne.periode, ligne.date)
        if not cotisation:
            raise UserError(
                "Aucune cotisation d'avantages sociaux n'est définie pour la caisse "
                "« %s », part « %s », métier %s, au %s."
                % (caisse, payeur,
                   ligne.metier_id.display_name or "non défini", ligne.date)
            )
        return cotisation._montant_horaire(ligne.taux_horaire, facteur_conges)

    def _ccq_avantages_sociaux(self, caisse, payeur):
        """Somme de (heures travaillées × cotisation horaire) sur la période.

        « Pour chaque heure de travail » (R-20, r. 10, article 13) : les heures
        supplémentaires comptent une pour une. La majoration rémunère l'heure,
        elle n'en crée pas une seconde — et le pourcentage de la règle
        particulière porte sur le taux RÉGULIER, non majoré.
        """
        self.ensure_one()
        facteur_conges = 1.0 + self._ccq_taux_conges()
        total = sum(
            ligne.total_heures
            * self._ccq_cotisation_horaire(ligne, caisse, payeur, facteur_conges)
            for ligne in self._ccq_lignes_assujetties()
        )
        return round(total, 2)

    def _ccq_av_soc_prevoyance(self):
        self.ensure_one()
        return self._ccq_avantages_sociaux('prevoyance', 'salarie')

    def _ccq_av_soc_taxe(self):
        """Taxe de vente sur l'assurance, sur la seule part de prévoyance.

        La caisse de retraite n'est pas de l'assurance : elle n'est pas taxée.
        """
        self.ensure_one()
        taux = self._rule_parameter('l10n_ca_qc_ccq_taxe_assurance')
        return round(self._ccq_av_soc_prevoyance() * taux, 2)

    def _ccq_av_soc_retraite(self):
        self.ensure_one()
        return self._ccq_avantages_sociaux('retraite', 'salarie')

    def _l10n_ca_qc_deductions_rpa(self):
        """La cotisation à la caisse de retraite réduit le revenu imposable.

        C'est un régime de pension agréé : la retenue se déduit du revenu avant
        le calcul de l'impôt, au fédéral comme au Québec. La cotisation à la
        caisse de prévoyance finance une assurance maladie (R-20, r. 10,
        article 11) et ne se déduit pas.
        """
        self.ensure_one()
        if not self.employee_id.l10n_ca_qc_ccq_assujetti:
            return super()._l10n_ca_qc_deductions_rpa()
        return self._ccq_av_soc_retraite()

    # ------------------------------------------------------------------
    # Prélèvement et fonds sectoriels
    # ------------------------------------------------------------------

    def _ccq_heures_travaillees(self):
        """Heures travaillées assujetties de la période, sans majoration.

        Les fonds se cotisent « pour chaque heure travaillée » : une heure
        supplémentaire est une heure, quel que soit le taux auquel elle est payée.
        Ces heures viennent des feuilles de temps confirmées, jamais du calendrier
        du contrat, qui ignore où et pour qui le salarié a travaillé.
        """
        self.ensure_one()
        return sum(self._ccq_lignes_assujetties().mapped('total_heures'))

    def _ccq_prelevement(self, part):
        """Prélèvement de la CCQ — R-20, r. 9, article 1.

        L'assiette est la RÉMUNÉRATION VERSÉE, donc le salaire cotisable SANS
        l'indemnité de 13 % : le règlement dit « rémunération » là où la loi
        distingue, à son article 1 q), la « rémunération en monnaie courante » des
        « indemnités ». L'y inclure serait au surplus circulaire, le 13 % étant
        calculé sur ce même salaire cotisable.

        Le minimum de 10 $ par période mensuelle du deuxième alinéa n'apparaît pas
        ici : il ne vise que l'employeur et l'entrepreneur autonome, jamais la
        retenue salariale, et se règle au rapport mensuel — un bulletin
        hebdomadaire ne peut pas décider d'un plancher mensuel.
        """
        self.ensure_one()
        taux = self._rule_parameter('l10n_ca_qc_ccq_prelevement')[part]
        return round(self._ccq_salaire_cotisable() * taux, 2)

    def _ccq_prelevement_salarie(self):
        self.ensure_one()
        return self._ccq_prelevement('taux_salarie')

    def _ccq_prelevement_employeur(self):
        self.ensure_one()
        return self._ccq_prelevement('taux_employeur')

    def _ccq_fonds_formation(self):
        """Fonds de formation — R-20, r. 7.1, articles 3 et 5.

        Aucune exclusion d'assiette, contrairement au fonds d'indemnisation : la
        cotisation est due « pour chaque heure travaillée par chacun de ses
        salariés », propriétaires et actionnaires compris.

        Le secteur ne change pas le montant. L'article 5, deuxième alinéa, dit
        seulement que la Commission « porte ces cotisations au volet »
        correspondant : il décide de la destination, pas du taux.
        """
        self.ensure_one()
        taux = self._rule_parameter('l10n_ca_qc_ccq_fonds_formation')
        return round(self._ccq_heures_travaillees() * taux, 2)

    def _ccq_fonds_indemnisation(self):
        """Fonds d'indemnisation — R-20, r. 7.01, article 4.

        Entièrement patronal : l'article 3 n'alimente le fonds que des cotisations
        versées par un employeur, aucune cotisation salariale n'existe.

        L'assiette exclut les personnes visées au deuxième alinéa de l'article 8,
        situation ordinaire d'une entreprise de construction dont un propriétaire
        travaille sur les chantiers.
        """
        self.ensure_one()
        if self.employee_id.l10n_ca_qc_ccq_exclu_fonds_indemnisation:
            return 0.0
        taux = self._rule_parameter('l10n_ca_qc_ccq_fonds_indemnisation')
        return round(self._ccq_heures_travaillees() * taux, 2)

    # ------------------------------------------------------------------
    # Assiettes rendues au module de base
    # ------------------------------------------------------------------

    def _ccq_base_hors_r20(self, gross):
        self.ensure_one()
        return max(0.0, round(gross - self._ccq_salaire_cotisable(), 2))

    def _l10n_ca_qc_vacances(self, gross):
        self.ensure_one()
        return super()._l10n_ca_qc_vacances(self._ccq_base_hors_r20(gross))

    def _l10n_ca_qc_normes_travail(self, gross):
        self.ensure_one()
        return super()._l10n_ca_qc_normes_travail(self._ccq_base_hors_r20(gross))
