from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportTripFuelWizard(models.TransientModel):
    _name = 'transport.trip.fuel.wizard'
    _description = 'Sefere Yakıt Ekle'

    trip_id = fields.Many2one('transport.trip')
    grupaj_trip_id = fields.Many2one('transport.grupaj.trip', string='Grupaj Seferi')
    last_odometer = fields.Float(
        compute='_compute_last_odometer', readonly=True, string='Son Km Okuması')
    fuel_limit = fields.Float(
        compute='_compute_fuel_limit', readonly=True,
        string='Kullanılabilir Yakıt Limiti (L)',
        help='Teklifin kartında tanımlanmış limit; sadece bilgi amaçlıdır, buradan değiştirilemez.')
    odometer = fields.Float(string='Yakıt Alındığı Km', required=True)
    liters = fields.Float(
        string='Alınan Yakıt (Litre)', required=True,
        help='Teklifte bir yakıt limiti tanımlıysa buraya varsayılan olarak gelir; gerekirse '
             'gerçek alınan miktara göre değiştirin.')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    price_per_liter = fields.Monetary(
        string='Litre Birim Fiyatı', currency_field='currency_id', required=True)
    total_cost = fields.Monetary(
        string='Toplam Tutar', currency_field='currency_id', compute='_compute_total_cost')

    @api.depends('liters', 'price_per_liter')
    def _compute_total_cost(self):
        for wiz in self:
            wiz.total_cost = wiz.liters * wiz.price_per_liter

    @api.depends('trip_id.last_odometer', 'trip_id.odometer', 'grupaj_trip_id.vehicle_id.odometer')
    def _compute_last_odometer(self):
        for wiz in self:
            if wiz.trip_id:
                wiz.last_odometer = wiz.trip_id.last_odometer or wiz.trip_id.odometer
            else:
                wiz.last_odometer = wiz.grupaj_trip_id.vehicle_id.odometer

    @api.depends('trip_id.lead_id.transport_fuel_limit', 'grupaj_trip_id.lead_id.transport_fuel_limit')
    def _compute_fuel_limit(self):
        for wiz in self:
            lead = wiz.trip_id.lead_id if wiz.trip_id else wiz.grupaj_trip_id.lead_id
            wiz.fuel_limit = lead.transport_fuel_limit if lead else 0.0

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        trip_id = res.get('trip_id') or self.env.context.get('default_trip_id')
        grupaj_trip_id = res.get('grupaj_trip_id') or self.env.context.get('default_grupaj_trip_id')
        if 'liters' in fields_list:
            lead = False
            if trip_id:
                lead = self.env['transport.trip'].browse(trip_id).lead_id
            elif grupaj_trip_id:
                lead = self.env['transport.grupaj.trip'].browse(grupaj_trip_id).lead_id
            if lead and lead.transport_fuel_limit:
                res['liters'] = lead.transport_fuel_limit
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.trip_id and not self.grupaj_trip_id:
            raise UserError('Sefer bulunamadı.')
        if not self.odometer:
            raise UserError('Yakıt alındığı km girilmesi zorunludur.')
        if not self.liters:
            raise UserError('Alınan yakıt (litre) girilmesi zorunludur.')
        if not self.price_per_liter:
            raise UserError('Litre birim fiyatı girilmesi zorunludur.')
        trip = self.trip_id or self.grupaj_trip_id
        reference_km = self.last_odometer
        if self.odometer < reference_km:
            raise UserError(
                f'Yakıt alındığı km, son kayıtlı km ({reference_km}) değerinden küçük olamaz.')
        self.env['transport.trip.fuel'].create({
            'trip_id': self.trip_id.id if self.trip_id else False,
            'grupaj_trip_id': self.grupaj_trip_id.id if self.grupaj_trip_id else False,
            'odometer': self.odometer,
            'liters': self.liters,
            'price_per_liter': self.price_per_liter,
        })
        trip.message_post(body=self.env._(
            '%(driver)s, %(vehicle)s için %(liters)s litre yakıt aldı (km: %(km)s, '
            'birim fiyat: %(price)s, toplam: %(total)s).',
            driver=trip.driver_id.name or '-', vehicle=trip.vehicle_id.license_plate,
            liters=self.liters, km=self.odometer, price=self.price_per_liter,
            total=self.total_cost,
        ))
        return {'type': 'ir.actions.act_window_close'}
