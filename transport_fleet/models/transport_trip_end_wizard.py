from odoo import fields, models
from odoo.exceptions import UserError


class TransportTripEndWizard(models.TransientModel):
    _name = 'transport.trip.end.wizard'
    _description = 'Sefer Durağı / Teslimat Sonlandırma'

    trip_id = fields.Many2one('transport.trip', required=True)
    last_odometer = fields.Float(related='trip_id.last_odometer', readonly=True, string='Son Km Okuması')
    new_odometer = fields.Float(string='Yeni Km', required=True)
    line_ids = fields.Many2many(
        'transport.trip.line', string='Teslim Edilen Araçlar (Şasi No)',
        domain="[('trip_id', '=', trip_id), ('delivered', '=', False)]")

    def action_confirm(self):
        self.ensure_one()
        if not self.new_odometer:
            raise UserError('Yeni kilometre girilmesi zorunludur.')
        if self.new_odometer <= self.trip_id.last_odometer:
            raise UserError(
                f'Yeni km, son kayıtlı km ({self.trip_id.last_odometer}) değerinden büyük olmalıdır.')
        if not self.line_ids:
            raise UserError('Teslim edilen en az bir araç (şasi no) seçmelisiniz.')
        self.trip_id._deliver_lines(self.line_ids, self.new_odometer)
        return {'type': 'ir.actions.act_window_close'}
