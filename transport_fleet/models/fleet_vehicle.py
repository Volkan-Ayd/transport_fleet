from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    transport_type = fields.Selection([
        ('tractor', 'Çekici (Tır)'),
        ('truck', 'Kamyon'),
        ('light_truck', 'Kamyonet / Panelvan'),
        ('other', 'Diğer'),
    ], string='Taşımacılık Tipi', default='tractor', tracking=True)
    transport_state = fields.Selection([
        ('available', 'Müsait'),
        ('on_trip', 'Seferde'),
        ('maintenance', 'Bakımda'),
        ('breakdown', 'Arızalı'),
    ], string='Operasyon Durumu', default='available', required=True, tracking=True)
    axle_count = fields.Integer(string='Aks Sayısı', default=2)
    max_payload = fields.Float(string='Azami Yük (kg)')
    gross_weight = fields.Float(string='Azami Brüt Ağırlık (kg)')
    fuel_tank_capacity = fields.Float(string='Yakıt Deposu (L)')
    is_adr = fields.Boolean(string='ADR Uygun')
    hgs_tag = fields.Char(string='HGS / OGS No')
    transport_driver_id = fields.Many2one(
        'hr.employee', string='Atanmış Şoför', domain=[('is_driver', '=', True)], tracking=True)
    current_trailer_id = fields.Many2one(
        'transport.trailer', string='Bağlı Dorse', copy=False, tracking=True)
    document_ids = fields.One2many('transport.document', 'vehicle_id', string='Belgeler')
    expiring_document_count = fields.Integer(compute='_compute_expiring_document_count')

    @api.depends('document_ids.status')
    def _compute_expiring_document_count(self):
        for rec in self:
            rec.expiring_document_count = len(
                rec.document_ids.filtered(lambda d: d.status != 'valid'))

    @api.onchange('transport_driver_id')
    def _onchange_transport_driver_id(self):
        contact = self.transport_driver_id.work_contact_id
        if contact:
            self.driver_id = contact

    @api.constrains('current_trailer_id')
    def _check_trailer_unique(self):
        for rec in self.filtered('current_trailer_id'):
            other = self.search([
                ('current_trailer_id', '=', rec.current_trailer_id.id),
                ('id', '!=', rec.id),
            ], limit=1)
            if other:
                raise ValidationError(
                    f'{rec.current_trailer_id.license_plate} dorsesi zaten '
                    f'{other.license_plate} plakalı çekiciye bağlı.')

    def action_view_transport_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Belgeler',
            'res_model': 'transport.document',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id, 'default_owner_type': 'vehicle'},
        }
