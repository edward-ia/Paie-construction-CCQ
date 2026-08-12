{
    'name': 'Paie — Québec (Canada)',
    'version': '19.0.1.17.0',
    'category': 'Human Resources/Payroll',
    'summary': "Retenues à la source du Québec : RRQ, RQAP, AE, impôt provincial et fédéral",
    'description': """
Règles de paie québécoises pour le moteur hr_payroll.

Sources officielles des barèmes :
  - Revenu Québec, TP-1015.F (formules de retenues à la source)
  - Agence du revenu du Canada, T4127 (formules informatisées)

Les barèmes sont des hr.rule.parameter datés : un fichier par millésime.
Ils ne doivent jamais être modifiés dans l'interface — voir data/README.
""",
    'author': 'Edward IA',
    'depends': ['hr_payroll'],
    'data': [
        'data/hr_rule_parameter_data.xml',
        'data/hr_rule_parameter_value_2026_data.xml',
        'data/hr_payroll_structure_data.xml',
        'data/hr_salary_rule_data.xml',
        'report/hr_payslip_bulletin_report.xml',
        'report/hr_payslip_sommaire_report.xml',
        'views/hr_payslip_views.xml',
        'views/res_company_views.xml',
    ],
    'license': 'LGPL-3',
}
