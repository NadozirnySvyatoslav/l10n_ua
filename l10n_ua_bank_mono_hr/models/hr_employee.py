import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# hr.employee document types → monobank DocumentType.
MONO_DOCUMENT_TYPES = {
    'passport': 'OLD_PASSPORT',
    'id_card': 'ID_CARD',
}
# The salary contacts search returns at most this many per page.
MONO_CONTACTS_PAGE = 100


def _clean(value):
    return (value or '').replace(' ', '').upper()


def _split_name(full_name):
    """(last, first, middle) of a Ukrainian full name «Прізвище Ім'я По батькові»."""
    parts = (full_name or '').split()
    return (parts[0] if parts else '',
            parts[1] if len(parts) > 1 else '',
            ' '.join(parts[2:]))


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    l10n_ua_mono_contact_id = fields.Char(
        string='monobank Salary Contact ID', copy=False,
        groups='l10n_ua_hr_base.group_hr_ua_officer',
        help='ID of the employee among the salary contacts of the company in '
             'monobank.')

    def _l10n_ua_mono_identity(self):
        """How monobank identifies the employee: the RNOKPP, or the document
        of someone who refused the number for religious reasons. {} when
        there is neither."""
        self.ensure_one()
        rnokpp = (self.rnokpp or '').strip()
        if rnokpp:
            return {'inn': rnokpp}
        doc_type = MONO_DOCUMENT_TYPES.get(self.document_type)
        number = (self.passport_id or '').strip()
        if not (doc_type and number):
            return {}
        identity = {'documentType': doc_type, 'documentNumber': number}
        if doc_type == 'OLD_PASSPORT' and self.passport_series:
            identity['documentSeries'] = self.passport_series.strip()
        return identity

    def _l10n_ua_mono_identification(self):
        """The single string the payslip API identifies an employee by: the
        RNOKPP, or the passport (series and number)."""
        self.ensure_one()
        identity = self._l10n_ua_mono_identity()
        return identity.get('inn') or '%s%s' % (
            identity.get('documentSeries', ''), identity.get('documentNumber', ''))

    def _l10n_ua_mono_iban(self):
        self.ensure_one()
        return _clean(self.primary_bank_account_id.acc_number)

    @staticmethod
    def _l10n_ua_mono_contact_matches(contact, identity):
        if identity.get('inn'):
            return (contact.get('inn') or '') == identity['inn']
        return (_clean(contact.get('documentNumber')) == _clean(identity.get('documentNumber'))
                and _clean(contact.get('documentSeries')) == _clean(identity.get('documentSeries')))

    def _l10n_ua_mono_find_contact(self, config):
        """The salary contact of the employee in monobank, or None."""
        self.ensure_one()
        identity = self._l10n_ua_mono_identity()
        query = identity.get('inn') or identity.get('documentNumber')
        if not query:
            return None
        offset = 0
        while True:
            page = config._mono_corp_request(
                '/ext/v1/salary-contacts/search',
                params={'query': query, 'limit': MONO_CONTACTS_PAGE, 'offset': offset}) or {}
            for contact in page.get('contacts') or []:
                if self._l10n_ua_mono_contact_matches(contact, identity):
                    return contact
            if not page.get('hasMore'):
                return None
            offset += MONO_CONTACTS_PAGE

    def _l10n_ua_mono_sync_contacts(self, config):
        """Match the employees with the salary contacts in monobank.

        Found ones get their contact ID; missing ones are created; a contact
        whose IBAN differs from the employee's account is reported, not
        overwritten: which one is right is for a person to decide.
        Returns {'found', 'created', 'mismatch', 'failed'}: lists of
        (employee, detail).
        """
        report = {'found': [], 'created': [], 'mismatch': [], 'failed': []}
        for employee in self:
            identity = employee._l10n_ua_mono_identity()
            iban = employee._l10n_ua_mono_iban()
            if not identity:
                report['failed'].append((employee, _('no RNOKPP or passport')))
                continue
            try:
                contact = employee._l10n_ua_mono_find_contact(config)
                if contact:
                    employee.sudo().l10n_ua_mono_contact_id = contact.get('id') or False
                    bank_iban = _clean(contact.get('iban'))
                    if iban and bank_iban and bank_iban != iban:
                        report['mismatch'].append((employee, _(
                            'IBAN in monobank %(bank)s, in Odoo %(odoo)s',
                            bank=bank_iban, odoo=iban)))
                    else:
                        report['found'].append((employee, ''))
                    continue
                if not iban:
                    report['failed'].append((employee, _('no bank account (IBAN)')))
                    continue
                last, first, middle = _split_name(employee.name)
                payload = dict(identity, lastName=last, firstName=first, iban=iban)
                if middle:
                    payload['middleName'] = middle
                result = config._mono_corp_request(
                    '/ext/v1/salary-contacts', method='POST', payload=payload)
                if isinstance(result, dict) and result.get('id'):
                    employee.sudo().l10n_ua_mono_contact_id = result['id']
                report['created'].append((employee, ''))
            except UserError as e:
                report['failed'].append((employee, str(e)))
        return report

    @staticmethod
    def _l10n_ua_mono_contacts_report(report):
        """The sync report as chatter HTML-free text."""
        labels = [
            ('created', _('Created in monobank')),
            ('mismatch', _('IBAN differs')),
            ('failed', _('Not synchronized')),
        ]
        parts = [_('Salary contacts: %(found)d found, %(created)d created, '
                   '%(mismatch)d with another IBAN, %(failed)d failed.',
                   found=len(report['found']), created=len(report['created']),
                   mismatch=len(report['mismatch']), failed=len(report['failed']))]
        for key, label in labels:
            if report[key]:
                parts.append('%s: %s' % (label, '; '.join(
                    employee.name + (' (%s)' % detail if detail else '')
                    for employee, detail in report[key])))
        return '\n'.join(parts)
