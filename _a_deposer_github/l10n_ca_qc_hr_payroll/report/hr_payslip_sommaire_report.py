from odoo import api, models

# Codes de lignes regroupés par agence de remise. L'employeur remet À LA FOIS
# les retenues prélevées sur l'employé (DED) et ses propres cotisations (COMP),
# d'où le mélange des deux dans chaque agence.
_RQ_CODES = ['IMPOT_QC', 'RRQ', 'RRQ2', 'RRQ_EMP', 'RRQ2_EMP', 'RQAP', 'RQAP_EMP', 'FSS', 'CNT']
_ARC_CODES = ['IMPOT_FED', 'AE', 'AE_EMP']


class ReportSommaireRemise(models.AbstractModel):
    _name = 'report.l10n_ca_qc_hr_payroll.report_sommaire_remise'
    _description = "Sommaire de remise employeur — Québec"

    def _total_for(self, records, codes):
        """Somme des montants (en valeur absolue) des lignes dont le code est
        dans `codes`, sur l'ensemble des fiches `records`. On prend la valeur
        absolue car les retenues employé (DED) sont stockées en négatif et les
        cotisations employeur (COMP) en positif."""
        return sum(abs(line.total) for line in records.line_ids if line.code in codes)

    @api.model
    def _get_report_values(self, docids, data=None):
        slips = self.env['hr.payslip'].browse(docids)
        company = slips[:1].company_id or self.env.company

        rq = {
            'impot_qc': self._total_for(slips, ['IMPOT_QC']),
            'rrq': self._total_for(slips, ['RRQ', 'RRQ2', 'RRQ_EMP', 'RRQ2_EMP']),
            'rqap': self._total_for(slips, ['RQAP', 'RQAP_EMP']),
            'fss': self._total_for(slips, ['FSS']),
            'cnt': self._total_for(slips, ['CNT']),
        }
        rq['total'] = rq['impot_qc'] + rq['rrq'] + rq['rqap'] + rq['fss'] + rq['cnt']

        arc = {
            'impot_fed': self._total_for(slips, ['IMPOT_FED']),
            'ae': self._total_for(slips, ['AE', 'AE_EMP']),
        }
        arc['total'] = arc['impot_fed'] + arc['ae']

        cnesst = self._total_for(slips, ['CNESST'])
        vacances = self._total_for(slips, ['VAC'])

        # Détail par employé (une ligne par personne, totaux par agence).
        per_employee = []
        for emp in slips.mapped('employee_id'):
            emp_slips = slips.filtered(lambda p: p.employee_id == emp)
            per_employee.append({
                'name': emp.name,
                'rq': self._total_for(emp_slips, _RQ_CODES),
                'arc': self._total_for(emp_slips, _ARC_CODES),
                'cnesst': self._total_for(emp_slips, ['CNESST']),
                'vacances': self._total_for(emp_slips, ['VAC']),
            })

        dates_from = slips.mapped('date_from')
        dates_to = slips.mapped('date_to')

        return {
            'doc_ids': docids,
            'doc_model': 'hr.payslip',
            'docs': slips,
            'company': company,
            'currency': company.currency_id,
            'date_from': min(dates_from) if dates_from else False,
            'date_to': max(dates_to) if dates_to else False,
            'nb_slips': len(slips),
            'nb_employees': len(slips.mapped('employee_id')),
            'nb_draft': len(slips.filtered(lambda p: p.state == 'draft')),
            'rq': rq,
            'arc': arc,
            'cnesst': cnesst,
            'vacances': vacances,
            'per_employee': per_employee,
        }
