import csv
import io
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.l10n_ua_supplier_prices_base.tools.transforms import (
    apply_transform, TransformError,
)

_logger = logging.getLogger(__name__)

FALLBACK_ENCODINGS = ('utf-8-sig', 'windows-1251', 'cp1251', 'latin-1')


class L10nUaSupplierPriceImport(models.Model):
    _inherit = 'l10n_ua.supplier.price.import'

    def _do_parse(self):
        self.ensure_one()
        if self.source_id.parser_type == 'csv':
            return self._parse_csv()
        return super()._do_parse()

    def _parse_csv(self):
        self.ensure_one()
        config = self._get_parser_config()
        delimiter = config.get('delimiter', ',')
        encoding = config.get('encoding', 'utf-8')
        has_header = bool(config.get('has_header', True))
        skip_rows = int(config.get('skip_rows', 0))
        quotechar = config.get('quotechar', '"')

        raw_bytes = self.raw_file.content
        text = self._decode_csv_bytes(raw_bytes, encoding)

        stream = io.StringIO(text)
        for _unused in range(skip_rows):
            if not stream.readline():
                break

        mapping = self.source_id.mapping_id
        if not mapping:
            raise UserError(_("Source has no mapping configured."))
        if not mapping.field_ids:
            raise UserError(_("Mapping '%s' has no fields.") % mapping.name)

        if has_header:
            reader = csv.DictReader(stream, delimiter=delimiter, quotechar=quotechar)
        else:
            reader = csv.reader(stream, delimiter=delimiter, quotechar=quotechar)

        deadline = datetime.now() + timedelta(seconds=self.source_id.parse_timeout)
        Line = self.env['l10n_ua.supplier.price.import.line']
        Currency = self.env['res.currency']
        currency_cache = {}
        count = 0

        for sequence, row in enumerate(reader, start=10):
            if datetime.now() > deadline:
                raise UserError(_(
                    "Parse timeout (%(t)ss) exceeded after %(n)s records.",
                    t=self.source_id.parse_timeout, n=count,
                ))
            vals = {'import_id': self.id, 'sequence': sequence}
            for field in mapping.field_ids:
                raw_value = self._resolve_csv_field(row, field.source_path, has_header)
                if raw_value is None or raw_value == '':
                    if field.required and not field.default_value:
                        raise UserError(_(
                            "Required field '%(t)s' missing at record %(n)s (path: %(p)s)",
                            t=field.target, n=count, p=field.source_path,
                        ))
                    raw_value = field.default_value
                if raw_value is None or raw_value == '':
                    continue
                try:
                    value = apply_transform(raw_value, field.transform, field.transform_param)
                except TransformError as e:
                    raise UserError(_(
                        "Transform error on field '%(t)s' (record %(n)s): %(e)s",
                        t=field.target, n=count, e=str(e),
                    ))
                self._assign_field_value(vals, field.target, value, currency_cache, Currency)

            if not vals.get('supplier_sku'):
                continue
            Line.create(vals)
            count += 1

    def _decode_csv_bytes(self, raw_bytes, encoding):
        """Декодує bytes у str з fallback на популярні кодування."""
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            _logger.info("CSV decode failed with '%s', trying fallbacks", encoding)
        for fallback in FALLBACK_ENCODINGS:
            if fallback == encoding:
                continue
            try:
                text = raw_bytes.decode(fallback)
                _logger.info("CSV decoded with fallback '%s'", fallback)
                return text
            except UnicodeDecodeError:
                continue
        raise UserError(_(
            "Cannot decode CSV file. Tried: %s and fallbacks %s",
        ) % (encoding, ', '.join(FALLBACK_ENCODINGS)))

    def _resolve_csv_field(self, row, source_path, has_header):
        """Отримати значення з рядка CSV за колонкою (назва або індекс)."""
        if not source_path:
            return None
        if has_header:
            return row.get(source_path) if isinstance(row, dict) else None
        if not isinstance(row, list):
            return None
        try:
            idx = int(source_path)
        except (ValueError, TypeError):
            return None
        if -len(row) <= idx < len(row):
            return row[idx]
        return None
