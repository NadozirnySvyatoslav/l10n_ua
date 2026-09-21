"""Тести імпорту виписки VST Bank (iBank 2 UA CSV) — #196."""

import base64

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError  # noqa: F401

HEADER = ('ЄДРПОУ;МФО;Рахунок;Валюта;Дата операції;Код операції;МФО банку;'
          'Назва банку;Рахунок кореспондента;ЄДРПОУ кореспондента;Кореспондент;'
          'Документ;Дата документу;Дебет;Кредит;Призначення платежу;'
          'Гривневе покриття;Ідентифікатор операції')
DEBIT_ROW = ('76345670;300335;UA773003350000026001236521254;UAH;'
             '25.03.2018 10:01:43;;300335;"АТ ""Райффайзен"" ";'
             'UA623003350000026009850123658;76655689;"ВАТ ""Агросервіс"" ";'
             '1;01.06.2018;100.11;;за послуги;0.00;15580')
CREDIT_ROW = ('76345670;300335;UA773003350000026001236521254;UAH;'
              '26.03.2018 09:00:00;;300335;"ПриватБанк";'
              'UA113052990000026007891234567;12345678;"ТОВ Клієнт";'
              '2;02.06.2018;;2500.50;оплата товару;0.00;15581')
SAMPLE_CSV = '\r\n'.join([HEADER, DEBIT_ROW, CREDIT_ROW]) + '\r\n'


@tagged('post_install', '-at_install')
class TestVstImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env['account.journal'].create({
            'name': 'VST Bank', 'type': 'bank', 'code': 'VSTB',
            'company_id': cls.company.id,
        })
        partner = cls.env['res.partner'].create({'name': 'Company'})
        cls.acc = cls.env['res.partner.bank'].create({
            'acc_number': '26001236521254', 'partner_id': partner.id,
        })
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'VST', 'provider': 'vst',
            'journal_id': cls.journal.id, 'bank_account_id': cls.acc.id,
        })

    def test_parse_debit_and_credit(self):
        txs = self.config._parse_transactions({'csv': SAMPLE_CSV})
        self.assertEqual(len(txs), 2)
        debit, credit = txs[0], txs[1]
        # Дебет → від'ємна сума (списання).
        self.assertAlmostEqual(debit['amount'], -100.11, places=2)
        self.assertEqual(debit['date'], '2018-03-25')
        self.assertEqual(debit['partner_name'], 'ВАТ "Агросервіс"')
        self.assertEqual(debit['partner_edrpou'], '76655689')
        self.assertEqual(debit['description'], 'за послуги')
        self.assertEqual(debit['id'], '15580')
        # Кредит → додатна сума (надходження).
        self.assertAlmostEqual(credit['amount'], 2500.50, places=2)
        self.assertEqual(credit['date'], '2018-03-26')
        self.assertEqual(credit['partner_name'], 'ТОВ Клієнт')

    def test_header_skipped(self):
        txs = self.config._parse_transactions({'csv': SAMPLE_CSV})
        # Рядок-шапка не потрапляє у транзакції.
        self.assertTrue(all(t['partner_edrpou'] != 'ЄДРПОУ кореспондента'
                            for t in txs))

    def test_empty_and_zero_skipped(self):
        csv = '\r\n'.join([HEADER,
                           '76345670;300335;UA77;UAH;25.03.2018;;;;;;;1;;;;;;',
                           '']) + '\r\n'
        txs = self.config._parse_transactions({'csv': csv})
        self.assertEqual(txs, [])

    def test_non_vst_delegates(self):
        # Для іншого провайдера vst-парсер делегує базовому (не реалізовано).
        other = self.env['l10n_ua.bank.sync.config'].create({
            'name': 'M', 'provider': 'manual',
            'journal_id': self.journal.id, 'bank_account_id': self.acc.id,
        })
        with self.assertRaises(NotImplementedError):
            other._parse_transactions({'csv': SAMPLE_CSV})

    def test_exchange_type_file(self):
        # VST — файловий обмін (керує видимістю кнопок).
        self.assertEqual(self.config.exchange_type, 'file')

    def test_generic_import_wizard_creates_statement(self):
        # Узагальнений файловий майстер + VST _file_to_payload → native-виписка.
        data = base64.b64encode(SAMPLE_CSV.encode('cp1251')).decode()
        wiz = self.env['l10n_ua.bank.statement.import'].create({
            'config_id': self.config.id,
            'statement_file': data,
            'file_name': 'vst.csv',
        })
        action = wiz.action_import()
        self.assertEqual(action['res_model'], 'account.bank.statement')
        statement = self.env['account.bank.statement'].browse(action['res_id'])
        self.assertEqual(len(statement.line_ids), 2)
        self.assertEqual(statement.l10n_ua_source_type, 'file')
        self.assertEqual(statement.l10n_ua_source_ref, 'vst.csv')

    def test_file_to_payload(self):
        content = SAMPLE_CSV.encode('cp1251')
        payload = self.config._file_to_payload(content, 'vst.csv')
        self.assertIn('csv', payload)
        self.assertIn('ЄДРПОУ', payload['csv'])
