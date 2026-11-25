from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportTripAddCargoWizard(models.TransientModel):
    _name = 'transport.trip.add.cargo.wizard'
    _description = 'Sefere Yolda Yeni Müşteri / Araç Ekle'

    trip_id = fields.Many2one('transport.trip', required=True)
    last_odometer = fields.Float(related='trip_id.last_odometer', readonly=True, string='Son Km Okuması')
    odometer = fields.Float(string='Şu Anki Km', required=True)
    lead_id = fields.Many2one('crm.lead', string='Müşteri / Teklif', required=True)
    chassis_ids = fields.Many2many(
        'crm.lead.chassis', string='Yüklenen Araçlar (Şasi No)',
        domain="[('lead_id', '=', lead_id)]")

    @api.onchange('lead_id')
    def _onchange_lead_id(self):
        self.chassis_ids = self.lead_id.transport_chassis_ids

    def action_confirm(self):
        self.ensure_one()
        if not self.odometer:
            raise UserError('Kilometre girilmesi zorunludur.')
        if not self.chassis_ids:
            raise UserError('En az bir şasi numarası seçmelisiniz.')
        self.trip_id._add_cargo(self.lead_id, self.chassis_ids, self.odometer)
        return {'type': 'ir.actions.act_window_close'}
