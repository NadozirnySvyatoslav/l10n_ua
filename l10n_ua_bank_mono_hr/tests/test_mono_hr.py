"""Salary registries, salary contacts and payslips through the monobank
Corporate API (mocked)."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

from odoo.addons.l10n_ua_hr_salary.tests.common import SalaryTestCase
from odoo.exceptions import UserError
from odoo.tests import tagged

MODULE = 'odoo.addons.l10n_ua_bank_mono.models.l10n_ua_bank_mono_config'
OWN_IBAN = 'UA213223130000026007233566001'
EMPLOYEE_IBAN = 'UA233220010000026005233566002'


def _response(status=200, json_data=None, content=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = str(json_data)
    resp.content = content if content is not None else (
        json.dumps(json_data).encode() if json_data is not None else b'')
    resp.json.return_value = json_data
    resp.headers = {}
    return resp


@tagged('post_install', '-at_install')
class TestMonoHr(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('hr_ua.validate_rnokpp', 'False')
        cls.employee.rnokpp = '1234567890'
        bank = cls.env['res.partner.bank'].create({
            'acc_number': EMPLOYEE_IBAN, 'partner_id': cls.employee.work_contact_id.id})
        cls.employee.bank_account_ids = [(4, bank.id)]
        uah = cls.env.ref('base.UAH')
        uah.active = True
        own = cls.env['res.partner.bank'].create({
            'acc_number': OWN_IBAN, 'partner_id': cls.env.company.partner_id.id})
        journal = cls.env['account.journal'].create({
            'name': 'mono corp', 'type': 'bank', 'code': 'MNH',
            'bank_account_id': own.id, 'currency_id': uah.id,
            'company_id': cls.env.company.id})
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'mono corp', 'provider': 'mono', 'mono_api_type': 'corporate',
            'mono_api_token': 'corp-token', 'journal_id': journal.id})
        cls.own_account = own
        cls.reg_type = cls.env['l10n_ua.mono.salary.registry.type'].create({
            'config_id': cls.config.id, 'alias': 'SALARY', 'name': 'Зарплата'})

    def _done_payslip(self):
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
        })
        slip.action_compute_sheet()
        slip.write({'state': 'done'})
        return slip

    # --- Registry types ---

    def test_fetch_registry_types(self):
        with patch(f'{MODULE}.requests.get', return_value=_response(json_data=[
                {'alias': 'SALARY', 'description': 'Заробітна плата'},
                {'alias': 'SALARY_ADVANCE', 'description': 'Аванс',
                 'additionalPurposeAllowed': True}])) as get:
            types = self.env['l10n_ua.mono.salary.registry.type']._mono_fetch(self.config)
        self.assertIn('/ext/v1/payments/salary/registries/types', get.call_args.args[0])
        self.assertEqual(len(types), 2)
        self.assertEqual(self.reg_type.name, 'Заробітна плата')
        advance = types.filtered(lambda t: t.alias == 'SALARY_ADVANCE')
        self.assertTrue(advance.additional_purpose_allowed)

    # --- Registry from the payroll export ---

    def _registry(self):
        slip = self._done_payslip()
        wizard = self.env['hr.payslip.bank.export'].create({
            'date_from': date(2025, 6, 1), 'date_to': date(2025, 6, 30),
            'file_format': 'mono_api', 'payer_account_id': self.own_account.id,
            'payment_purpose': 'Заробітна плата за {period}',
            'mono_registry_type_id': self.reg_type.id,
        })
        self.assertEqual(wizard.mono_config_id, self.config)
        action = wizard.action_generate()
        registry = self.env['l10n_ua.mono.salary.registry'].browse(action['res_id'])
        return registry, slip

    def test_export_creates_draft_registry(self):
        registry, slip = self._registry()
        self.assertEqual(registry.state, 'draft')
        self.assertEqual(registry.name, 'Заробітна плата за 06.2025')
        line = registry.line_ids
        self.assertEqual(line.inn, '1234567890')
        self.assertEqual(line.iban, EMPLOYEE_IBAN)
        self.assertAlmostEqual(line.amount, round(slip.net_salary, 2))

    def test_registry_sent_in_batches_and_finalized(self):
        registry, slip = self._registry()
        responses = [
            _response(json_data={'id': 'reg-1', 'registryReference': 'x',
                                 'state': 'API_LOADING'}),
            _response(json_data=None),
        ]
        with patch(f'{MODULE}.requests.post', side_effect=responses) as post:
            registry.action_send()
        batch, finalize = post.call_args_list
        self.assertEqual(batch.args[0],
                         'https://corp-api.monobank.ua/ext/v2/payments/salary/registries')
        self.assertTrue(batch.kwargs['headers']['idempotency-key'])
        body = batch.kwargs['json']
        self.assertEqual(body['registryReference'], registry.registry_reference)
        self.assertEqual(body['senderIban'], OWN_IBAN)
        self.assertEqual(body['salaryRegistryType'], 'SALARY')
        self.assertEqual((body['from'], body['to']), ('2025-06-01', '2025-06-30'))
        self.assertEqual(body['recipients'], [{
            'fullName': self.employee.name, 'iban': EMPLOYEE_IBAN,
            'amount': int(round(slip.net_salary * 100)), 'inn': '1234567890'}])
        self.assertTrue(finalize.args[0].endswith('/registries/finalize'))
        self.assertEqual(finalize.kwargs['json'],
                         {'registryReference': registry.registry_reference})
        self.assertEqual(registry.state, 'finalized')
        self.assertEqual(registry.bank_registry_id, 'reg-1')

    def test_registry_batch_of_1000(self):
        registry, _slip = self._registry()
        line = registry.line_ids
        registry.write({'line_ids': [(0, 0, dict(
            line.copy_data()[0], registry_id=registry.id)) for _i in range(1000)]})
        self.assertEqual(registry.line_count, 1001)
        with patch(f'{MODULE}.requests.post', side_effect=[
                _response(json_data={'id': 'reg-1'}),
                _response(400, {'errorCode': 'X', 'errorDescription': 'Збій'})]) as post:
            registry.action_send()
        self.assertEqual(len(post.call_args_list[0].kwargs['json']['recipients']), 1000)
        self.assertEqual(len(post.call_args_list[1].kwargs['json']['recipients']), 1)
        # The second batch failed: the first one is kept, nothing finalized.
        self.assertEqual(registry.state, 'loading')
        self.assertEqual(registry.batches_sent, 1)
        with patch(f'{MODULE}.requests.post', side_effect=[
                _response(json_data={'id': 'reg-1'}), _response()]) as post:
            registry.action_send()
        self.assertEqual(len(post.call_args_list[0].kwargs['json']['recipients']), 1)
        self.assertEqual(registry.state, 'finalized')

    def test_registry_status_and_decline_reason(self):
        registry, _slip = self._registry()
        registry.write({'state': 'finalized', 'bank_registry_id': 'reg-1'})
        with patch(f'{MODULE}.requests.get', return_value=_response(json_data={
                'status': 'FAILED', 'declineReason': 'Недостатньо коштів'})) as get:
            self.env['l10n_ua.mono.salary.registry']._cron_refresh_status()
        self.assertIn('/ext/v1/payments/salary/registries/reg-1/status',
                      get.call_args.args[0])
        self.assertEqual(registry.state, 'failed')
        self.assertEqual(registry.decline_reason, 'Недостатньо коштів')
        self.assertTrue(any('Недостатньо коштів' in (m.body or '')
                            for m in registry.message_ids))

    def test_additional_purpose_needs_allowed_type(self):
        registry, _slip = self._registry()
        registry.line_ids.additional_purpose = ' за червень'
        with self.assertRaisesRegex(UserError, 'purpose addition'):
            registry.action_send()

    # --- Salary contacts ---

    def test_contacts_found_created_mismatch(self):
        employees = self.employee
        with patch(f'{MODULE}.requests.get', return_value=_response(json_data={
                'hasMore': False, 'contacts': [{
                    'id': 'c-1', 'inn': '1234567890',
                    'iban': 'UA000000000000000000000000000'}]})) as get:
            report = employees._l10n_ua_mono_sync_contacts(self.config)
        self.assertEqual(get.call_args.kwargs['params']['query'], '1234567890')
        self.assertEqual(len(report['mismatch']), 1)
        self.assertEqual(self.employee.l10n_ua_mono_contact_id, 'c-1')

        with patch(f'{MODULE}.requests.get', return_value=_response(json_data={
                'hasMore': False, 'contacts': []})), \
                patch(f'{MODULE}.requests.post', return_value=_response(
                    json_data={})) as post:
            report = employees._l10n_ua_mono_sync_contacts(self.config)
        self.assertEqual(len(report['created']), 1)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['inn'], '1234567890')
        self.assertEqual(body['iban'], EMPLOYEE_IBAN)
        self.assertTrue(body['lastName'])

    def test_contact_by_passport(self):
        self.employee.write({'rnokpp': False, 'document_type': 'passport',
                             'passport_series': 'АБ', 'passport_id': '123456'})
        self.assertEqual(self.employee._l10n_ua_mono_identity(), {
            'documentType': 'OLD_PASSPORT', 'documentNumber': '123456',
            'documentSeries': 'АБ'})
        self.assertEqual(self.employee._l10n_ua_mono_identification(), 'АБ123456')

    # --- Payslips in the app ---

    def _import(self, slip):
        return self.env['l10n_ua.mono.payslip.import'].create({
            'config_id': self.config.id, 'period': '2025-06',
            'payslip_ids': [(6, 0, slip.ids)]})

    def test_payslips_upload_send_pdf(self):
        slip = self._done_payslip()
        record = self._import(slip)
        with patch(f'{MODULE}.requests.post', return_value=_response(json_data={'result': {
                'period': '2025-06', 'status': 'LOADED',
                'batchStats': {'employeesInBatch': 1, 'successInBatch': 0, 'failedInBatch': 1},
                'overallStats': {'totalEmployees': 1, 'totalSuccessEmployees': 0,
                                 'totalFailedEmployees': 1},
                'failedEmployees': [{'identification': '1234567890',
                                     'reason': 'CONTACT_NOT_FOUND'}]}})) as post:
            record.action_upload()
        self.assertTrue(post.call_args.args[0].endswith('/ext/v1/payslips/batch'))
        body = post.call_args.kwargs['json']
        self.assertEqual(body['period'], '2025-06')
        employee = body['employees'][0]
        self.assertEqual(employee['identification'], '1234567890')
        names = [a['attributeName'] for a in employee['attributes']]
        self.assertEqual([a['sortOrder'] for a in employee['attributes']],
                         list(range(1, len(names) + 1)))
        net = employee['attributes'][-1]
        self.assertEqual(net['value'], '%.2f' % slip.net_salary)
        self.assertTrue(net['attributeSuffix'])
        self.assertEqual(record.state, 'loaded')
        self.assertEqual(record.failed_employees, 1)
        self.assertIn('1234567890', record.failed_details)
        self.assertIn(self.employee.name, record.failed_details)

        with patch(f'{MODULE}.requests.post', return_value=_response(json_data={'result': {
                'period': '2025-06', 'status': 'SENT', 'employeesSent': 1}})) as post:
            record.action_send()
        self.assertTrue(post.call_args.args[0].endswith('/ext/v1/payslip-imports/send'))
        self.assertEqual(post.call_args.kwargs['params'], {'period': '2025-06'})
        self.assertEqual(record.state, 'sent')
        self.assertEqual(record.employees_sent, 1)

        with patch(f'{MODULE}.requests.get', return_value=_response(
                content=b'%PDF-1.4 test')) as get:
            action = slip.action_mono_payslip_pdf()
        self.assertEqual(get.call_args.kwargs['params'],
                         {'identification': '1234567890', 'period': '2025-06'})
        self.assertEqual(action['type'], 'ir.actions.act_url')

    def test_import_status_and_delete(self):
        record = self._import(self._done_payslip())
        record.state = 'loaded'
        with patch(f'{MODULE}.requests.get', return_value=_response(json_data={'result': {
                'period': '2025-06', 'status': 'FAILED', 'totalEmployees': 1,
                'totalSuccessEmployees': 0, 'totalFailedEmployees': 1,
                'failedEmployees': []}})):
            record.action_refresh_status()
        self.assertEqual(record.state, 'failed')
        with patch(f'{MODULE}.requests.delete', return_value=_response(204)) as delete:
            record.action_delete_import()
        self.assertEqual(delete.call_args.kwargs['params'], {'period': '2025-06'})
        self.assertEqual(record.state, 'deleted')

    def test_bad_period(self):
        with self.assertRaises(UserError):
            self.env['l10n_ua.mono.payslip.import'].create({
                'config_id': self.config.id, 'period': '06.2025'})

    def test_hr_officer_sends_registry(self):
        user = self.env['res.users'].create({
            'name': 'Кадровик', 'login': 'mono_hr_officer',
            'group_ids': [(6, 0, [self.env.ref('l10n_ua_hr_base.group_hr_ua_officer').id])],
        })
        registry, _slip = self._registry()
        registry = registry.with_user(user)
        with patch(f'{MODULE}.requests.post', side_effect=[
                _response(json_data={'id': 'reg-u'}), _response()]):
            registry.action_send()
        self.assertEqual(registry.state, 'finalized')
