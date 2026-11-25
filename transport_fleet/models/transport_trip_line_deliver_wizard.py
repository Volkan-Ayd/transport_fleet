from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportTripLineDeliverWizard(models.TransientModel):
    _name = 'transport.trip.line.deliver.wizard'
    _description = 'Araç Teslim Et'

    line_id = fields.Many2one('transport.trip.line', required=True)
    trip_id = fields.Many2one(related='line_id.trip_id', readonly=True)
    chassis_number = fields.Char(related='line_id.chassis_number', readonly=True)
    partner_id = fields.Many2one(related='line_id.partner_id', readonly=True, string='Müşteri')
    pickup_odometer = fields.Float(related='line_id.pickup_odometer', readonly=True, string='Teslim Alma Km')
    last_odometer = fields.Float(related='trip_id.last_odometer', readonly=True, string='Son Km Okuması')
    delivered_odometer = fields.Float(string='Teslim Km', required=True)
    image_ids = fields.Many2many(
        'ir.attachment', string='Fotoğraflar',
        help='Teslim sırasındaki fotoğraflar. Birden fazla fotoğraf eklenebilir.')

    @api.onchange('line_id')
    def _onchange_line_id(self):
        if self.line_id and not self.delivered_odometer:
            self.delivered_odometer = self.line_id.trip_id.last_odometer

    def action_confirm(self):
        self.ensure_one()
        line = self.line_id
        trip = line.trip_id
        if line.delivered:
            raise UserError(f'{line.chassis_number} zaten teslim edilmiş.')
        if not self.delivered_odometer:
            raise UserError('Teslim km girilmesi zorunludur.')
        if self.delivered_odometer < trip.last_odometer:
            raise UserError(
                f'Teslim km, son kayıtlı km ({trip.last_odometer}) değerinden küçük olamaz '
                f'(eşit olabilir).')
        trip._deliver_lines(line, self.delivered_odometer)
        if self.image_ids:
            body = Markup('<b>%s</b> - şasi: %s, teslim km: %s') % (
                self.env._('Araç teslim edildi (fotoğraflı)'), line.chassis_number, self.delivered_odometer)
            if line.partner_id:
                body += Markup(' (%s: %s)') % (self.env._('müşteri'), line.partner_id.name)
            body += Markup('<br/>%s: %s') % (self.env._('Fotoğraf sayısı'), len(self.image_ids))
            trip.message_post(body=body, attachment_ids=self.image_ids.ids)
        return {'type': 'ir.actions.act_window_close'}
