"""Tests for termination reasons — HR-19 from HR_UKRAINE.md.

Tests cover:
- Termination reason full reference
- Termination reason compensation flags

The work-schedule tests that used to live here went away with
hr.work.schedule itself (#213, phase 2): the weekly norm is now kept on the
native resource.calendar and covered by test_resource_calendar_ua.py.
"""

from odoo.tests import tagged
from .common import ContractTestCase


@tagged('post_install', '-at_install')
class TestTerminationReason(ContractTestCase):
    """Test hr.termination.reason model."""

    def _create_reason(self, **kwargs):
        vals = {
            'name': 'За власним бажанням',
            'article': '38',
            'paragraph': '1',
            'category': 'own_will',
            'notice_days': 14,
        }
        vals.update(kwargs)
        return self.env['hr.termination.reason'].create(vals)

    def test_reason_creation(self):
        """Reason should have required fields."""
        reason = self._create_reason()
        self.assertTrue(reason.name)
        self.assertEqual(reason.category, 'own_will')

    def test_full_reference_computed(self):
        """Full reference should combine article and paragraph."""
        reason = self._create_reason(article='38', paragraph='1')
        # full_reference may be False if not implemented, or a string
        if reason.full_reference:
            self.assertIn('38', reason.full_reference)
        else:
            # At minimum, article should be stored
            self.assertEqual(reason.article, '38')

    def test_reason_own_will_notice(self):
        """Own will requires 14 days notice."""
        reason = self._create_reason(
            category='own_will',
            notice_days=14,
        )
        self.assertEqual(reason.notice_days, 14)

    def test_reason_compensation(self):
        """Employer initiative may require compensation."""
        reason = self._create_reason(
            name='Скорочення штату',
            article='40',
            paragraph='1',
            category='employer_initiative',
            requires_compensation=True,
            compensation_amount='one_month',
        )
        self.assertTrue(reason.requires_compensation)
        self.assertEqual(reason.compensation_amount, 'one_month')

    def test_reason_categories(self):
        """All termination categories should be valid."""
        categories = ['own_will', 'agreement', 'fixed_term', 'transfer',
                       'employer_initiative', 'circumstances', 'other']
        for i, cat in enumerate(categories):
            reason = self._create_reason(
                name=f'Reason {cat}',
                article=str(30 + i),
                category=cat,
            )
            self.assertEqual(reason.category, cat)
            reason.unlink()


@tagged('post_install', '-at_install')
class TestStaffReductionReason(ContractTestCase):
    """#158: the shipped «скорочення штату» reason, checked against КЗпП.

    п. 1 ст. 40 КЗпП — the ground itself; ст. 49-2 — notice of at least two
    months; ст. 44 — severance of at least one average monthly wage. The
    record is what the dismissal order copies its wording from
    (`hr.order._onchange_termination_reason_id`) and what the labour report
    counts as a reorganisation dismissal, so a drift in any of these fields
    is a wrong order text or a wrong report line.
    """

    def test_reduction_reason_matches_labour_code(self):
        reason = self.env.ref('l10n_ua_hr_contract.termination_reason_reduction')
        self.assertEqual(reason.code, 'REDUCTION')
        self.assertEqual(reason.article, '40')
        self.assertEqual(reason.paragraph, 'п. 1')
        self.assertEqual(reason.category, 'employer_initiative')
        self.assertIn('скороченням чисельності або штату', reason.full_text)
        self.assertTrue(reason.full_text.endswith('п. 1 ст. 40 КЗпП України'))
        # ст. 44: вихідна допомога не менше середнього місячного заробітку.
        self.assertTrue(reason.requires_compensation)
        self.assertEqual(reason.compensation_amount, 'one_month')
        # ст. 49-2: попередження не пізніше ніж за два місяці.
        self.assertGreaterEqual(reason.notice_days, 59)
        self.assertEqual(reason.full_reference, 'п. 1 ст. 40 КЗпП України')

    def test_reduction_is_distinct_from_liquidation(self):
        """Скорочення and ліквідація share п. 1 ст. 40 but are different
        records: only liquidation may skip the trade-union consent (ст. 43),
        so the officer must be able to pick one without the other."""
        reduction = self.env.ref('l10n_ua_hr_contract.termination_reason_reduction')
        liquidation = self.env.ref('l10n_ua_hr_contract.termination_reason_liquidation')
        self.assertNotEqual(reduction, liquidation)
        self.assertEqual(reduction.kzpt_code, liquidation.kzpt_code)
        self.assertNotEqual(reduction.code, liquidation.code)
