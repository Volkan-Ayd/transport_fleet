from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportTripReturnWizard(models.TransientModel):
    _name = 'transport.trip.return.wizard'
    _description = 'Dönüş Tamamlandı'

    trip_id = fields.Many2one('transport.trip', required=True)
    vehicle_id = fields.Many2one('fleet.vehicle', related='trip_id.vehicle_id', readonly=True)
    last_odometer = fields.Float(
        related='trip_id.last_odometer', readonly=True, string='Teslimat Bitişindeki Km')
    return_odometer = fields.Float(
        string='Dönüş Km (Garaja Ulaşıldığında)', required=True,
        help='Araç garaja/depoya boş dönüşle ulaştığındaki kilometresi. Bu bilgiyle boş dönüş '
             'mesafesi hesaplanır.')

    @api.onchange('trip_id')
    def _onchange_trip_id(self):
        if self.trip_id and not self.return_odometer:
            self.return_odometer = self.trip_id.last_odometer

    def action_confirm(self):
        self.ensure_one()
        trip = self.trip_id
        if trip.state != 'done':
            raise UserError(f'{trip.name} henüz tamamlanmadı.')
        if trip.return_datetime:
            raise UserError(f'{trip.name} için dönüş zaten tamamlanmış.')
        if not self.return_odometer:
            raise UserError('Dönüş km girilmesi zorunludur.')
        if self.return_odometer < trip.last_odometer:
            raise UserError(
                f'Dönüş km, teslimat bitişindeki km ({trip.last_odometer}) değerinden küçük olamaz.')
        trip.write({
            'return_odometer': self.return_odometer,
            'return_datetime': fields.Datetime.now(),
        })
        trip.vehicle_id.with_context(transport_skip_return_guard=True).write({
            'odometer': self.return_odometer,
            'transport_state': 'available',
        })
        body = self.env._(
            'Dönüş tamamlandı, araç müsait duruma alındı. Boş dönüş mesafesi: %(km)s km '
            '(teslimat bitişi %(last)s -> dönüş %(ret)s).',
            km=self.return_odometer - trip.last_odometer, last=trip.last_odometer, ret=self.return_odometer,
        )
        if trip.outbound_distance_km:
            body += self.env._(
                ' Boş gidiş mesafesi (garajdan ilk teslim almaya): %(out)s km. '
                'Toplam boş gidiş/dönüş mesafesi: %(total)s km.',
                out=trip.outbound_distance_km, total=trip.return_distance_km,
            )
        trip.message_post(body=body)
        return {'type': 'ir.actions.act_window_close'}
