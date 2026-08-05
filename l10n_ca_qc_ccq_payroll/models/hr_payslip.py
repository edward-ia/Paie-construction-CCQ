from odoo import models


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

    def _ccq_conges(self):
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_ccq_conges')
        taux = p['conges_annuels'] + p['jours_feries'] + p['maladie']
        return round(self._ccq_salaire_cotisable() * taux, 2)

    def _ccq_base_hors_r20(self, gross):
        self.ensure_one()
        return max(0.0, round(gross - self._ccq_salaire_cotisable(), 2))

    def _l10n_ca_qc_vacances(self, gross):
        self.ensure_one()
        return super()._l10n_ca_qc_vacances(self._ccq_base_hors_r20(gross))

    def _l10n_ca_qc_normes_travail(self, gross):
        self.ensure_one()
        return super()._l10n_ca_qc_normes_travail(self._ccq_base_hors_r20(gross))
