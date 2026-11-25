# -*- coding: utf-8 -*-
"""
Subconto (Субконто) - 1C-style analytical dimensions for Ukrainian accounting.

In 1C, each account can have up to 3-5 "subconto" types that define
what analytical data must be provided for each transaction.

Examples:
- Account 631 (Suppliers): Subconto = [Partner, Contract]
- Account 281 (Goods): Subconto = [Product, Warehouse]
- Account 92 (Admin expenses): Subconto = [Cost Item, Department]
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# Kept in sync with migrations/19.0.1.5.0/pre-migration.py
BASE_SUBCONTO_MODELS = (
    'res.partner',
    'res.partner.bank',
    'account.account',
    'account.journal',
    'product.product',
)


class L10nUaSubcontoType(models.Model):
    """
    Subconto Type (Вид субконто)

    Defines a type of analytical dimension that can be attached to accounts.
    Each type references a specific Odoo model for data.
    """
    _name = 'l10n_ua.subconto.type'
    _description = 'Subconto Type (Вид субконто)'
    _order = 'sequence, name'

    name = fields.Char(
        string='Name',
        required=True,
        translate=True,
    )
    code = fields.Char(
        string='Code',
        required=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # Reference to Odoo model (#701, ADR 0005): a closed list instead of a
    # Many2one to ir.model, so accountants need no access to ir.model and a
    # subconto cannot expose display_name of an arbitrary model.
    model_name = fields.Selection(
        selection='_selection_subconto_models',
        string='Reference Model',
        required=True,
        help='Odoo model that provides values for this subconto type',
    )

    # Display settings
    field_name = fields.Char(
        string='Display Field',
        default='name',
        help='Field to display when showing subconto value',
    )

    description = fields.Text(string='Description')

    _unique_code = models.Constraint(
        'UNIQUE(code)',
        'Subconto type code must be unique!',
    )

    @api.model
    def _selection_subconto_models(self):
        """Models allowed as a subconto dimension, as (model, label) pairs.

        A module bridging another domain (hr, stock, …) extends this list
        the same way it extends account.move.line._subconto_quick_fields_map.
        See l10n_ua_account_subconto_hr for an example.
        """
        # _description needs no ACL, unlike reading ir.model
        return [(name, self.env[name]._description)
                for name in BASE_SUBCONTO_MODELS if name in self.env]

    @api.constrains('model_name')
    def _check_model_name(self):
        # The ORM does not validate stored selection values on write
        allowed = dict(self._selection_subconto_models())
        for rec in self:
            if rec.model_name not in allowed:
                raise ValidationError(_(
                    'Model %(model)s is not allowed as a subconto type.',
                    model=rec.model_name,
                ))


class L10nUaAccountSubconto(models.Model):
    """
    Account Subconto Configuration

    Links subconto types to accounts and defines which subconto
    are required/optional for each account.
    """
    _name = 'l10n_ua.account.subconto'
    _description = 'Account Subconto Configuration'
    _order = 'sequence'

    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
        ondelete='cascade',
    )
    subconto_type_id = fields.Many2one(
        'l10n_ua.subconto.type',
        string='Subconto Type',
        required=True,
        ondelete='restrict',
    )
    sequence = fields.Integer(
        string='Order',
        default=10,
        help='Order of subconto (1st, 2nd, 3rd...)',
    )
    required = fields.Boolean(
        string='Required',
        default=True,
        help='If checked, this subconto must be filled for all transactions',
    )

    _unique_account_subconto = models.Constraint(
        'UNIQUE(account_id, subconto_type_id)',
        'Each subconto type can only be added once per account!',
    )


class AccountAccount(models.Model):
    """Extend account.account with subconto configuration"""
    _inherit = 'account.account'

    subconto_ids = fields.One2many(
        'l10n_ua.account.subconto',
        'account_id',
        string='Subconto Configuration',
        help='Analytical dimensions (субконто) for this account',
    )
    subconto_count = fields.Integer(
        compute='_compute_subconto_count',
        string='Subconto Count',
    )

    @api.depends('subconto_ids')
    def _compute_subconto_count(self):
        for account in self:
            account.subconto_count = len(account.subconto_ids)


class L10nUaMoveLineSubconto(models.Model):
    """
    Subconto values for account move lines.

    Stores the actual subconto values for each journal entry line.
    """
    _name = 'l10n_ua.move.line.subconto'
    _description = 'Move Line Subconto Value'

    move_line_id = fields.Many2one(
        'account.move.line',
        string='Journal Item',
        required=True,
        ondelete='cascade',
    )
    subconto_type_id = fields.Many2one(
        'l10n_ua.subconto.type',
        string='Subconto Type',
        required=True,
        ondelete='restrict',
    )

    # Generic reference to any model
    res_model = fields.Selection(
        string='Model',
        related='subconto_type_id.model_name',
        store=True,
    )
    res_id = fields.Integer(
        string='Record ID',
        required=True,
    )

    # Computed display name
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True,
    )

    @api.depends('res_model', 'res_id', 'subconto_type_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.res_model and rec.res_id:
                try:
                    record = self.env[rec.res_model].browse(rec.res_id)
                    if record.exists():
                        field_name = rec.subconto_type_id.field_name or 'name'
                        rec.display_name = getattr(record, field_name, str(rec.res_id))
                    else:
                        rec.display_name = f'[Deleted: {rec.res_id}]'
                except Exception:
                    rec.display_name = str(rec.res_id)
            else:
                rec.display_name = ''


class AccountMoveLine(models.Model):
    """Extend account.move.line with subconto values"""
    _inherit = 'account.move.line'

    subconto_ids = fields.One2many(
        'l10n_ua.move.line.subconto',
        'move_line_id',
        string='Subconto Values',
    )

    # Quick access fields for common subconto types
    # These are computed from subconto_ids for convenience
    subconto_partner_id = fields.Many2one(
        'res.partner',
        string='Partner (Subconto)',
        compute='_compute_subconto_quick_fields',
        inverse='_inverse_subconto_partner',
        store=True,
    )
    subconto_product_id = fields.Many2one(
        'product.product',
        string='Product (Subconto)',
        compute='_compute_subconto_quick_fields',
        inverse='_inverse_subconto_product',
        store=True,
    )
    def _subconto_quick_fields_map(self):
        """Map a subconto model name to its quick access field on this model.

        A module bridging another domain (hr, stock, …) extends this map instead
        of declaring a Many2one to a model that l10n_ua_account_base does not
        depend on. See l10n_ua_account_subconto_hr for an example.
        """
        return {
            'res.partner': 'subconto_partner_id',
            'product.product': 'subconto_product_id',
        }

    @api.depends('subconto_ids', 'subconto_ids.res_model', 'subconto_ids.res_id')
    def _compute_subconto_quick_fields(self):
        quick_fields = self._subconto_quick_fields_map()
        for line in self:
            for field_name in quick_fields.values():
                line[field_name] = False

            for sub in line.subconto_ids:
                field_name = quick_fields.get(sub.res_model)
                if field_name:
                    line[field_name] = sub.res_id

    def _inverse_subconto_partner(self):
        self._set_subconto_value('res.partner', 'subconto_partner_id')

    def _inverse_subconto_product(self):
        self._set_subconto_value('product.product', 'subconto_product_id')

    def _set_subconto_value(self, model_name, field_name):
        """Helper to set subconto value from quick access field"""
        SubcontoType = self.env['l10n_ua.subconto.type']
        MoveLineSubconto = self.env['l10n_ua.move.line.subconto']

        subconto_type = SubcontoType.search([('model_name', '=', model_name)], limit=1)
        if not subconto_type:
            return

        for line in self:
            value = getattr(line, field_name)
            existing = line.subconto_ids.filtered(
                lambda s: s.subconto_type_id == subconto_type
            )

            if value:
                if existing:
                    existing.write({'res_id': value.id})
                else:
                    MoveLineSubconto.create({
                        'move_line_id': line.id,
                        'subconto_type_id': subconto_type.id,
                        'res_id': value.id,
                    })
            elif existing:
                existing.unlink()

    @api.constrains('account_id', 'subconto_ids')
    def _check_required_subconto(self):
        """Validate that all required subconto are filled"""
        for line in self:
            if not line.account_id or not line.account_id.subconto_ids:
                continue

            for acc_sub in line.account_id.subconto_ids:
                if acc_sub.required:
                    matching = line.subconto_ids.filtered(
                        lambda s: s.subconto_type_id == acc_sub.subconto_type_id
                    )
                    if not matching or not matching.res_id:
                        raise ValidationError(_(
                            'Account %(account)s requires subconto "%(subconto)s" to be filled.',
                            account=line.account_id.display_name,
                            subconto=acc_sub.subconto_type_id.name,
                        ))
