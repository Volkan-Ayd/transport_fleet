from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportTripFuel(models.Model):
    _name = 'transport.trip.fuel'
    _description = 'Sefer Yakıt İşlemi'
    _inherit = ['mail.thread']
    _order = 'id desc'

    trip_id = fields.Many2one(
        'transport.trip', ondelete='cascade', string='Sefer', readonly=True)
    grupaj_trip_id = fields.Many2one(
        'transport.grupaj.trip', ondelete='cascade', string='Grupaj Seferi', readonly=True)
    driver_id = fields.Many2one(
        'hr.employee', compute='_compute_vehicle_driver', store=True, string='Şoför', readonly=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', compute='_compute_vehicle_driver', store=True, string='Çekici', readonly=True)
    date = fields.Datetime(string='Tarih', default=fields.Datetime.now, readonly=True)
    odometer = fields.Float(string='Yakıt Alındığı Km', required=True, readonly=True)
    liters = fields.Float(string='Alınan Yakıt (Litre)', required=True, readonly=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, readonly=True)
    price_per_liter = fields.Monetary(
        string='Litre Birim Fiyatı', currency_field='currency_id', required=True, readonly=True)
    total_cost = fields.Monetary(
        string='Toplam Tutar', currency_field='currency_id', compute='_compute_total_cost',
        store=True, help='Alınan yakıt (litre) x litre birim fiyatı.')
    fuel_limit = fields.Float(
        compute='_compute_fuel_limit', store=True, string='Tanımlı Yakıt Limiti (L)', readonly=True,
        help='Teklifin kartında tanımlanmış kullanılabilir yakıt limiti; sadece bilgi/karşılaştırma '
             'amaçlıdır.')
    distance_since_last = fields.Float(
        compute='_compute_consumption_rate', store=True, string='Önceki Yakıttan Bu Yana Km',
        help='Bu yakıt alımından önceki yakıt alımına (yoksa sefer başlangıcına) kadar katedilen km.')
    consumption_rate = fields.Float(
        compute='_compute_consumption_rate', store=True, string='Oran (L/Km)', digits=(16, 3),
        help='Önceki yakıt alımından (yoksa sefer başlangıcından) bu yakıt alımına kadar '
             'katedilen km başına harcanan yakıt (litre/km).')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('liters', 'price_per_liter')
    def _compute_total_cost(self):
        for fuel in self:
            fuel.total_cost = fuel.liters * fuel.price_per_liter

    @api.depends('liters', 'fuel_limit')
    def _compute_display_name(self):
        for fuel in self:
            fuel.display_name = self.env._(
                '%(liters)s L (km: %(km)s)', liters=fuel.liters, km=fuel.odometer)

    @api.depends('trip_id.vehicle_id', 'trip_id.driver_id', 'grupaj_trip_id.vehicle_id', 'grupaj_trip_id.driver_id')
    def _compute_vehicle_driver(self):
        for fuel in self:
            ref = fuel.trip_id or fuel.grupaj_trip_id
            fuel.vehicle_id = ref.vehicle_id
            fuel.driver_id = ref.driver_id

    @api.depends('trip_id.lead_id.transport_fuel_limit', 'grupaj_trip_id.lead_id.transport_fuel_limit')
    def _compute_fuel_limit(self):
        for fuel in self:
            lead = fuel.trip_id.lead_id if fuel.trip_id else fuel.grupaj_trip_id.lead_id
            fuel.fuel_limit = lead.transport_fuel_limit if lead else 0.0

    @api.depends('trip_id', 'grupaj_trip_id', 'odometer', 'liters')
    def _compute_consumption_rate(self):
        for fuel in self:
            if fuel.trip_id:
                reference_km = fuel.trip_id.odometer
                domain = [('trip_id', '=', fuel.trip_id.id)]
            else:
                reference_km = fuel.grupaj_trip_id.vehicle_id.odometer
                domain = [('grupaj_trip_id', '=', fuel.grupaj_trip_id.id)]
            if (fuel.trip_id or fuel.grupaj_trip_id) and fuel.odometer:
                previous = self.search(
                    domain + [('odometer', '<', fuel.odometer), ('id', '!=', fuel.id)],
                    order='odometer desc', limit=1)
                if previous:
                    reference_km = previous.odometer
            distance = fuel.odometer - reference_km
            fuel.distance_since_last = distance if distance > 0 else 0.0
            fuel.consumption_rate = (fuel.liters / distance) if distance > 0 else 0.0

    @api.constrains('trip_id', 'grupaj_trip_id')
    def _check_trip_reference(self):
        for fuel in self:
            if bool(fuel.trip_id) == bool(fuel.grupaj_trip_id):
                raise UserError(
                    'Yakıt işlemi tam olarak bir Sefer veya bir Grupaj Seferine bağlı olmalıdır.')

    def action_open_trip(self):
        self.ensure_one()
        if self.grupaj_trip_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Grupaj Seferi',
                'res_model': 'transport.grupaj.trip',
                'view_mode': 'form',
                'res_id': self.grupaj_trip_id.id,
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sefer',
            'res_model': 'transport.trip',
            'view_mode': 'form',
            'res_id': self.trip_id.id,
        }
