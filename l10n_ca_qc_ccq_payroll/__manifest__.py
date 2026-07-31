{
    'name': "Paie — Construction Québec (CCQ)",
    'version': '19.0.0.2.0',
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

CONTENU DE CETTE VERSION — le modèle de données uniquement :
  - référentiel CCQ : secteurs, annexes de salaire, régions, métiers, associations
    et locaux syndicaux, primes de convention ;
  - grilles de taux, fonds de qualification et barèmes de déplacement, tous
    versionnés par date d'entrée en vigueur ;
  - chantiers, porteurs du secteur, de l'annexe, de la région et de
    l'assujettissement ;
  - dimensions CCQ sur la fiche employé ;
  - feuilles de temps hebdomadaires (semaine CCQ : dimanche → samedi), avec les
    sept dimensions du rapport mensuel figées sur chaque ligne d'heures ;
  - paramètres de cotisation CCQ datés (hr.rule.parameter).

PAS ENCORE FAIT : le moteur de calcul (règles de paie, cotisations, primes,
déplacement), le rapport mensuel et les remises.

Sources officielles :
  - CCQ, « Guide pour remplir le rapport mensuel » (PD5277)
  - CCQ, convention collective institutionnel et commercial 2025-2029 (PD5145)
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
        'data/ccq_salary_rule_data.xml',
        'views/ccq_views.xml',
    ],
    'installable': True,
    'application': False,
}
