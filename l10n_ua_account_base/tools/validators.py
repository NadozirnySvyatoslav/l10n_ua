"""Validators for Ukrainian identification codes."""

import re


def validate_edrpou(code: str) -> tuple[bool, str]:
    """Validate EDRPOU code (8 digits with checksum).
    
    Args:
        code: EDRPOU code to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not code:
        return False, 'EDRPOU code is required'
    
    code = code.strip()
    
    if not re.match(r'^\d{8}$', code):
        return False, 'EDRPOU must be exactly 8 digits'
    
    digits = [int(d) for d in code]
    
    if int(code) < 30000000 or int(code) > 60000000:
        weights1 = [1, 2, 3, 4, 5, 6, 7]
        weights2 = [3, 4, 5, 6, 7, 8, 9]
    else:
        weights1 = [7, 1, 2, 3, 4, 5, 6]
        weights2 = [9, 3, 4, 5, 6, 7, 8]
    
    checksum = sum(d * w for d, w in zip(digits[:7], weights1)) % 11
    
    if checksum >= 10:
        checksum = sum(d * w for d, w in zip(digits[:7], weights2)) % 11
    
    if checksum >= 10:
        checksum = 0
    
    if checksum != digits[7]:
        return False, 'Invalid EDRPOU checksum'
    
    return True, ''


def validate_ipn(code: str) -> tuple[bool, str]:
    """Validate IPN/RNOKPP code: 10-digit RNOKPP (with checksum) or 12-digit VAT IPN.

    Індивідуальний податковий номер платника ПДВ має 12 цифр — без контрольної
    суми РНОКПП; саме його вимагають ПН і додаток Д1 декларації з ПДВ.

    Args:
        code: IPN code to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not code:
        return False, 'IPN code is required'
    
    code = code.strip()

    if re.match(r'^\d{12}$', code):
        return True, ''

    if not re.match(r'^\d{10}$', code):
        return False, 'IPN must be 10 digits (RNOKPP) or 12 digits (VAT IPN)'
    
    digits = [int(d) for d in code]
    
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    checksum = sum(d * w for d, w in zip(digits[:9], weights)) % 11 % 10
    
    if checksum != digits[9]:
        return False, 'Invalid IPN checksum'
    
    return True, ''


def validate_iban_ua(iban: str) -> tuple[bool, str]:
    """Validate Ukrainian IBAN (UA + 27 digits).
    
    Args:
        iban: IBAN to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not iban:
        return False, 'IBAN is required'
    
    iban = iban.strip().upper().replace(' ', '')
    
    if not iban.startswith('UA'):
        return False, 'Ukrainian IBAN must start with UA'
    
    if len(iban) != 29:
        return False, 'Ukrainian IBAN must be 29 characters (UA + 27 digits)'
    
    if not re.match(r'^UA\d{27}$', iban):
        return False, 'Ukrainian IBAN must contain only digits after UA'
    
    rearranged = iban[4:] + iban[:4]
    numeric = ''
    for char in rearranged:
        if char.isdigit():
            numeric += char
        else:
            numeric += str(ord(char) - ord('A') + 10)
    
    if int(numeric) % 97 != 1:
        return False, 'Invalid IBAN checksum'
    
    return True, ''


def validate_passport(series: str, number: str) -> tuple[bool, str]:
    """Validate Ukrainian passport (old format: 2 letters + 6 digits).
    
    Args:
        series: Passport series (2 Cyrillic letters)
        number: Passport number (6 digits)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if series:
        series = series.strip().upper()
        if not re.match(r'^[А-ЯІЇЄҐ]{2}$', series):
            return False, 'Passport series must be 2 Cyrillic letters'
    
    if number:
        number = number.strip()
        if not re.match(r'^\d{6}$', number):
            return False, 'Passport number must be 6 digits'
    
    return True, ''
