from odoo import fields, models


class L10nUaEdoKepSignature(models.Model):
    """A КЕП signature of an EDO document exchanged without a service."""
    _name = 'l10n_ua.edo.kep.signature'
    _description = 'КЕП Signature of an EDO Document'
    _order = 'signing_time, id'

    document_id = fields.Many2one('l10n_ua.edo.document', required=True, ondelete='cascade', index=True)
    party = fields.Selection(
        [('owner', 'Sender'), ('recipient', 'Recipient')], required=True)
    attachment_id = fields.Many2one('ir.attachment', string='Signature (.p7s)', required=True)
    signer_name = fields.Char(string='Signer', required=True)
    signer_title = fields.Char(string='Position')
    organization = fields.Char()
    drfo = fields.Char(string='РНОКПП')
    edrpou = fields.Char(string='ЄДРПОУ')
    is_stamp = fields.Boolean(string='Seal', help='The key of the organisation, not of a person.')
    issuer = fields.Char(string='Certification Authority')
    cert_serial = fields.Char(string='Certificate Serial Number')
    signing_time = fields.Datetime()
    attached = fields.Boolean(
        string='With the Data', help='The signature carries the signed file (CAdES enveloping).')
    verification = fields.Selection([
        ('pending', 'Not Checked'),
        ('valid', 'Valid'),
        ('invalid', 'Invalid'),
    ], default='pending', required=True,
        help='Checked by the IIT library in the browser of an Odoo user: the signature of the '
             'original file and the certificate of the signer (its chain and status).')
    verified_on = fields.Datetime(string='Checked On')
    verification_error = fields.Char(string='Check Result')

    def _code(self):
        """ЄДРПОУ for a seal or an official of an organisation, РНОКПП for a person."""
        self.ensure_one()
        return self.edrpou or self.drfo or ''

    def _filename(self, base):
        self.ensure_one()
        kind = 'Pechatka' if self.is_stamp else 'Pidpys'
        return f'{base}. {kind} {self._code()}.p7s'.replace('  ', ' ')
