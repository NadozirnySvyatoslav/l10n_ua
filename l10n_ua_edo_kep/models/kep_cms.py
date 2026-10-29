"""Who signed a detached CAdES signature (.p7s): the signer's certificate.

The signature itself (ДСТУ 4145 with ГОСТ 34.311 or «Купина») cannot be
checked in Python: it is checked by the IIT library in the browser of an Odoo
user (see ``l10n_ua.edo.kep.signature.verification``). Here the certificate
inside the signature only tells whose it is: the name, the РНОКПП
(``TINUA-…`` or the subject directory attributes), the ЄДРПОУ (``NTRUA-…``),
the organisation, the CA, the serial number and the signing time.
"""

import re

from asn1crypto import cms
from asn1crypto.core import Any, ObjectIdentifier, Sequence, SequenceOf, SetOf

# Subject directory attributes (2.5.29.9) of the Ukrainian qualified certificates
OID_DRFO = '1.2.804.2.1.1.1.11.1.4.1.1'
OID_EDRPOU = '1.2.804.2.1.1.1.11.1.4.2.1'
OID_SUBJECT_DIRECTORY = '2.5.29.9'


class KepSignatureError(ValueError):
    """Not a detached CAdES signature with the signer's certificate."""


def _code(value, prefix):
    match = re.fullmatch(rf'{prefix}-?(\d+)', (value or '').strip())
    return match.group(1) if match else False


class _Attribute(Sequence):
    _fields = [('type', ObjectIdentifier), ('values', SetOf, {'spec': Any})]


class _Attributes(SequenceOf):
    _child_spec = _Attribute


def _directory_attributes(tbs):
    """{oid: value} of the subject directory attributes extension."""
    values = {}
    for ext in tbs['extensions'] or []:
        if ext['extn_id'].dotted != OID_SUBJECT_DIRECTORY:
            continue
        try:
            for attr in _Attributes.load(ext['extn_value'].contents):
                for value in attr['values']:
                    text = value.parsed.native if hasattr(value, 'parsed') else None
                    if isinstance(text, str):
                        values[attr['type'].dotted] = text.strip()
        except ValueError:
            continue
    return values


def _load(data):
    try:
        info = cms.ContentInfo.load(data)
        if info['content_type'].native != 'signed_data':
            raise KepSignatureError('not signed data')
        return info['content']
    except (ValueError, TypeError, KeyError) as error:
        raise KepSignatureError(str(error)) from error


def embedded_content(data):
    """The data inside an attached signature (signed «with the data», as on
    id.gov.ua by default), or None for a detached one."""
    signed = _load(data)
    try:
        return signed['encap_content_info']['content'].native
    except (ValueError, TypeError, KeyError) as error:
        raise KepSignatureError(str(error)) from error


def parse_signature(data, attached=False):
    """Signer of a detached signature.

    :param bytes data: DER of the .p7s
    :param bool attached: the signature may carry the data
    :return: dict — signer_name, signer_title, organization, drfo, edrpou,
        is_stamp, issuer, cert_serial, signing_time (naive UTC datetime or False)
    :raise KepSignatureError: not a detached signed-data with its certificate
    """
    signed = _load(data)
    try:
        if not attached and signed['encap_content_info']['content'].native is not None:
            raise KepSignatureError('the signature carries the data: a detached one is expected')
        signer = signed['signer_infos'][0]
        sid = signer['sid']
        certificates = [c.chosen for c in signed['certificates'] or [] if c.name == 'certificate']
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise KepSignatureError(str(error)) from error

    cert = None
    for candidate in certificates:
        tbs = candidate['tbs_certificate']
        if sid.name == 'issuer_and_serial_number':
            if (tbs['serial_number'].native == sid.chosen['serial_number'].native
                    and tbs['issuer'] == sid.chosen['issuer']):
                cert = candidate
                break
        else:
            key_id = candidate.key_identifier
            if key_id and key_id == sid.chosen.native:
                cert = candidate
                break
    if cert is None:
        raise KepSignatureError("the signature has no certificate of the signer")

    tbs = cert['tbs_certificate']
    subject = tbs['subject'].native
    directory = _directory_attributes(tbs)
    drfo = directory.get(OID_DRFO) or _code(subject.get('serial_number'), 'TINUA')
    edrpou = directory.get(OID_EDRPOU) or _code(subject.get('organization_identifier'), 'NTRUA')
    if not drfo and not edrpou and re.fullmatch(r'\d{8}', subject.get('serial_number') or ''):
        edrpou = subject['serial_number']
    person = subject.get('surname') or subject.get('given_name') or drfo

    signing_time = False
    for attr in signer['signed_attrs'] or []:
        if attr['type'].native == 'signing_time':
            signing_time = attr['values'][0].native.replace(tzinfo=None)
    return {
        'signer_name': subject.get('common_name') or '',
        'signer_title': subject.get('title') or False,
        'organization': subject.get('organization_name') or False,
        'drfo': drfo or False,
        'edrpou': edrpou or False,
        'is_stamp': not person,
        'issuer': tbs['issuer'].native.get('common_name') or False,
        'cert_serial': format(tbs['serial_number'].native, 'X'),
        'signing_time': signing_time,
    }
