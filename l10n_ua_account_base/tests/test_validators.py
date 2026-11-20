"""Tests for Ukrainian validators (EDRPOU, IPN, IBAN)."""

from odoo.tests import TransactionCase

from ..tools.validators import (
    validate_edrpou,
    validate_ipn,
    validate_iban_ua,
    validate_passport,
)


class TestValidateEdrpou(TransactionCase):
    """Test cases for EDRPOU validation."""

    def test_valid_edrpou_regular(self):
        """Test valid EDRPOU codes (regular range)."""
        # Well-known valid EDRPOU codes
        valid_codes = [
            '00032129',  # Національний банк України
            '00032112',  # Верховна Рада України
            '14360570',  # ПриватБанк
            '21133352',  # monobank (Universal Bank)
            '37193071',  # Розетка (Rozetka.UA)
            '20953647',  # Нова Пошта
        ]
        for code in valid_codes:
            is_valid, error = validate_edrpou(code)
            self.assertTrue(is_valid, f'EDRPOU {code} should be valid: {error}')

    def test_valid_edrpou_special_range(self):
        """Test valid EDRPOU codes in 30-60 million range."""
        # Codes in the special range use different weights
        valid_codes = [
            '32352228',  # Example in 30-60M range
            '40075815',  # Example in 30-60M range
        ]
        for code in valid_codes:
            is_valid, error = validate_edrpou(code)
            self.assertTrue(is_valid, f'EDRPOU {code} should be valid: {error}')

    def test_invalid_edrpou_wrong_checksum(self):
        """Test EDRPOU with wrong checksum."""
        invalid_codes = [
            '00032121',  # Wrong checksum
            '14360571',  # Wrong checksum
        ]
        for code in invalid_codes:
            is_valid, error = validate_edrpou(code)
            self.assertFalse(is_valid, f'EDRPOU {code} should be invalid')
            self.assertIn('checksum', error.lower())

    def test_invalid_edrpou_format(self):
        """Test EDRPOU with invalid format."""
        invalid_codes = [
            '',          # Empty
            '1234567',   # Too short (7 digits)
            '123456789', # Too long (9 digits)
            'ABCDEFGH',  # Letters
            '1234567A',  # Mixed
            '1234 567',  # With space
        ]
        for code in invalid_codes:
            is_valid, error = validate_edrpou(code)
            self.assertFalse(is_valid, f'EDRPOU {code!r} should be invalid')

    def test_edrpou_whitespace_handling(self):
        """Test EDRPOU with leading/trailing whitespace."""
        is_valid, _ = validate_edrpou('  00032129  ')
        self.assertTrue(is_valid, 'Should handle whitespace')


class TestValidateIpn(TransactionCase):
    """Test cases for IPN/RNOKPP validation."""

    def test_valid_ipn(self):
        """Test valid IPN codes."""
        # Test IPN codes (generated according to algorithm)
        valid_codes = [
            '2222222225',  # Test code
            '3333333332',  # Test code
        ]
        for code in valid_codes:
            is_valid, error = validate_ipn(code)
            self.assertTrue(is_valid, f'IPN {code} should be valid: {error}')

    def test_valid_vat_ipn_12_digits(self):
        """ІПН платника ПДВ — 12 цифр, без контрольної суми РНОКПП."""
        is_valid, error = validate_ipn('123456789012')
        self.assertTrue(is_valid, error)

    def test_invalid_ipn_wrong_checksum(self):
        """Test IPN with wrong checksum."""
        invalid_codes = [
            '2222222220',  # Wrong checksum
            '3333333330',  # Wrong checksum
        ]
        for code in invalid_codes:
            is_valid, error = validate_ipn(code)
            self.assertFalse(is_valid, f'IPN {code} should be invalid')
            self.assertIn('checksum', error.lower())

    def test_invalid_ipn_format(self):
        """Test IPN with invalid format."""
        invalid_codes = [
            '',           # Empty
            '123456789',  # Too short (9 digits)
            '12345678901', # 11 digits
            '1234567890123',  # 13 digits
            'ABCDEFGHIJ', # Letters
            '123456789A', # Mixed
        ]
        for code in invalid_codes:
            is_valid, error = validate_ipn(code)
            self.assertFalse(is_valid, f'IPN {code!r} should be invalid')

    def test_ipn_whitespace_handling(self):
        """Test IPN with leading/trailing whitespace."""
        is_valid, _ = validate_ipn('  2222222225  ')
        self.assertTrue(is_valid, 'Should handle whitespace')


class TestValidateIbanUa(TransactionCase):
    """Test cases for Ukrainian IBAN validation."""

    def test_valid_iban(self):
        """Test valid Ukrainian IBAN."""
        valid_ibans = [
            'UA213223130000026007233566001',  # Valid IBAN
            'UA 21 3223 1300 0002 6007 2335 6600 1',  # With spaces
            'ua213223130000026007233566001',  # Lowercase
        ]
        for iban in valid_ibans:
            is_valid, error = validate_iban_ua(iban)
            self.assertTrue(is_valid, f'IBAN {iban} should be valid: {error}')

    def test_invalid_iban_wrong_country(self):
        """Test IBAN with wrong country code."""
        invalid_ibans = [
            'DE89370400440532013000',  # German IBAN
            'GB82WEST12345698765432',  # UK IBAN
        ]
        for iban in invalid_ibans:
            is_valid, error = validate_iban_ua(iban)
            self.assertFalse(is_valid, f'IBAN {iban} should be invalid')
            self.assertIn('UA', error)

    def test_invalid_iban_wrong_length(self):
        """Test IBAN with wrong length."""
        invalid_ibans = [
            'UA2132231300000260072335660',    # Too short (28 chars)
            'UA21322313000002600723356600123', # Too long (31 chars)
        ]
        for iban in invalid_ibans:
            is_valid, error = validate_iban_ua(iban)
            self.assertFalse(is_valid, f'IBAN {iban} should be invalid')
            self.assertIn('29', error)

    def test_invalid_iban_wrong_checksum(self):
        """Test IBAN with wrong checksum."""
        is_valid, error = validate_iban_ua('UA213223130000026007233566099')
        self.assertFalse(is_valid)
        self.assertIn('checksum', error.lower())

    def test_invalid_iban_format(self):
        """Test IBAN with invalid format."""
        invalid_ibans = [
            '',           # Empty
            'UA12345',    # Too short
            'UAABCDEFGHIJKLMNOPQRSTUVWXYZ',  # Letters instead of digits
        ]
        for iban in invalid_ibans:
            is_valid, error = validate_iban_ua(iban)
            self.assertFalse(is_valid, f'IBAN {iban!r} should be invalid')


class TestValidatePassport(TransactionCase):
    """Test cases for Ukrainian passport validation."""

    def test_valid_passport(self):
        """Test valid passport series and number."""
        valid_passports = [
            ('АА', '123456'),
            ('СН', '999999'),
            ('МН', '000001'),
        ]
        for series, number in valid_passports:
            is_valid, error = validate_passport(series, number)
            self.assertTrue(is_valid, f'Passport {series}{number} should be valid: {error}')

    def test_invalid_passport_series(self):
        """Test passport with invalid series."""
        invalid_series = [
            'A',      # Too short
            'AAA',    # Too long
            'AB',     # Latin letters
            '12',     # Digits
        ]
        for series in invalid_series:
            is_valid, error = validate_passport(series, '123456')
            self.assertFalse(is_valid, f'Passport series {series!r} should be invalid')

    def test_invalid_passport_number(self):
        """Test passport with invalid number."""
        invalid_numbers = [
            '12345',    # Too short (5 digits)
            '1234567',  # Too long (7 digits)
            'ABCDEF',   # Letters
        ]
        for number in invalid_numbers:
            is_valid, error = validate_passport('АА', number)
            self.assertFalse(is_valid, f'Passport number {number!r} should be invalid')

    def test_passport_optional_fields(self):
        """Test that passport fields are optional."""
        is_valid, _ = validate_passport('', '')
        self.assertTrue(is_valid, 'Empty passport should be valid (optional)')

        is_valid, _ = validate_passport('АА', '')
        self.assertTrue(is_valid, 'Passport with only series should be valid')

        is_valid, _ = validate_passport('', '123456')
        self.assertTrue(is_valid, 'Passport with only number should be valid')
