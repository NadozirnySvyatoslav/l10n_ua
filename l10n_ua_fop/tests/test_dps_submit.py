"""Подання декларації ЄП у ДПС: ім'я файлу, транспортний пакет, відповідь кабінету."""

import base64
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_dps_submit_mixin import dps_standard_filename

CONFIG = 'odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_tax_cabinet_config.L10nUaTaxCabinetConfig'

HEAD = (b'<?xml version="1.0" encoding="windows-1251"?><DECLAR><DECLARHEAD>'
        b'<TIN>2940910418</TIN><C_DOC>F01</C_DOC><C_DOC_SUB>033</C_DOC_SUB>'
        b'<C_DOC_VER>9</C_DOC_VER><C_DOC_TYPE>0</C_DOC_TYPE><C_DOC_CNT>1</C_DOC_CNT>'
        b'<C_REG>17</C_REG><C_RAJ>16</C_RAJ><PERIOD_MONTH>9</PERIOD_MONTH>'
        b'<PERIOD_TYPE>4</PERIOD_TYPE><PERIOD_YEAR>2026</PERIOD_YEAR>'
        b'<C_STI_ORIG>1716</C_STI_ORIG><C_DOC_STAN>1</C_DOC_STAN></DECLARHEAD></DECLAR>')


@tagged('post_install', '-at_install')
class TestDpsSubmit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        config = cls.env['l10n_ua.tax.cabinet.config'].with_context(active_test=False).search(
            [('company_id', '=', company.id)], limit=1)
        vals = {'name': 'Кабінет', 'taxpayer_code': '2940910418', 'active': True}
        if config:
            config.write(vals)
        else:
            cls.env['l10n_ua.tax.cabinet.config'].create({**vals, 'company_id': company.id})
        group = cls.env['l10n_ua.fop.group'].search([('code', '=', '3')], limit=1)
        cls.decl = cls.env['l10n_ua.fop.declaration'].create({
            'year': 2026, 'period': '9m', 'fop_group_id': group.id, 'company_id': company.id,
            'total_income': 1000.0, 'state': 'calculated',
            'xml_file': base64.b64encode(HEAD).decode(),'xml_filename': 'x.xml'})

    def test_standard_filename(self):
        self.assertEqual(dps_standard_filename(HEAD),
                         '17162940910418F0103309100000000140920261716.xml')
        self.assertIsNone(dps_standard_filename(b'<x/>'))
        self.assertEqual(self.decl._dps_filename(), '17162940910418F0103309100000000140920261716.xml')

    def test_signing_spec_is_transport_container(self):
        with patch(CONFIG + '._get_dps_encrypt_certificate', return_value=b'CERT'):
            doc = self.decl.kep_prepare_signing()['documents'][0]
        self.assertEqual(doc['format'], 'dps_transport')
        self.assertEqual(doc['taxpayer_code'], '2940910418')
        self.assertEqual(doc['filename'], '17162940910418F0103309100000000140920261716.xml')

    def test_rejected_status_is_not_submitted(self):
        rejected = {'message': None, 'status': 'ERROR_DECRYPT', 'id': None,
                    'kvt1Base64': None, 'kvt1Fname': None, 'kvtList': None}
        with patch(CONFIG + '._api_submit_document_presigned', return_value=rejected):
            with self.assertRaisesRegex(UserError, 'розшифрувати'):
                self.decl.kep_submit_signed({'doc': 'ENV'}, 'AUTH')
        self.assertEqual(self.decl.state, 'calculated')

    def test_ok_stores_receipt(self):
        ok = [{'status': 'OK', 'id': 77, 'message': 'Прийнято',
               'kvt1Base64': base64.b64encode(b'<KVT/>').decode(), 'kvt1Fname': 'kvt1.xml',
               'kvtList': None}]
        with patch(CONFIG + '._api_submit_document_presigned', return_value=ok):
            result = self.decl.kep_submit_signed({'doc': 'ENV'}, 'AUTH')
        self.assertEqual(self.decl.state, 'submitted')
        self.assertEqual(result['receipt'], 'Прийнято')
        att = self.env['ir.attachment'].search([
            ('res_model', '=', 'l10n_ua.fop.declaration'), ('res_id', '=', self.decl.id),
            ('name', '=', 'kvt1.xml')])
        self.assertEqual(att.raw.content, b'<KVT/>')
