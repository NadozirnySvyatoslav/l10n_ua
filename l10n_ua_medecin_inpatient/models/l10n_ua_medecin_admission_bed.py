from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class L10nUaMedecinAdmission(models.Model):
    """Ліжко і переведення між відділеннями для епізоду стаціонару (#227)."""
    _inherit = 'l10n_ua.medecin.admission'

    bed_id = fields.Many2one(
        'l10n_ua.medecin.bed', string='Ліжко', ondelete='restrict',
        tracking=True, index=True, check_company=True, copy=False,
        domain="[('department_id', '=', department_id), ('is_occupied', '=', False)]")
    transfer_ids = fields.One2many(
        'l10n_ua.medecin.admission.transfer', 'admission_id',
        string='Переведення між відділеннями', copy=False)
    transfer_count = fields.Integer(compute='_compute_transfer_count')

    @api.depends('transfer_ids')
    def _compute_transfer_count(self):
        for rec in self:
            rec.transfer_count = len(rec.transfer_ids)

    @api.onchange('department_id')
    def _onchange_department_id_bed(self):
        if self.bed_id and self.bed_id.department_id != self.department_id:
            self.bed_id = False

    def _get_department_stays(self):
        """Перебування у відділеннях: [(відділення, початок, кінець, подія_входу, подія_виходу)].

        Початок/кінець — UTC naive; кінець = False, поки пацієнт не вибув.
        Подія входу: 'admitted' (госпіталізація) або 'transferred_in';
        виходу: 'transferred_out', 'discharged' (живим) або 'died'.
        """
        self.ensure_one()
        transfers = self.transfer_ids.sorted(lambda t: (t.date, t.id))
        stays = []
        dept = transfers[:1].department_from_id or self.department_id
        start, kind_in = self.date_admission, 'admitted'
        for transfer in transfers:
            stays.append((dept, start, transfer.date, kind_in, 'transferred_out'))
            dept, start, kind_in = transfer.department_to_id, transfer.date, 'transferred_in'
        if self.state == 'discharged':
            kind_out = 'died' if self.discharge_type == 'died' else 'discharged'
            stays.append((dept, start, self.date_discharge, kind_in, kind_out))
        else:
            stays.append((dept, start, False, kind_in, False))
        return stays

    def _check_transfer_chain(self):
        for rec in self:
            transfers = rec.transfer_ids.sorted(lambda t: (t.date, t.id))
            for prev, nxt in zip(transfers, transfers[1:]):
                if nxt.department_from_id != prev.department_to_id:
                    raise ValidationError(_(
                        'Переведення епізоду %s не утворюють послідовний ланцюжок '
                        'відділень (за датами).', rec.display_name))

    @api.constrains('department_id', 'transfer_ids', 'date_discharge', 'state')
    def _check_department_transfers(self):
        for rec in self:
            transfers = rec.transfer_ids.sorted(lambda t: (t.date, t.id))
            if not transfers:
                continue
            if rec.department_id != transfers[-1].department_to_id:
                raise ValidationError(_(
                    'Відділення епізоду %s має збігатися з відділенням останнього '
                    'переведення. Змінюйте відділення через переведення.', rec.display_name))
            if rec.state == 'discharged' and rec.date_discharge < transfers[-1].date:
                raise ValidationError(_(
                    'Дата виписки не може бути раніше останнього переведення (%s).',
                    rec.display_name))

    @api.constrains('bed_id', 'department_id', 'state')
    def _check_bed(self):
        for rec in self.filtered(lambda r: r.bed_id and r.state in ('draft', 'admitted')):
            if rec.bed_id.department_id != rec.department_id:
                raise ValidationError(_(
                    'Ліжко %(bed)s належить іншому відділенню, ніж епізод %(adm)s.',
                    bed=rec.bed_id.display_name, adm=rec.display_name))
            if rec.state == 'admitted' and self.search_count([
                    ('id', '!=', rec.id), ('bed_id', '=', rec.bed_id.id),
                    ('state', '=', 'admitted')]):
                raise ValidationError(_(
                    'Ліжко %s уже зайняте іншим пацієнтом.', rec.bed_id.display_name))

    def action_transfer(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Переведення в інше відділення'),
            'res_model': 'l10n_ua.medecin.admission.transfer',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_admission_id': self.id,
                'default_department_from_id': self.department_id.id,
            },
        }
