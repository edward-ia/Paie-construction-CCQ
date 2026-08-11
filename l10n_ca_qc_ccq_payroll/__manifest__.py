{
    'name': "Paie — Construction Québec (CCQ)",
    'version': '19.0.0.11.0',
    'summary': "Couche construction (loi R-20 / CCQ) par-dessus la paie québécoise : "
               "métiers, secteurs, annexes, chantiers, taux de convention et "
               "feuilles de temps hebdomadaires",
    'description': """
Couche « construction » de la paie québécoise, pour les employeurs assujettis à la
loi R-20.

Elle NE recalcule PAS les retenues fiscales : l'impôt fédéral, l'impôt du Québec, le
RRQ, le RRQ2, l'AE et le RQAP viennent du module l10n_ca_qc_hr_payroll, déjà validé
au cent près contre WebRAS et PDOC. Ce module ajoute par-dessus ce qui est propre à
la construction.

CONTENU :
  - référentiel CCQ : secteurs, annexes de salaire, régions, métiers, associations
    et locaux syndicaux, primes de convention ;
  - grilles de taux, cotisations d'avantages sociaux, fonds de qualification et
    barèmes de déplacement, tous versionnés par date d'entrée en vigueur, les
    avantages sociaux distinguant la règle générale des clauses communes des
    règles particulières de métier ;
  - chantiers, porteurs du secteur, de l'annexe, de la région et de
    l'assujettissement ;
  - dimensions CCQ sur la fiche employé ;
  - feuilles de temps hebdomadaires (semaine CCQ : dimanche → samedi), avec les
    sept dimensions du rapport mensuel figées sur chaque ligne d'heures ;
  - paramètres de cotisation CCQ datés (hr.rule.parameter) ;
  - calcul de la paie : salaire de base pris ligne par ligne dans les feuilles de
    temps confirmées, heures supplémentaires payées à 150 % et à 200 % du taux,
    primes de convention, indemnité de congés de 13 % remplaçant la provision de
    vacances sur la part conventionnée, et exclusion de la rémunération versée en
    vertu de la loi R-20 de l'assiette de la cotisation aux normes du travail ;
  - avantages sociaux précomptés sur le salaire : caisse de prévoyance collective,
    taxe sur l'assurance et caisse de retraite, cette dernière déduite du revenu
    imposable à la source comme toute cotisation à un régime de pension agréé ;
  - avantages sociaux à la charge de l'employeur : caisses d'assurance, taxe et
    caisse de retraite, celle-ci distinguant l'Apprenti des autres salariés, avec
    les règles particulières de métier qui s'ajoutent au montant des clauses
    communes au lieu de le remplacer ;
  - prélèvement de la CCQ, parts salariale et patronale, sur la rémunération
    versée ;
  - cotisations patronales au fonds de formation et au fonds d'indemnisation,
    calculées sur les heures des feuilles de temps, chacune avec sa propre
    assiette — seul le fonds d'indemnisation exclut les propriétaires,
    actionnaires principaux, répondants de licence et représentants désignés.

NON AUTOMATISÉ : la contribution sectorielle, la cotisation syndicale, les
cotisations aux associations patronales, les frais de déplacement, le rapport
mensuel et les remises.

Sources officielles :
  - CCQ, « Guide pour remplir le rapport mensuel » (PD5277)
  - CCQ, convention collective institutionnel et commercial 2025-2029 (PD5145)
  - Règlement sur les régimes complémentaires d'avantages sociaux dans
    l'industrie de la construction (chapitre R-20, r. 10)
  - Règlement de prélèvement de la Commission de la construction du Québec
    (chapitre R-20, r. 9)
  - Règlement sur le fonds de formation des salariés de l'industrie de la
    construction (chapitre R-20, r. 7.1)
  - Règlement sur le fonds d'indemnisation des salariés de l'industrie de la
    construction (chapitre R-20, r. 7.01)
  - ACQ, « Frais de déplacement 2025-2028 »

Les taux et barèmes sont des données datées : ils ne doivent jamais être modifiés
dans l'interface. Pour un nouveau millésime, ajouter un fichier daté — l'ancien
reste, pour pouvoir rejouer l'historique.
""",
    'author': 'Edward IA',
    'category': 'Human Resources/Payroll',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ca_qc_hr_payroll',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ccq_rule_parameter_data.xml',
        'data/ccq_rule_parameter_value_2025_data.xml',
        'data/ccq_referentiel_data.xml',
        'data/ccq_region_data.xml',
        'data/ccq_taux_data.xml',
        'data/ccq_avantage_social_data.xml',
        'data/ccq_salary_rule_data.xml',
        'views/ccq_views.xml',
        'views/ccq_search_views.xml',
    ],
    'installable': True,
    'application': False,
}
