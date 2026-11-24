"""Форма № 5 «Примітки до річної фінансової звітності» (#78).
Дати — 2047 рік, рахунки створюються тут."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ua_accounting.models.l10n_ua_notes_data import notes_rows, notes_xml_element

from .common import AccountingTestCase

D = date(2047, 5, 20)


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestNotesReport(AccountingTestCase):

    _own_company = True  # #654: demo balances leak into code-prefix rows

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        acc = cls._account
        cls.acc_104 = acc('104', 'Машини та обладнання', 'asset_fixed')
        cls.acc_103 = acc('103', 'Будинки та споруди', 'asset_fixed')
        cls.acc_131 = acc('131', 'Знос основних засобів', 'asset_fixed')
        cls.acc_152 = acc('152', 'Придбання основних засобів', 'asset_fixed')
        cls.acc_201 = acc('201', 'Сировина й матеріали', 'asset_current')
        cls.acc_281 = acc('281', 'Товари на складі', 'asset_current')
        cls.acc_311 = acc('311', 'Поточні рахунки в банку', 'asset_cash')
        cls.acc_301 = acc('301', 'Каса', 'asset_cash')
        cls.acc_361 = acc('361', 'Розрахунки з покупцями', 'asset_receivable', True)
        cls.acc_471 = acc('471', 'Забезпечення виплат відпусток', 'liability_current')
        cls.acc_631 = acc('631', 'Розрахунки з постачальниками', 'liability_payable', True)
        cls.acc_661 = acc('661', 'Розрахунки за заробітною платою', 'liability_current')
        cls.acc_702 = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_714 = acc('714', 'Дохід від операційної курсової різниці', 'income_other')
        cls.acc_92 = acc('92', 'Адміністративні витрати', 'expense')
        cls.acc_945 = acc('945', 'Втрати від операційної курсової різниці', 'expense')
        cls.acc_981 = acc('981', 'Податок на прибуток', 'expense')
        cls.acc_6413 = acc('6413', 'Розрахунки за податком на прибуток', 'liability_current')

    @classmethod
    def _account(cls, code, name, account_type, reconcile=False):
        Account = cls.env['account.account']
        account = Account.search([
            ('code', '=', code), ('company_ids', 'in', cls.company.id)], limit=1)
        return account or Account.create({
            'code': code, 'name': name, 'account_type': account_type,
            'reconcile': reconcile, 'company_ids': [(6, 0, cls.company.ids)],
        })

    def _entry(self, debit_account, credit_account, amount, on_date=D):
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.misc_journal.id, 'date': on_date,
            'line_ids': [
                (0, 0, {'account_id': debit_account.id, 'debit': amount, 'partner_id': self.partner.id}),
                (0, 0, {'account_id': credit_account.id, 'credit': amount, 'partner_id': self.partner.id}),
            ],
        })
        move.action_post()

    def _report(self):
        report = self.env['l10n_ua.notes.report'].create({
            'company_id': self.company.id,
            'date_from': date(2047, 1, 1), 'date_to': date(2047, 12, 31),
        })
        report.action_compute()
        return report

    def _cell(self, report, code, graph):
        return report.line_ids.filtered(lambda l: l.code == code)[f'g{graph}']

    def test_layout_covers_every_cell_of_the_xsd(self):
        cells = {notes_xml_element(code, g) for _s, _q, code, _n, kind, graphs in notes_rows()
                 if code and kind != 'title' for g in graphs}
        self.assertEqual(len(cells), 1052)
        self.assertIn('R02641G3', cells)
        self.assertIn('R1540G11', cells)
        self.assertNotIn('R1420G4', cells)   # «Х» on the form

    def test_filled_from_the_ledger(self):
        self._entry(self.acc_104, self.acc_631, 120000)
        self._entry(self.acc_103, self.acc_631, 300000, date(2046, 6, 1))
        self._entry(self.acc_152, self.acc_631, 45000)
        self._entry(self.acc_92, self.acc_131, 18000)
        self._entry(self.acc_201, self.acc_631, 7400)
        self._entry(self.acc_281, self.acc_631, 15600)
        self._entry(self.acc_311, self.acc_361, 25000)
        self._entry(self.acc_301, self.acc_361, 2500)
        self._entry(self.acc_92, self.acc_471, 9000)
        self._entry(self.acc_471, self.acc_661, 4000)
        self._entry(self.acc_361, self.acc_702, 60000)
        self._entry(self.acc_361, self.acc_702, 10000, date(2046, 3, 1))
        self._entry(self.acc_361, self.acc_714, 1200)
        self._entry(self.acc_945, self.acc_361, 800)
        self._entry(self.acc_981, self.acc_6413, 3000)

        report = self._report()
        cell = lambda code, g: self._cell(report, code, g)  # noqa: E731
        # II: 103 bought last year, 104 this year
        self.assertEqual((cell('120', 3), cell('120', 14)), (300, 300))
        self.assertEqual((cell('130', 5), cell('130', 14)), (120, 120))
        self.assertEqual(cell('260', 14), 420)
        self.assertIn('131: 18', report.depreciation_hint)
        # III
        self.assertEqual((cell('290', 3), cell('340', 4)), (45, 45))
        # V: operating FX difference, income and expense
        self.assertEqual((cell('450', 3), cell('450', 4)), (1, 1))
        # VI
        self.assertEqual((cell('640', 3), cell('650', 3), cell('690', 3)), (3, 25, 28))
        # VII: holiday provision 9000 accrued, 4000 used
        self.assertEqual((cell('710', 4), cell('710', 6), cell('710', 9)), (9, 4, 5))
        # VIII
        self.assertEqual((cell('800', 3), cell('910', 3), cell('920', 3)), (7, 16, 23))
        # IX: rows 1125/1155 of Form 1
        self.assertTrue(cell('940', 3))
        # XII, XIII
        self.assertEqual((cell('1210', 3), cell('1240', 3)), (3, 3))
        self.assertEqual(cell('1300', 3), 18)

    def test_manual_entry_and_totals(self):
        report = self._report()
        line = report.line_ids.filtered(lambda l: l.code == '1411')
        line.g3 = 40
        report.line_ids.filtered(lambda l: l.code == '1421').g3 = 7
        self.assertEqual(self._cell(report, '1410', 3), 40)
        self.assertEqual(self._cell(report, '1430', 3), 47)
        with self.assertRaises(UserError):
            report.line_ids.filtered(lambda l: l.code == '1430').g3 = 1      # a total
        with self.assertRaises(UserError):
            report.line_ids.filtered(lambda l: l.code == '1421').g4 = 1      # «Х»
        blank = report.line_ids.filtered(lambda l: l.code == '060')
        blank.write({'label': 'Права на програмне забезпечення', 'g14': 5})
        values = report._xml_values()
        self.assertEqual(values['R0060G1S'], 'Права на програмне забезпечення')
        self.assertEqual(values['R0080G14'], 5)
        self.assertEqual(values['R1430G3'], 47)

    def test_print(self):
        report = self._report()
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_accounting.report_notes_document', report.ids)[0].decode()
        self.assertIn('ПРИМІТКИ ДО РІЧНОЇ ФІНАНСОВОЇ ЗВІТНОСТІ', html)
        self.assertIn('XV. Фінансові результати', html)
