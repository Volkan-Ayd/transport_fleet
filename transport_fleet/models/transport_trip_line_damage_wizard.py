from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportTripLineDamageWizard(models.TransientModel):
    _name = 'transport.trip.line.damage.wizard'
    _description = 'Hasar Bildir'

    line_id = fields.Many2one('transport.trip.line')
    grupaj_trip_id = fields.Many2one('transport.grupaj.trip', string='Grupaj Seferi')
    chassis_number = fields.Char(
        compute='_compute_reference', readonly=True, string='Şasi / Grupaj No')
    partner_id = fields.Many2one(
        'res.partner', compute='_compute_reference', readonly=True, string='Müşteri')
    note = fields.Text(string='Not')
    image_ids = fields.Many2many(
        'ir.attachment', string='Fotoğraflar (Hasar)',
        help='Hasarlı aracın fotoğrafları. Birden fazla fotoğraf eklenebilir.')

    @api.depends(
        'line_id.chassis_number', 'line_id.partner_id',
        'grupaj_trip_id.grupaj_no', 'grupaj_trip_id.partner_id')
    def _compute_reference(self):
        for wiz in self:
            if wiz.line_id:
                wiz.chassis_number = wiz.line_id.chassis_number
                wiz.partner_id = wiz.line_id.partner_id
            else:
                wiz.chassis_number = wiz.grupaj_trip_id.grupaj_no
                wiz.partner_id = wiz.grupaj_trip_id.partner_id

    def action_confirm(self):
        self.ensure_one()
        if not self.line_id and not self.grupaj_trip_id:
            raise UserError('Sefer bulunamadı.')
        if not self.image_ids and not self.note:
            raise UserError('En az bir fotoğraf veya not eklemelisiniz.')
        if self.line_id:
            trip = self.line_id.trip_id
            reference_label = 'şasi'
        else:
            trip = self.grupaj_trip_id
            reference_label = 'grupaj no'
        # Markup(...) % value HTML-escapes value automatically, so free-text (note, partner
        # name) can't inject markup into the trip's chatter.
        body = Markup('<b>%s</b> - %s: %s') % (
            self.env._('Hasar bildirimi'), reference_label, self.chassis_number)
        if self.partner_id:
            body += Markup(' (%s: %s)') % (self.env._('müşteri'), self.partner_id.name)
        if self.note:
            body += Markup('<br/>%s: %s') % (self.env._('Not'), self.note)
        if self.image_ids:
            body += Markup('<br/>%s: %s') % (self.env._('Fotoğraf sayısı'), len(self.image_ids))
        trip.message_post(body=body, attachment_ids=self.image_ids.ids)
        return {'type': 'ir.actions.act_window_close'}
