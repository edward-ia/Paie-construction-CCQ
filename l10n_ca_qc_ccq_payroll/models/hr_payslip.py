from odoo import models
from odoo.exceptions import UserError

from .ccq_referentiel import (
    STATUTS_AVEC_FRAIS_PARTICIPATION,
    STATUTS_SANS_ASSOCIATIONS_PATRONALES,
    STATUTS_SANS_ASSURANCE,
    STATUTS_SANS_CONGES,
    STATUTS_SANS_CONTRIBUTION_SECTORIELLE,
    STATUTS_SANS_FONDS_FORMATION,
    STATUTS_SANS_FONDS_INDEMNISATION,
    STATUTS_SANS_PRELEVEMENT,
    STATUTS_SANS_RETRAITE,
)


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

    def _ccq_lignes_cotisables(self, statuts_exclus):
        """Lignes assujetties dont le statut n'exempte pas de la cotisation.

        Les codes du tableau B de PD5277 désignent des situations où l'heure est
        déclarée mais où certaines cotisations ne sont pas dues : l'entrepreneur
        autonome n'a pas d'avantages sociaux, le représentant désigné ne paie ni
        prélèvement ni fonds, et ainsi de suite. Le filtre est posé LIGNE PAR
        LIGNE, parce que le statut est une propriété de l'heure travaillée : un
        même salarié peut cumuler des heures ordinaires et des heures déclarées
        sous un code particulier dans la même semaine.

        Le statut vide est celui du salarié ordinaire : il ne figure dans aucune
        liste d'exclusion et cotise à tout.
        """
        self.ensure_one()
        return self._ccq_lignes_assujetties().filtered(
            lambda ligne: ligne.statut not in statuts_exclus)

    def _ccq_lignes_frais_participation(self):
        """Heures qui déclenchent les frais de participation aux régimes.

        Ces heures-là ne sont PAS assujetties à la loi R-20 : c'est tout le
        propos du statut A, qui maintient volontairement les régimes d'avantages
        sociaux sur des heures qui en sortent. Le filtre part donc de toutes les
        lignes de la période, pas des seules lignes assujetties.
        """
        self.ensure_one()
        return self._ccq_lignes_temps().filtered(
            lambda ligne: ligne.statut in STATUTS_AVEC_FRAIS_PARTICIPATION)

    def _ccq_primes(self, lignes=None):
        self.ensure_one()
        majorations = self._ccq_majorations()
        Prime = self.env['ccq.prime']
        total = 0.0
        for ligne in self._ccq_lignes_assujetties() if lignes is None else lignes:
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

    def _ccq_salaire_cotisable(self, lignes=None):
        """Salaire de convention servant d'assiette aux cotisations.

        L'ensemble de lignes est paramétrable pour que chaque cotisation puisse
        écarter les statuts qui en sont exemptés sans recopier ce calcul.
        """
        self.ensure_one()
        if lignes is None:
            lignes = self._ccq_lignes_assujetties()
        majorations = self._ccq_majorations()
        total = sum(
            ligne.taux_horaire * (
                ligne.heures_regulieres
                + ligne.heures_supp_50 * majorations['majoration_50']
                + ligne.heures_supp_100 * majorations['majoration_100'])
            for ligne in lignes
        )
        return round(total + self._ccq_primes(lignes), 2)

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
        """Indemnité de 13 %, due sur toutes les heures sauf celles du statut C.

        L'entrepreneur autonome facture ses services : il n'a ni congés payés ni
        avantages sociaux (PD5277, tableau B).
        """
        self.ensure_one()
        assiette = self._ccq_salaire_cotisable(
            self._ccq_lignes_cotisables(STATUTS_SANS_CONGES))
        return round(assiette * self._ccq_taux_conges(), 2)

    # ------------------------------------------------------------------
    # Avantages sociaux
    # ------------------------------------------------------------------

    def _ccq_taux_compagnon(self, ligne):
        """Taux du compagnon au croisement que porte la ligne d'heures.

        La règle particulière du 416 calcule la cotisation patronale de
        prévoyance sur « le taux de salaire du compagnon » (clause 27.06,
        paragraphe 13) a)), et non sur celui de la personne payée : un apprenti
        de première période donne donc le même montant qu'un compagnon. Prendre
        le taux de la ligne sous-paierait la cotisation de tous les apprentis.
        """
        self.ensure_one()
        taux = self.env['ccq.taux.salaire']._taux_applicable(
            ligne.metier_id, ligne.secteur_id, ligne.annexe_id, 'compagnon', ligne.date)
        if not taux:
            raise UserError(
                "Le taux du compagnon est introuvable dans la grille pour le métier "
                "%s, secteur %s, annexe %s, au %s. Une cotisation d'avantages "
                "sociaux s'y calcule."
                % (ligne.metier_id.display_name or "non défini",
                   ligne.secteur_id.display_name or "non défini",
                   ligne.annexe_id.display_name or "non défini", ligne.date)
            )
        return taux.taux_horaire

    def _ccq_cotisation_horaire(self, ligne, caisse, payeur, facteur_conges, obligatoire=True):
        """Cotisation due pour une heure travaillée sur cette ligne d'heures.

        Lue ligne par ligne comme le taux de salaire : la règle particulière du
        métier et le pourcentage du taux de convention se lisent tous deux au
        croisement que porte la ligne, jamais sur une moyenne de la semaine.

        `obligatoire` distingue les caisses que tout salarié assujetti alimente
        de la caisse supplémentaire d'assurance, qui n'existe que là où une règle
        particulière la crée. Pour celle-là, l'absence d'enregistrement est une
        cotisation nulle, pas une erreur de configuration.
        """
        self.ensure_one()
        cotisations = self.env['ccq.avantage.social']._cotisation_applicable(
            ligne.metier_id, caisse, payeur, ligne.periode, ligne.date)
        if not cotisations:
            if not obligatoire:
                return 0.0
            raise UserError(
                "Aucune cotisation d'avantages sociaux n'est définie pour la caisse "
                "« %s », part « %s », métier %s, au %s."
                % (caisse, payeur,
                   ligne.metier_id.display_name or "non défini", ligne.date)
            )
        taux_compagnon = 0.0
        if 'pct_taux_compagnon' in cotisations.mapped('mode'):
            taux_compagnon = self._ccq_taux_compagnon(ligne)
        return cotisations._montant_horaire(
            ligne.taux_horaire, taux_compagnon, facteur_conges)

    def _ccq_avantages_sociaux(self, caisse, payeur, obligatoire=True):
        """Somme de (heures travaillées × cotisation horaire) sur la période.

        « Pour chaque heure de travail » (R-20, r. 10, article 13) : les heures
        supplémentaires comptent une pour une. La majoration rémunère l'heure,
        elle n'en crée pas une seconde — et le pourcentage de la règle
        particulière porte sur le taux RÉGULIER, non majoré.
        """
        self.ensure_one()
        facteur_conges = 1.0 + self._ccq_taux_conges()
        statuts_exclus = (STATUTS_SANS_RETRAITE if caisse == 'retraite'
                          else STATUTS_SANS_ASSURANCE)
        total = sum(
            ligne.total_heures
            * self._ccq_cotisation_horaire(
                ligne, caisse, payeur, facteur_conges, obligatoire)
            for ligne in self._ccq_lignes_cotisables(statuts_exclus)
        )
        return round(total, 2)

    def _ccq_av_soc_assurance(self, payeur):
        """Cotisations d'assurance : prévoyance et caisse supplémentaire réunies.

        Deux caisses au sens du règlement, une seule ligne au bulletin. R-20,
        r. 10, article 13 les distingue parce que le dernier alinéa de son
        annexe I verse à la caisse supplémentaire la part des cotisations
        conventionnelles qui excède les montants réglementaires ; la distinction
        sert au rapport mensuel, pas au calcul de la paie, où les deux sommes
        sont dues au même titre et à la même échéance.
        """
        self.ensure_one()
        return round(
            self._ccq_avantages_sociaux('prevoyance', payeur)
            + self._ccq_avantages_sociaux('supplementaire', payeur, obligatoire=False),
            2)

    def _ccq_av_soc_taxe(self, payeur):
        """Taxe de vente sur les seules cotisations d'assurance.

        La caisse de retraite n'est pas de l'assurance : elle n'est pas taxée.
        La clause 27.03 A) prélève les taxes « selon les pratiques usuelles
        passées de la CCQ » sans distinguer la caisse ni le payeur, et l'article
        13 de R-20, r. 10 fait transiter les sommes de la caisse supplémentaire
        par la caisse de prévoyance, d'où les primes d'assurance sont payées.
        """
        self.ensure_one()
        taux = self._rule_parameter('l10n_ca_qc_ccq_taxe_assurance')
        return round(self._ccq_av_soc_assurance(payeur) * taux, 2)

    def _ccq_av_soc_retraite(self, payeur):
        self.ensure_one()
        return self._ccq_avantages_sociaux('retraite', payeur)

    def _l10n_ca_qc_deductions_rpa(self):
        """La cotisation à la caisse de retraite réduit le revenu imposable.

        C'est un régime de pension agréé : la retenue se déduit du revenu avant
        le calcul de l'impôt, au fédéral comme au Québec. La cotisation à la
        caisse de prévoyance finance une assurance maladie (R-20, r. 10,
        article 11) et ne se déduit pas.

        Seule la part précomptée au salarié entre ici : la cotisation patronale
        n'est pas son revenu, elle ne peut donc pas en être déduite.
        """
        self.ensure_one()
        if not self.employee_id.l10n_ca_qc_ccq_assujetti:
            return super()._l10n_ca_qc_deductions_rpa()
        return self._ccq_av_soc_retraite('salarie')

    # ------------------------------------------------------------------
    # Prélèvement et fonds sectoriels
    # ------------------------------------------------------------------

    def _ccq_heures_travaillees(self, statuts_exclus=()):
        """Heures travaillées assujetties de la période, sans majoration.

        Les fonds se cotisent « pour chaque heure travaillée » : une heure
        supplémentaire est une heure, quel que soit le taux auquel elle est payée.
        Ces heures viennent des feuilles de temps confirmées, jamais du calendrier
        du contrat, qui ignore où et pour qui le salarié a travaillé.
        """
        self.ensure_one()
        return sum(self._ccq_lignes_cotisables(statuts_exclus).mapped('total_heures'))

    def _ccq_prelevement(self, part):
        """Prélèvement de la CCQ — R-20, r. 9, article 1.

        L'assiette est le salaire cotisable AUGMENTÉ de l'indemnité de 13 % :
        « 0,75 % du salaire cotisable additionné du montant de congés et jours
        fériés payés » (guide PD5277, page 5), la Commission percevant au total
        1,5 % à parts égales du salarié et de l'employeur.

        Le règlement, lui, parle de « rémunération versée » (R-20, r. 9,
        article 1), là où la loi distingue à son article 1 q) la « rémunération
        en monnaie courante » des « indemnités » — lecture qui exclurait le
        13 %. C'est la méthode de perception de la Commission qui est retenue :
        une remise inférieure à ce qu'elle réclame est recouvrée majorée de
        20 % (R-20, article 81, paragraphe c.2).

        Le minimum de 10 $ par période mensuelle du deuxième alinéa n'apparaît pas
        ici : il ne vise que l'employeur et l'entrepreneur autonome, jamais la
        retenue salariale, et se règle au rapport mensuel — un bulletin
        hebdomadaire ne peut pas décider d'un plancher mensuel.
        """
        self.ensure_one()
        taux = self._rule_parameter('l10n_ca_qc_ccq_prelevement')[part]
        lignes = self._ccq_lignes_cotisables(STATUTS_SANS_PRELEVEMENT)
        assiette = self._ccq_salaire_cotisable(lignes) + round(
            self._ccq_salaire_cotisable(
                lignes.filtered(lambda l: l.statut not in STATUTS_SANS_CONGES))
            * self._ccq_taux_conges(), 2)
        return round(assiette * taux, 2)

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
        heures = self._ccq_heures_travaillees(STATUTS_SANS_FONDS_FORMATION)
        return round(heures * taux, 2)

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
        heures = self._ccq_heures_travaillees(STATUTS_SANS_FONDS_INDEMNISATION)
        return round(heures * taux, 2)

    def _ccq_contribution_sectorielle(self, payeur):
        """Contribution sectorielle — convention IC 2025-2029, article 7.09.

        La convention l'appelle « caisse d'éducation syndicale », la Commission
        « contribution sectorielle » au rapport mensuel : c'est le même poste.
        Le salarié y verse « une cotisation de 0,02 $ pour chaque heure
        travaillée », précomptée sur sa paie et transmise avec le rapport
        mensuel. Aucune exclusion d'assiette n'est prévue, contrairement au
        fonds d'indemnisation.

        Le payeur dépend du SECTEUR et non de l'entreprise : la contribution est
        salariale en institutionnel-commercial, en industriel et en génie civil,
        patronale en résidentiel. Une semaine partagée entre deux secteurs se
        répartit donc entre les deux lignes du bulletin, d'où ce regroupement
        par secteur plutôt qu'un total d'heures unique.

        Elle ne réduit pas le revenu imposable : ce n'est pas un régime de
        pension agréé, et aucune déduction à la source n'est prévue pour ce type
        de cotisation.
        """
        self.ensure_one()
        bareme = self._rule_parameter('l10n_ca_qc_ccq_contribution_sectorielle')
        total = 0.0
        for ligne in self._ccq_lignes_cotisables(STATUTS_SANS_CONTRIBUTION_SECTORIELLE):
            regle = bareme.get(ligne.secteur_id.code)
            if not regle:
                raise UserError(
                    "Aucune contribution sectorielle n'est paramétrée pour le "
                    "secteur %s, au %s."
                    % (ligne.secteur_id.display_name or "non défini", ligne.date)
                )
            if regle['payeur'] == payeur:
                total += ligne.total_heures * regle['taux']
        return round(total, 2)

    def _ccq_avantage_imposable(self):
        """Avantage imposable des régimes d'assurance sur la période.

        Le montant se lit LIGNE PAR LIGNE, comme le taux de convention : il
        dépend du métier, du secteur et du groupe d'annexes que porte la ligne
        d'heures, et une même semaine peut mêler deux chantiers d'annexes
        différentes — 3,303 $ l'heure en annexe C-3, 3,333 $ en C-6.

        Les heures supplémentaires comptent une pour une : l'avantage rémunère
        une heure de couverture, que la majoration ne dédouble pas.

        Une combinaison sans montant publié vaut zéro. Contrairement à une
        cotisation, l'absence n'est pas ici une erreur de configuration : il
        n'existe d'avantage imposable que là où un régime d'assurance couvre le
        métier, et les paies antérieures au premier millésime chargé n'en
        portaient pas.
        """
        self.ensure_one()
        Avantage = self.env['ccq.avantage.imposable']
        total = 0.0
        for ligne in self._ccq_lignes_cotisables(STATUTS_SANS_ASSURANCE):
            montant = Avantage._montant_applicable(
                ligne.metier_id, ligne.secteur_id, ligne.annexe_id, ligne.date)
            if montant:
                total += ligne.total_heures * montant.montant_horaire
        return round(total, 2)

    def _l10n_ca_qc_avantage_imposable(self):
        """Seules les heures assujetties à la loi R-20 en produisent un.

        Le personnel de bureau et les heures hors champ relèvent de la paie
        ordinaire, qui n'en porte aucun.
        """
        self.ensure_one()
        if not self.employee_id.l10n_ca_qc_ccq_assujetti:
            return super()._l10n_ca_qc_avantage_imposable()
        return self._ccq_avantage_imposable()

    def _ccq_associations_patronales(self):
        """Cotisations aux associations patronales — guide PD5277, page 5.

        L'adhésion à l'association d'employeurs est obligatoire (R-20, article
        40) et la cotisation se transmet avec le rapport mensuel. Elle comporte
        une part commune à tous les secteurs, versée à l'AECQ, et une part
        propre au secteur : l'ACQ en institutionnel-commercial et en industriel,
        l'ACRGTQ en génie civil. En résidentiel, la part sectorielle passe par
        la contribution sectorielle, qui verse à l'APCHQ.

        Aucun texte de loi ne fixe ces montants : l'article 40 les renvoie à
        « la base choisie par l'association ». Ils sont donc publiés, non
        réglementés, et se corrigent par un nouveau millésime de paramètre.

        Trois obligations de la période mensuelle n'apparaissent pas ici, un
        bulletin hebdomadaire ne pouvant pas les trancher : le minimum de 5 $
        par mois de l'AECQ, dû même sans activité déclarée, sa cotisation
        annuelle de 240 $ payable avec le rapport d'octobre, et les taxes, que
        la Commission perçoit à titre de mandataire.
        """
        self.ensure_one()
        p = self._rule_parameter('l10n_ca_qc_ccq_associations_patronales')
        sectorielle = p['sectorielle_horaire']
        total = sum(
            ligne.total_heures * (
                p['aecq_horaire'] + sectorielle.get(ligne.secteur_id.code, 0.0))
            for ligne in self._ccq_lignes_cotisables(STATUTS_SANS_ASSOCIATIONS_PATRONALES)
        )
        return round(total, 2)

    def _ccq_frais_participation(self):
        """Frais de participation aux régimes — R-20, article 126.0.2.

        « Des frais de 0,075 $ par heure de travail sont payables à la Commission
        par toute personne qui lui transmet des contributions et cotisations aux
        régimes complémentaires d'avantages sociaux à l'égard d'un employé qui
        n'est pas un salarié assujetti à la présente loi », et le même montant
        est payable par l'employé, « acquitté au moyen d'une retenue sur le
        salaire ». C'est le prix du maintien volontaire des régimes sur des
        heures qui sortent du champ de la loi : le statut A du tableau B de
        PD5277, étendu par ce guide au représentant désigné et aux trois codes
        d'association syndicale.

        Les deux parts sont identiques, d'où une seule méthode pour les deux
        règles de paie.
        """
        self.ensure_one()
        taux = self._rule_parameter('l10n_ca_qc_ccq_frais_participation')
        heures = sum(self._ccq_lignes_frais_participation().mapped('total_heures'))
        return round(heures * taux, 2)

    def _ccq_contribution_sectorielle_salarie(self):
        self.ensure_one()
        return self._ccq_contribution_sectorielle('salarie')

    def _ccq_contribution_sectorielle_employeur(self):
        self.ensure_one()
        return self._ccq_contribution_sectorielle('employeur')

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
