"""Tests for the pure-Python DBF reader."""
import struct
from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.addons.l10n_ua_budget_treasury_dbf.models.dbf_reader import read_dbf_records


def _build_minimal_dbf(encoding='cp866'):
    """Construct a tiny DBase III file in memory with 2 records for testing."""
    # Field names must fit into the 11-byte slot (name + NULL terminator).
    fields = [
        (b'DOC_NUM', b'C', 10, 0),
        (b'DOC_DATE', b'D', 8, 0),
        (b'SUM_', b'N', 12, 2),
        (b'NAZ_PRIZ', b'C', 40, 0),
    ]
    n_fields = len(fields)
    header_len = 32 + 32 * n_fields + 1  # header + descriptors + terminator
    record_len = 1 + sum(f[2] for f in fields)
    n_records = 2

    # Header
    today = date.today()
    hdr = bytearray(32)
    hdr[0] = 0x03  # DBase III
    hdr[1] = today.year - 1900
    hdr[2] = today.month
    hdr[3] = today.day
    hdr[4:8] = struct.pack('<I', n_records)
    hdr[8:10] = struct.pack('<H', header_len)
    hdr[10:12] = struct.pack('<H', record_len)

    # Field descriptors
    descriptors = bytearray()
    for name, ftype, length, dec in fields:
        d = bytearray(32)
        # name field is 11 bytes: name + NULL padding (no resize)
        padded_name = name.ljust(11, b'\x00')[:11]
        d[0:11] = padded_name
        d[11] = ftype[0]
        d[16] = length
        d[17] = dec
        descriptors.extend(d)
    descriptors.append(0x0D)  # terminator

    # Records (active = 0x20)
    def encode_field(value, ftype, length):
        if ftype == b'C':
            s = value.encode(encoding, errors='replace')
            return s[:length].ljust(length, b' ')
        if ftype == b'N':
            s = f'{value:.2f}'.encode('ascii')
            return s[:length].rjust(length, b' ')
        if ftype == b'D':
            s = value.strftime('%Y%m%d').encode('ascii')
            return s[:length].ljust(length, b' ')
        return b' ' * length

    records_data = bytearray()
    # ASCII purposes in the test to avoid encoding-specific complications;
    # real ДКСУ DBFs commonly use cp866 (Russian DOS) or cp1251 (Windows Cyrillic).
    rows = [
        ('PD000001', date(2025, 1, 10), 1500.50, 'Salary Jan 2025'),
        ('PD000002', date(2025, 1, 11), 250.00,  'Office supplies'),
    ]
    for num, dt, amt, prz in rows:
        rec = bytearray(b' ')  # active marker
        rec.extend(encode_field(num, b'C', 10))
        rec.extend(encode_field(dt, b'D', 8))
        rec.extend(encode_field(amt, b'N', 12))
        rec.extend(encode_field(prz, b'C', 40))
        records_data.extend(rec)
    records_data.append(0x1A)  # EOF

    return bytes(hdr) + bytes(descriptors) + bytes(records_data)


@tagged('post_install', '-at_install', 'l10n_ua_budget_treasury_dbf')
class TestDbfReader(TransactionCase):

    def test_read_minimal_dbf(self):
        dbf = _build_minimal_dbf()
        rows = list(read_dbf_records(dbf))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['DOC_NUM'], 'PD000001')
        self.assertEqual(rows[0]['DOC_DATE'], date(2025, 1, 10))
        self.assertAlmostEqual(rows[0]['SUM_'], 1500.50)
        self.assertIn('Salary', rows[0]['NAZ_PRIZ'])

    def test_short_file_rejected(self):
        from odoo.addons.l10n_ua_budget_treasury_dbf.models.dbf_reader import DbfReadError
        with self.assertRaises(DbfReadError):
            list(read_dbf_records(b'short'))

    def test_eof_marker_terminates(self):
        # Truncated file (no records, just header) — should yield nothing
        dbf = _build_minimal_dbf()
        # Cut after header — no records left
        header_len = struct.unpack('<H', dbf[8:10])[0]
        truncated = dbf[:header_len] + bytes([0x1A])
        # n_records is still 2 in the header, but body is empty after EOF marker
        rows = list(read_dbf_records(truncated))
        self.assertEqual(rows, [])


@tagged('post_install', '-at_install', 'l10n_ua_budget_treasury_dbf')
class TestDbfWizardIntegration(TransactionCase):

    def test_custom_parse_with_dbf(self):
        """End-to-end: wizard with file_format='custom' parses DBF and creates statement lines."""
        import base64
        dbf = _build_minimal_dbf()
        company = self.env.company
        journal = self.env['account.journal'].create({
            'name': 'TEST DBF', 'type': 'bank', 'code': 'TDBF',
            'company_id': company.id, 'ua_is_treasury': True,
            'ua_treasury_check_limit': False,
        })
        # The wizard decodes the file using `encoding` and then re-encodes in
        # `_parse_custom`. Pass the raw bytes through latin-1 round-trip.
        b64 = base64.b64encode(dbf).decode()
        wizard = self.env['l10n_ua.treasury.statement.import'].create({
            'journal_id': journal.id,
            'file': b64,
            'filename': 'demo.dbf',
            'file_format': 'custom',
            'encoding': 'cp866',
        })
        result = wizard.action_import()
        self.assertEqual(result['res_model'], 'account.bank.statement')
        statement = self.env['account.bank.statement'].browse(result['res_id'])
        self.assertEqual(statement.journal_id, journal)
        self.assertEqual(len(statement.line_ids), 2)
