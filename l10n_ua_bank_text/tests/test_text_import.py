"""Тести узагальненого текстового провайдера виписки (BUH-1/ІБІС/CSV) — #82."""

import base64

from odoo.tests import TransactionCase, tagged

HEADER = 'Дата;Документ;Дебет;Кредит;Контрагент;Рахунок;ЄДРПОУ;Призначення'
ROW_CREDIT = ('01.06.2026;101;;2500.50;ТОВ Постачальник;26007111222333;'
              '12345678;оплата за товар')
ROW_DEBIT = '03.06.2026;102;100.11;;Банк;26009999888;;комісія за РКО'
SAMPLE = '\r\n'.join([HEADER, ROW_CREDIT, ROW_DEBIT]) + '\r\n'


@tagged('post_install', '-at_install')
class TestTextImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        journal = cls.env['account.journal'].create({
            'name': 'Text Bank', 'type': 'bank', 'code': 'TXBK'})
        partner = cls.env['res.partner'].create({'name': 'C'})
        acc = cls.env['res.partner.bank'].create({
            'acc_number': '26001112223334', 'partner_id': partner.id})
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'BUH-1', 'provider': 'text',
            'journal_id': journal.id, 'bank_account_id': acc.id,
            'text_delimiter': 'semicolon', 'text_encoding': 'cp1251',
            'text_skip_rows': 1, 'text_date_format': '%d.%m.%Y',
            'text_col_date': 0, 'text_col_docid': 1,
            'text_col_debit': 2, 'text_col_credit': 3,
            'text_col_partner': 4, 'text_col_account': 5,
            'text_col_edrpou': 6, 'text_col_purpose': 7,
        })

    def _payload(self):
        return {'text': SAMPLE}

    def test_exchange_type_file(self):
        self.assertEqual(self.config.exchange_type, 'file')

    def test_parse_debit_credit(self):
        txs = self.config._parse_transactions(self._payload())
        self.assertEqual(len(txs), 2)  # шапка пропущена
        credit, debit = txs[0], txs[1]
        self.assertAlmostEqual(credit['amount'], 2500.50, places=2)
        self.assertEqual(credit['date'], '2026-06-01')
        self.assertEqual(credit['partner_name'], 'ТОВ Постачальник')
        self.assertEqual(credit['partner_iban'], '26007111222333')
        self.assertEqual(credit['partner_edrpou'], '12345678')
        self.assertEqual(credit['description'], 'оплата за товар')
        self.assertEqual(credit['id'], '101')
        self.assertAlmostEqual(debit['amount'], -100.11, places=2)

    def test_signed_amount_column(self):
        # Дт/Кт вимкнено, колонка 3 = сума зі знаком.
        self.config.write({
            'text_col_debit': -1, 'text_col_credit': -1, 'text_col_amount': 3})
        text = 'header\r\n01.06.2026;1;x;250.00;;;;\r\n05.06.2026;2;x;-40.00;;;;\r\n'
        txs = self.config._parse_transactions({'text': text})
        self.assertEqual(len(txs), 2)
        self.assertAlmostEqual(txs[0]['amount'], 250.0, places=2)
        self.assertAlmostEqual(txs[1]['amount'], -40.0, places=2)

    def test_file_to_payload(self):
        payload = self.config._file_to_payload(SAMPLE.encode('cp1251'), 'buh1.txt')
        self.assertIn('text', payload)
        self.assertIn('Постачальник', payload['text'])

    def test_generic_wizard_creates_statement(self):
        data = base64.b64encode(SAMPLE.encode('cp1251')).decode()
        wiz = self.env['l10n_ua.bank.statement.import'].create({
            'config_id': self.config.id, 'statement_file': data,
            'file_name': 'buh1.txt'})
        action = wiz.action_import()
        self.assertEqual(action['res_model'], 'account.bank.statement')
        st = self.env['account.bank.statement'].browse(action['res_id'])
        self.assertEqual(len(st.line_ids), 2)
        self.assertEqual(st.l10n_ua_source_type, 'file')
