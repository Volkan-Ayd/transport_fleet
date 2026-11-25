from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportTripLinePickupWizard(models.TransientModel):
    _name = 'transport.trip.line.pickup.wizard'
    _description = 'Araç Teslim Al'

    line_id = fields.Many2one('transport.trip.line', required=True)
    trip_id = fields.Many2one(related='line_id.trip_id', readonly=True)
    chassis_number = fields.Char(related='line_id.chassis_number', readonly=True)
    partner_id = fields.Many2one(related='line_id.partner_id', readonly=True, string='Müşteri')
    last_odometer = fields.Float(related='trip_id.last_odometer', readonly=True, string='Son Km Okuması')
    pickup_odometer = fields.Float(
        string='Teslim Alma Km', required=True,
        help='Bu aracın çekiciye yüklendiği/teslim alındığı andaki km.')
    image_ids = fields.Many2many(
        'ir.attachment', string='Fotoğraflar',
        help='Teslim alma sırasındaki fotoğraflar. Birden fazla fotoğraf eklenebilir.')

    @api.onchange('line_id')
    def _onchange_line_id(self):
        if self.line_id and not self.pickup_odometer:
            self.pickup_odometer = (
                self.line_id.pickup_odometer
                or self.line_id.trip_id.last_odometer
                or self.line_id.trip_id.odometer)

    def action_confirm(self):
        self.ensure_one()
        line = self.line_id
        trip = line.trip_id
        if not self.pickup_odometer:
            raise UserError('Teslim alma km girilmesi zorunludur.')
        if self.pickup_odometer < trip.last_odometer:
            raise UserError(
                f'Teslim alma km, son kayıtlı km ({trip.last_odometer}) değerinden küçük olamaz '
                f'(eşit olabilir).')
        starting_trip = trip.state == 'draft'
        line.pickup_odometer = self.pickup_odometer
        # Araç zaten teslim edilmişse, kat edilen km'yi yeni yükleme kmsine göre tutarlı tut.
        if line.delivered and line.delivered_odometer:
            line.delivered_km = line.delivered_odometer - self.pickup_odometer
        if starting_trip:
            # Sefer henüz taslaksa, bu satırın teslim alınması "Sefer Başlat" ile aynı geçişi
            # tetikler (Araç Km / durum / son km okuması doldurulur) - ama SADECE bu satır için;
            # diğer satırlar boş kalır, her biri kendi "Teslim Al" işlemiyle ayrı doldurulacak.
            trip._start_from_pickup(line, self.pickup_odometer)
        elif self.pickup_odometer > trip.last_odometer:
            # Seferin "Son Km Okuması" bilgisini bu okumayla güncel tut (araç fiilen bu kmye
            # kadar ilerlemiş demektir) - ama bu güncelleme SADECE bu satıra özel; diğer
            # satırların kendi teslim alma km'lerine yansımaz/dokunulmaz.
            trip.last_odometer = self.pickup_odometer
            trip.vehicle_id.odometer = self.pickup_odometer
        body = Markup('<b>%s</b> - şasi: %s, teslim alma km: %s') % (
            self.env._('Araç teslim alındı'), line.chassis_number, self.pickup_odometer)
        if line.partner_id:
            body += Markup(' (%s: %s)') % (self.env._('müşteri'), line.partner_id.name)
        if self.image_ids:
            body += Markup('<br/>%s: %s') % (self.env._('Fotoğraf sayısı'), len(self.image_ids))
        trip.message_post(body=body, attachment_ids=self.image_ids.ids)
        return {'type': 'ir.actions.act_window_close'}
