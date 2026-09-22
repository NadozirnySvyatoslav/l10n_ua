import logging
from datetime import datetime, timedelta

from lxml import etree

from odoo import models, _
from odoo.exceptions import UserError

from odoo.addons.l10n_ua_supplier_prices_base.tools.transforms import (
    apply_transform, TransformError,
)

_logger = logging.getLogger(__name__)


class L10nUaSupplierPriceImport(models.Model):
    _inherit = 'l10n_ua.supplier.price.import'

    def _do_parse(self):
        self.ensure_one()
        if self.source_id.parser_type == 'xml':
            return self._parse_xml()
        return super()._do_parse()

    def _parse_xml(self):
        self.ensure_one()
        config = self._get_parser_config()
        namespaces = config.get('namespaces') or {}
        forced_encoding = config.get('encoding')

        raw_bytes = self.raw_file.content
        if forced_encoding:
            try:
                raw_bytes = raw_bytes.decode(forced_encoding).encode('utf-8')
                raw_bytes = self._strip_xml_declaration(raw_bytes)
            except UnicodeDecodeError as e:
                raise UserError(_("Cannot decode XML with encoding %(enc)s: %(e)s",
                                  enc=forced_encoding, e=e))

        try:
            root = etree.fromstring(raw_bytes)
        except etree.XMLSyntaxError as e:
            raise UserError(_("Invalid XML: %s") % e)

        mapping = self.source_id.mapping_id
        if not mapping:
            raise UserError(_("Source has no mapping configured."))
        if not mapping.field_ids:
            raise UserError(_("Mapping '%s' has no fields.") % mapping.name)

        record_xpath = mapping.record_path or '.'
        try:
            records = root.xpath(record_xpath, namespaces=namespaces)
        except etree.XPathEvalError as e:
            raise UserError(_("Invalid record_path XPath '%(p)s': %(e)s",
                              p=record_xpath, e=e))
        if not records:
            raise UserError(_(
                "No records found at XPath '%s'. Check mapping configuration.",
            ) % record_xpath)

        deadline = datetime.now() + timedelta(seconds=self.source_id.parse_timeout)
        Line = self.env['l10n_ua.supplier.price.import.line']
        Currency = self.env['res.currency']
        currency_cache = {}
        count = 0

        for sequence, record in enumerate(records, start=10):
            if datetime.now() > deadline:
                raise UserError(_(
                    "Parse timeout (%(t)ss) exceeded after %(n)s records.",
                    t=self.source_id.parse_timeout, n=count,
                ))
            vals = {'import_id': self.id, 'sequence': sequence * 10}
            for field in mapping.field_ids:
                raw_value = self._resolve_xpath(record, field.source_path, namespaces)
                if raw_value is None or raw_value == '':
                    if field.required and not field.default_value:
                        raise UserError(_(
                            "Required field '%(t)s' missing at record %(n)s (xpath: %(p)s)",
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

    def _resolve_xpath(self, record, xpath_expr, namespaces):
        """Виконати XPath і повернути scalar (str/число) або None.

        Підтримуються типові форми:
        - text(): list[str] — беремо перший
        - @attr: list[str]
        - element node: беремо .text
        - string()/число: вже scalar
        """
        if not xpath_expr:
            return None
        try:
            result = record.xpath(xpath_expr, namespaces=namespaces)
        except etree.XPathEvalError as e:
            raise UserError(_("Invalid XPath '%(p)s': %(e)s", p=xpath_expr, e=e))
        if isinstance(result, (str, int, float, bool)):
            return result if result != '' else None
        if isinstance(result, list):
            if not result:
                return None
            first = result[0]
            if isinstance(first, str):
                return first.strip() or None
            if etree.iselement(first):
                return (first.text or '').strip() or None
            return str(first) if first is not None else None
        return None

    def _strip_xml_declaration(self, xml_bytes):
        """Видалити <?xml encoding=...?> заголовок щоб lxml не сваритися
        що encoding не співпадає з buffer."""
        if xml_bytes.startswith(b'<?xml'):
            end = xml_bytes.find(b'?>')
            if end != -1:
                return xml_bytes[end + 2:].lstrip()
        return xml_bytes
