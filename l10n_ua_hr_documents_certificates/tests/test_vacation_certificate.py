"""The remaining vacation certificate, issued from the employee's
"New Certificate" button like any other certificate.

The vacation comes from l10n_ua_hr_holidays, which this module does not
depend on, so the suite is skipped without it."""

from datetime import date

from unittest import SkipTest

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVacationCertificate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'hr.vacation.entitlement' not in cls.env:
            raise SkipTest('l10n_ua_hr_holidays is not installed')
        # Public holidays are working days under martial law.
        cls.env['resource.calendar.leaves'].search([('resource_id', '=', False)]).unlink()
        cls.basic = cls.env.ref('l10n_ua_hr_holidays.leave_type_annual_basic')
        cls.cert_type = cls.env.ref(
            'l10n_ua_hr_documents_certificates.certificate_type_vacation_remaining')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Certificate Test Employee',
            'hire_date': date(2024, 3, 1),
        })
        version = cls.employee.with_context(active_test=False).version_ids[:1]
        if version:
            version.write({'contract_date_start': date(2024, 3, 1), 'contract_date_end': False})
        cls.env['hr.vacation.balance'].create({
            'employee_id': cls.employee.id,
            'leave_type_id': cls.basic.id,
            'period_start': date(2026, 3, 1),
            'period_end': date(2027, 2, 28),
            'entitled_days': 24,
        })

    def _certificate(self, as_of):
        certificate = self.env['hr.certificate'].create({
            'employee_id': self.employee.id,
            'certificate_type_id': self.cert_type.id,
            'vacation_as_of': as_of,
        })
        certificate.action_load_template()
        return certificate

    def test_type_is_offered_with_the_other_certificates(self):
        """The type is one of the certificate types the "New Certificate"
        form offers, and only it shows the "As of" date."""
        self.assertIn(self.cert_type, self.env['hr.certificate.type'].search([]))
        # Shared by every company, so each one offers it.
        self.assertFalse(self.cert_type.company_id)
        certificate = self._certificate(date(2026, 4, 15))
        self.assertTrue(certificate.is_vacation_remaining)
        other = self.env['hr.certificate'].new({
            'certificate_type_id': self.env.ref(
                'l10n_ua_hr_documents_certificates.certificate_type_employment').id,
        })
        self.assertFalse(other.is_vacation_remaining)

    def test_body_lists_the_vacation_as_of_the_date(self):
        """The body quotes the leave type, the date and both totals:
        72 days that may be taken, 52 earned (24 + 24 + 24 × 46 / 365 = 51.02,
        rounded up)."""
        certificate = self._certificate(date(2026, 4, 15))
        body = certificate.body
        self.assertIn(self.basic.name, body)
        self.assertIn('15.04.2026', body)
        self.assertIn('<strong>72</strong>', body)
        self.assertIn('<strong>52</strong>', body)
        self.assertIn(certificate.name, body)

    def test_changing_the_date_renders_the_body_again(self):
        certificate = self._certificate(date(2026, 4, 15))
        certificate.vacation_as_of = date(2026, 10, 16)
        certificate.action_load_template()
        self.assertIn('16.10.2026', certificate.body)

    def test_signers_are_printed_under_their_job_positions(self):
        company = self.employee.company_id
        hr_job = self.env['hr.job'].create({'name': 'HR Inspector (certificate test)'})
        accountant_job = self.env['hr.job'].create({'name': 'Accountant (certificate test)'})
        company.hr_manager_id = self.env['hr.employee'].create({
            'name': 'HR Signer (certificate test)', 'job_id': hr_job.id})
        company.accountant_id = self.env['hr.employee'].create({
            'name': 'Accountant Signer (certificate test)', 'job_id': accountant_job.id})
        body = self._certificate(date(2026, 4, 15)).body
        for text in ('HR Inspector (certificate test)', 'HR Signer (certificate test)',
                     'Accountant (certificate test)', 'Accountant Signer (certificate test)'):
            self.assertIn(text, body)

    def test_place_has_one_settlement_prefix(self):
        """The place is printed with "м." once, whether or not the company's
        city already carries it, and without a trailing comma."""
        certificate = self._certificate(date(2026, 4, 15))
        company = certificate.company_id
        for city, place in (('м. Миргород, Полтавська обл.,', 'м. Миргород, Полтавська обл.'),
                            ('Миргород', 'м. Миргород'),
                            ('смт Гадяч', 'смт Гадяч'),
                            (False, '')):
            with self.subTest(city=city):
                company.city = city
                self.assertEqual(certificate._vacation_certificate_place(), place)

    def test_certificate_prints_with_one_header(self):
        """The printed certificate carries the body's own header only: the
        company name appears once, with no company document layout."""
        certificate = self._certificate(date(2026, 4, 15))
        action = certificate.action_print()
        self.assertEqual(action['type'], 'ir.actions.report')
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_hr_documents_certificates.report_hr_certificate', certificate.ids)[0]
        html = html.decode() if isinstance(html, bytes) else html
        self.assertIn('<strong>72</strong>', html)
        self.assertEqual(html.count(certificate.company_id.name), 1)
        self.assertNotIn('o_report_layout', html)
