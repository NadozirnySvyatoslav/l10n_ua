"""Документообіг з КЕП без сервісу ЕДО.

Підписи — справжні CMS (CAdES) із тестовими RSA-сертифікатами з тими самими
полями, що в українських кваліфікованих (TINUA-…, NTRUA-…): модуль бере з
них лише те, чий це підпис; сам підпис перевіряє бібліотека IIT у браузері.
"""

import base64
import datetime
import io
import zipfile
from email.message import EmailMessage

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.l10n_ua_edo_kep.models.kep_cms import embedded_content, parse_signature

PDF = b'%PDF-1.4\n% test document\n'


def make_key(name, drfo=None, edrpou=None, organization=None, title=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, name)]
    if drfo:
        attrs.append(x509.NameAttribute(NameOID.SURNAME, name.split()[0]))
        attrs.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, f'TINUA-{drfo}'))
    if title:
        attrs.append(x509.NameAttribute(NameOID.TITLE, title))
    if organization:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization))
    if edrpou:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_IDENTIFIER, f'NTRUA-{edrpou}'))
    subject = x509.Name(attrs)
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Тестовий ЦСК')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    return cert, key


def sign(data, signer, attached=False):
    cert, key = signer
    options = [pkcs7.PKCS7Options.Binary] + ([] if attached else [pkcs7.PKCS7Options.DetachedSignature])
    return (pkcs7.PKCS7SignatureBuilder().set_data(data)
            .add_signer(cert, key, hashes.SHA256())
            .sign(serialization.Encoding.DER, options))


@tagged('post_install', '-at_install', 'l10n_ua_edo')
class TestKep(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.account = cls.env['l10n_ua.edo.account'].create({
            'name': 'КЕП', 'provider': 'kep', 'edrpou': '11111116', 'company_id': cls.company.id,
        })
        cls.director = make_key('Петренко Петро Петрович', drfo='1111111111', edrpou='11111116',
                                organization='ТОВ «Наша»', title='Директор')
        cls.customer_key = make_key('Іваненко Іван Іванович', drfo='2222222222', edrpou='22222221',
                                    organization='ТОВ «Покупець»', title='Директор')
        cls.customer_seal = make_key('ТОВ «Покупець»', edrpou='22222221', organization='ТОВ «Покупець»')
        cls.stranger = make_key('Сидоренко Сидір', drfo='3333333333')
        cls.customer = cls.env['res.partner'].create({
            'name': 'ТОВ «Покупець»', 'is_company': True, 'email': 'buh@customer.example'})
        if 'edrpou' in cls.customer._fields:
            cls.customer.edrpou = '22222221'

    def _outgoing(self, counterparty_edrpou='22222221'):
        """What l10n_ua.edo.mixin._edo_send does for a record."""
        data = self.account._call('upload', {'recipient_emails': ['buh@customer.example'], 'category': 'act'})
        vals = self.account._call('normalize', data)
        Document = self.env['l10n_ua.edo.document']
        doc = Document.create({
            **{k: v for k, v in vals.items() if k in Document._fields},
            'name': 'Акт № 7', 'account_id': self.account.id, 'direction': 'out',
            'counterparty_edrpou': counterparty_edrpou, 'partner_id': self.customer.id,
        })
        doc.attachment_id = self.env['ir.attachment'].create({
            'name': 'Akt_7.pdf', 'raw': PDF, 'res_model': doc._name, 'res_id': doc.id})
        return doc

    def _mails(self, doc):
        return self.env['mail.mail'].search([('model', '=', doc._name), ('res_id', '=', doc.id)])

    def _zip_names(self, attachment):
        return sorted(zipfile.ZipFile(io.BytesIO(attachment.raw)).namelist())

    # ── Certificates ────────────────────────────────────────

    def test_signer_from_the_certificate(self):
        info = parse_signature(sign(PDF, self.director))
        self.assertEqual((info['drfo'], info['edrpou'], info['signer_title'], info['is_stamp']),
                         ('1111111111', '11111116', 'Директор', False))
        seal = parse_signature(sign(PDF, self.customer_seal))
        self.assertEqual((seal['drfo'], seal['edrpou'], seal['is_stamp']), (False, '22222221', True))
        self.assertEqual(embedded_content(sign(PDF, self.director, attached=True)), PDF)
        self.assertIsNone(embedded_content(sign(PDF, self.director)))

    # ── Outgoing ────────────────────────────────────────────

    def test_outgoing_signed_in_odoo_then_on_the_portal(self):
        doc = self._outgoing()
        self.assertEqual(doc.state, 'uploaded')
        self.assertTrue(doc.can_sign)
        self.assertEqual(doc.kep_recipient_emails, 'buh@customer.example')
        # Our signature (the КЕП dialog), then the invitation to the counterparty
        doc.kep_submit_signed({'document': base64.b64encode(sign(PDF, self.director)).decode()})
        self.assertEqual(doc.state, 'signed_owner')
        self.assertFalse(doc.can_sign)
        self.assertTrue(doc.kep_invited)
        invitation = self._mails(doc)
        self.assertEqual(len(invitation), 1)
        self.assertIn('buh@customer.example', invitation.email_to)
        self.assertIn(doc.get_portal_url().split('?')[0], invitation.body_html)
        # The counterparty signs on the portal: a signature and a seal
        self.assertTrue(doc._kep_can_sign_their())
        doc._kep_portal_sign(base64.b64encode(sign(PDF, self.customer_key)).decode())
        self.assertEqual(doc.state, 'signed')
        self.assertEqual(self._zip_names(doc.archive_attachment_id), [
            'Akt_7. Pidpys 11111116.p7s', 'Akt_7. Pidpys 22222221.p7s', 'Akt_7.pdf', 'Kvytantsiia.pdf'])
        signed_mail = self._mails(doc) - invitation
        self.assertEqual(len(signed_mail), 1)
        self.assertEqual(signed_mail.attachment_ids.name, 'Akt_7.zip')
        # The seal after all signed: the archive is rebuilt
        doc._kep_add_signature(sign(PDF, self.customer_seal))
        self.assertIn('Akt_7. Pechatka 22222221.p7s', self._zip_names(doc.archive_attachment_id))
        self.assertEqual(doc.kep_unchecked_count, 3)

    def test_recipient_signs_first(self):
        doc = self._outgoing()
        self.account._call('send', doc.provider_ref)
        self.assertEqual(doc.state, 'sent')
        doc._kep_portal_sign(base64.b64encode(sign(PDF, self.customer_key)).decode())
        self.assertEqual(doc.state, 'signing')
        self.assertTrue(doc.can_sign)  # our turn
        doc.kep_submit_signed({'document': base64.b64encode(sign(PDF, self.director)).decode()})
        self.assertEqual(doc.state, 'signed')

    def test_the_key_must_be_of_the_right_party(self):
        doc = self._outgoing()
        with self.assertRaises(UserError):  # not the company's key
            doc._kep_add_signature_b64(base64.b64encode(sign(PDF, self.customer_key)).decode(), expect='own')
        with self.assertRaises(UserError):  # the company's key on the counterparty's link
            doc._kep_portal_sign(base64.b64encode(sign(PDF, self.director)).decode())
        with self.assertRaises(UserError):  # not the counterparty of the document
            doc._kep_portal_sign(base64.b64encode(sign(PDF, self.stranger)).decode())
        with self.assertRaises(UserError):  # not a signature
            doc._kep_add_signature(b'garbage')
        self.assertFalse(doc.kep_signature_ids)

    def test_the_same_signature_is_taken_once(self):
        doc = self._outgoing()
        signature = sign(PDF, self.director)
        doc._kep_add_signature(signature)
        doc._kep_add_signature(signature)
        self.assertEqual(len(doc.kep_signature_ids), 1)

    def test_an_invalid_signature_does_not_count(self):
        doc = self._outgoing()
        doc._kep_add_signature(sign(PDF, self.director))
        doc._kep_portal_sign(base64.b64encode(sign(PDF, self.customer_key)).decode())
        self.assertEqual(doc.state, 'signed')
        theirs = doc.kep_signature_ids.filtered(lambda s: s.party == 'recipient')
        ours = doc.kep_signature_ids - theirs
        doc.kep_store_verification([
            {'id': ours.id, 'valid': True},
            {'id': theirs.id, 'valid': False, 'error': 'Підпис не відповідає даним'}])
        self.assertEqual((ours.verification, theirs.verification), ('valid', 'invalid'))
        self.assertEqual(doc.state, 'signed_owner')
        self.assertEqual(doc.kep_invalid_count, 1)

    def test_rejected_on_the_portal(self):
        doc = self._outgoing()
        doc._kep_reject('Не та сума', by_counterparty=True)
        self.assertEqual(doc.state, 'rejected')
        self.assertFalse(doc._kep_can_sign_their())
        self.assertEqual(doc.kep_reject_reason, 'Не та сума')

    def test_answer_by_e_mail_with_the_signature(self):
        doc = self._outgoing()
        doc._kep_add_signature(sign(PDF, self.director))
        doc.message_update({'attachments': [
            self.env['mail.thread']._Attachment('Akt_7.pdf.p7s', sign(PDF, self.customer_key), {})]})
        self.assertEqual(doc.state, 'signed')

    def test_attached_signature_of_another_file_is_refused(self):
        doc = self._outgoing()
        with self.assertRaises(UserError):
            doc._kep_add_signature(sign(b'other file', self.customer_key, attached=True), attached=True)

    # ── Incoming by e-mail ──────────────────────────────────

    def _receive(self, attachments, subject='Акт за жовтень'):
        if not self.account.alias_name:
            domain = self.env['mail.alias.domain'].search([('name', '=', 'edo.test.example')]) \
                or self.env['mail.alias.domain'].create({'name': 'edo.test.example'})
            self.account.write({'alias_name': 'edo', 'alias_domain_id': domain.id})
        message = EmailMessage()
        message['From'] = 'Покупець <buh@customer.example>'
        message['To'] = 'edo@edo.test.example'
        message['Subject'] = subject
        message['Message-Id'] = f'<{subject.encode().hex()}@customer.example>'
        message.set_content('Підписаний документ у вкладенні.')
        for name, content in attachments:
            message.add_attachment(content, maintype='application', subtype='octet-stream', filename=name)
        doc_id = self.env['mail.thread'].message_process(False, message.as_string())
        return self.env['l10n_ua.edo.document'].browse(doc_id)

    def test_incoming_original_with_its_signatures(self):
        doc = self._receive([('Akt_15.pdf', PDF), ('Akt_15.pdf.p7s', sign(PDF, self.customer_key)),
                             ('Akt_15.pdf.seal.p7s', sign(PDF, self.customer_seal))])
        self.assertEqual((doc.direction, doc.account_id, doc.name), ('in', self.account, 'Akt_15'))
        self.assertEqual(doc.attachment_id.raw, PDF)
        self.assertEqual(doc.counterparty_edrpou, '22222221')
        self.assertEqual(doc.kep_recipient_emails, 'buh@customer.example')
        if 'edrpou' in self.customer._fields:
            self.assertEqual(doc.partner_id, self.customer)
        self.assertEqual(len(doc.kep_signature_ids), 2)
        self.assertEqual(set(doc.kep_signature_ids.mapped('party')), {'owner'})
        self.assertEqual(doc.state, 'signed_owner')
        self.assertTrue(doc.can_sign)
        # We countersign: the archive goes back to the sender
        doc.kep_submit_signed({'document': base64.b64encode(sign(PDF, self.director)).decode()})
        self.assertEqual(doc.state, 'signed')
        mail = self._mails(doc).filtered(lambda m: m.attachment_ids)
        self.assertIn('buh@customer.example', mail.email_to)
        self.assertEqual(len(self._zip_names(doc.archive_attachment_id)), 5)

    def test_incoming_archive_of_a_service_and_an_attached_signature(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('Rakhunok 45.pdf', PDF)
            z.writestr('Rakhunok 45. Pidpys 22222221.p7s', sign(PDF, self.customer_key))
            z.writestr('Kvytantsiia.pdf', b'%PDF receipt')
            z.writestr('Instruktsiia.pdf', b'%PDF instruction')
        doc = self._receive([('Rakhunok 45.zip', archive.getvalue())], subject='Рахунок 45')
        self.assertEqual((doc.name, doc.attachment_id.name), ('Rakhunok 45', 'Rakhunok 45.pdf'))
        self.assertEqual(len(doc.kep_signature_ids), 1)

        doc = self._receive([('Dohovir.pdf.p7s', sign(PDF, self.customer_key, attached=True))],
                            subject='Договір')
        self.assertEqual((doc.attachment_id.name, doc.attachment_id.raw), ('Dohovir.pdf', PDF))
        self.assertTrue(doc.kep_signature_ids.attached)

    def test_message_without_a_signed_document(self):
        doc = self._receive([('photo.jpg', b'\xff\xd8\xff')], subject='Просто лист')
        self.assertEqual(doc.direction, 'in')
        self.assertFalse(doc.kep_signature_ids)


@tagged('post_install', '-at_install', 'l10n_ua_edo')
class TestKepPortal(HttpCase):

    def test_portal_page_needs_the_token(self):
        account = self.env['l10n_ua.edo.account'].create({
            'name': 'КЕП', 'provider': 'kep', 'edrpou': '11111116'})
        doc = self.env['l10n_ua.edo.document'].create({
            'name': 'Акт № 9', 'account_id': account.id, 'direction': 'out', 'provider_ref': 'kep-9',
            'kep_recipient_emails': 'buh@customer.example'})
        doc.attachment_id = self.env['ir.attachment'].create({
            'name': 'Akt_9.pdf', 'raw': PDF, 'res_model': doc._name, 'res_id': doc.id})
        url = doc.get_portal_url()
        page = self.url_open(url)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Акт № 9', page.text)
        self.assertIn('o_kep_sign_card', page.text)
        self.assertEqual(self.url_open(f'/my/edo/{doc.id}').status_code, 404)
        self.assertEqual(self.url_open(f'/my/edo/{doc.id}?access_token=wrong').status_code, 404)
        original = self.url_open(f'/my/edo/{doc.id}/file/original?access_token={doc.access_token}')
        self.assertEqual(original.content, PDF)
        proxy = self.url_open(f'/l10n_ua_edo_kep/ca_proxy/{doc.id}/wrong?address=ca.tax.gov.ua/x',
                              data=b'')
        self.assertEqual(proxy.status_code, 403)
