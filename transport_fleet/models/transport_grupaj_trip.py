from odoo import api, fields, models
from odoo.exceptions import UserError

from .crm_lead import _detect_route_continent


class TransportGrupajTrip(models.Model):
    _name = 'transport.grupaj.trip'
    _description = 'Grupaj Seferi'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Sefer No', default='Yeni', copy=False, readonly=True)
    grupaj_id = fields.Many2one(
        'crm.lead.grupaj', string='Grupaj Satırı', required=True, readonly=True, copy=False,
        ondelete='restrict')
    lead_id = fields.Many2one(
        'crm.lead', string='Teklif', related='grupaj_id.lead_id', store=True, readonly=True)
    partner_id = fields.Many2one(
        'res.partner', string='Müşteri', related='lead_id.partner_id', store=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('confirmed', 'Sefer Başladı'),
        ('done', 'Tamamlandı'),
    ], string='Durum', default='confirmed', required=True, tracking=True, copy=False)
    start_datetime = fields.Datetime(string='Sefer Başlama Saati', readonly=True, copy=False)
    end_datetime = fields.Datetime(string='Sefer Bitiş Saati', readonly=True, copy=False)

    # Grupaj satırından, oluşturulduğu an kopyalanan bilgiler - sefer kartında bağımsız olarak
    # düzenlenebilir (teklif/CRM tarafındaki satır sonradan değişirse burada otomatik değişmez,
    # tıpkı Taşımacılık sekmesindeki şasi -> sefer satırı aktarımında olduğu gibi).
    firma = fields.Char(string='Firma')
    activity_code = fields.Char(string='Aktivite Kodu')
    grupaj_no = fields.Char(string='Grupaj No')
    start_date = fields.Date(string='Başlangıç Tarihi')
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Çekici Plaka',
        domain=[('transport_state', 'in', ('available', 'returning')), ('vehicle_type', '=', 'other')],
        context={'show_transport_status': True})
    driver_id = fields.Many2one(
        'hr.employee', string='Şoför', related='vehicle_id.transport_driver_id', store=True, readonly=True)
    subcontractor_tractor_plate = fields.Char(string='Taşeron Çekici Plaka')
    route_info = fields.Char(string='Rota Bilgisi')
    quantity = fields.Integer(string='Miktar')
    activity_group_name = fields.Char(string='Aktivite Grup Adı')
    km = fields.Float(string='Kilometre')
    vehicle_coefficient = fields.Float(string='Araç Katsayısı')
    extra_km = fields.Float(string='İlave Km')
    invoice_status = fields.Char(
        string='Fatura Durumu (İçe Aktarılan)',
        help='Excel\'den içe aktarılan ham bilgi (FATURADURUMU sütunu) - sadece referans '
             'amaçlıdır, sistem tarafından otomatik güncellenmez. Gerçek/güncel durum için '
             '"Fatura Durumu" alanına bakın.')
    mt = fields.Char(string='MT')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Para Birimi', related='company_id.currency_id')
    amount_total = fields.Monetary(
        string='Tutar', compute='_compute_amount_total', store=True, currency_field='currency_id',
        help='Miktar x (Kilometre + İlave Km) x Araç Katsayısı')
    order_id = fields.Many2one('sale.order', string='Sipariş', readonly=True, copy=False)
    billing_status = fields.Selection([
        ('not_invoiced', 'Faturalanmadı'),
        ('partial', 'Kısmi Faturalandı'),
        ('invoiced', 'Faturalandı'),
    ], string='Fatura Durumu', compute='_compute_billing_status', store=True)
    driver_earning_ids = fields.One2many(
        'transport.driver.earning', 'grupaj_trip_id', string='Şoför Hakedişi')
    driver_earning_count = fields.Integer(compute='_compute_driver_earning_count')
    fuel_ids = fields.One2many('transport.trip.fuel', 'grupaj_trip_id', string='Yakıt İşlemleri')
    fuel_count = fields.Integer(compute='_compute_fuel_count')
    route_continent = fields.Selection([
        ('europe', 'Avrupa'),
        ('asia', 'Asya'),
        ('both', 'Avrupa-Asya (Geçişli)'),
    ], string='Rota Kıtası', compute='_compute_route_continent', store=True,
        help='Rota Bilgisi metninde geçen il (ve İstanbul/Çanakkale için ilçe) adları İl/İlçe/'
             'Mahalle Referansı tablosundaki kıta bilgisiyle karşılaştırılarak otomatik '
             'yakalanır (örn. İstanbul içi Avrupa/Asya yakası arası geçiş).')

    @api.depends('route_info')
    def _compute_route_continent(self):
        for trip in self:
            trip.route_continent = _detect_route_continent(trip.route_info)

    @api.depends('quantity', 'km', 'extra_km', 'vehicle_coefficient')
    def _compute_amount_total(self):
        for trip in self:
            trip.amount_total = (
                (trip.quantity or 0) * ((trip.km or 0) + (trip.extra_km or 0)) * (trip.vehicle_coefficient or 0))

    @api.depends('driver_earning_ids')
    def _compute_driver_earning_count(self):
        for trip in self:
            trip.driver_earning_count = len(trip.driver_earning_ids)

    @api.depends('fuel_ids')
    def _compute_fuel_count(self):
        for trip in self:
            trip.fuel_count = len(trip.fuel_ids)

    @api.depends('order_id.invoice_status', 'order_id.invoice_ids.state')
    def _compute_billing_status(self):
        for trip in self:
            order = trip.order_id
            if not order:
                trip.billing_status = 'not_invoiced'
            elif order.invoice_status == 'invoiced':
                trip.billing_status = 'invoiced'
            elif order.invoice_ids.filtered(lambda move: move.state == 'posted'):
                trip.billing_status = 'partial'
            else:
                trip.billing_status = 'not_invoiced'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Yeni') == 'Yeni':
                vals['name'] = self.env['ir.sequence'].next_by_code('transport.grupaj.trip') or 'Yeni'
        trips = super().create(vals_list)
        trips.filtered(lambda t: t.state == 'confirmed' and not t.start_datetime).start_datetime = \
            fields.Datetime.now()
        return trips

    def _prepare_order_line_vals(self):
        self.ensure_one()
        return {
            'product_id': self._get_grupaj_order_product().id,
            'product_uom_qty': self.quantity or 0,
            'price_unit': ((self.km or 0) + (self.extra_km or 0)) * (self.vehicle_coefficient or 0),
            'name': self.env._(
                '%(name)s - Grupaj Nakliye (%(route)s)', name=self.name, route=self.route_info or '',
            ),
        }

    def _get_grupaj_order_product(self):
        product_tmpl = self.env.ref('transport_fleet.product_transport_service_grupaj', raise_if_not_found=False)
        product = product_tmpl.product_variant_id if product_tmpl else False
        if not product:
            raise UserError('Grupaj nakliye hizmeti ürünü bulunamadı.')
        return product

    def action_create_or_update_order(self):
        """Siparişi (satış siparişi - onaylanmamış/taslak) güncel Miktar x Km x Araç Katsayısı
        değerine göre oluşturur ya da - zaten oluşmuşsa ve henüz onaylanmamışsa - günceller."""
        for trip in self:
            if not trip.partner_id:
                raise UserError(
                    f'{trip.name}: Sipariş oluşturmak için önce ilgili teklifte bir müşteri seçilmelidir.')
            if trip.order_id:
                if trip.order_id.state != 'draft':
                    raise UserError(
                        f'{trip.name}: Sipariş zaten onaylanmış, tutar artık buradan değiştirilemez.')
                line = trip.order_id.order_line[:1]
                if line:
                    line.write(trip._prepare_order_line_vals())
                else:
                    trip.env['sale.order.line'].create(
                        dict(trip._prepare_order_line_vals(), order_id=trip.order_id.id))
            else:
                trip.order_id = self.env['sale.order'].create({
                    'partner_id': trip.partner_id.id,
                    'origin': trip.name,
                    'order_line': [(0, 0, trip._prepare_order_line_vals())],
                })

    def action_complete(self):
        for trip in self:
            if trip.state != 'confirmed':
                raise UserError(f'{trip.name} tamamlanamaz.')
        self.action_create_or_update_order()
        self.write({'state': 'done', 'end_datetime': fields.Datetime.now()})
        for trip in self:
            trip._create_driver_earning()

    def _create_driver_earning(self):
        """Sefer tamamlandığında, şoförün bu grupaj seferinde katettiği mesafe (Kilometre +
        İlave Km) üzerinden hakediş kaydı oluşturur."""
        self.ensure_one()
        if not self.driver_id:
            return
        distance = (self.km or 0.0) + (self.extra_km or 0.0)
        if distance <= 0:
            return
        rate = self.env.company.transport_driver_rate_per_km or 0.0
        self.env['transport.driver.earning'].create({
            'grupaj_trip_id': self.id,
            'driver_id': self.driver_id.id,
            'earning_type': 'distance',
            'distance_km': distance,
            'rate_per_km': rate,
            'amount': distance * rate,
        })

    def action_open_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sipariş',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.order_id.id,
        }

    def action_open_lead(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Teklif',
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': self.lead_id.id,
        }

    def action_open_expense_wizard(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'done'):
            raise UserError('Masraf sadece sefer sırasında veya tamamlandıktan sonra eklenebilir.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Masraf Ekle',
            'res_model': 'transport.trip.expense.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_grupaj_trip_id': self.id},
        }

    def action_open_fuel_wizard(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'done'):
            raise UserError('Yakıt sadece sefer sırasında veya tamamlandıktan sonra eklenebilir.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yakıt Ekle',
            'res_model': 'transport.trip.fuel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_grupaj_trip_id': self.id},
        }

    def action_open_damage_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasar Bildir',
            'res_model': 'transport.trip.line.damage.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_grupaj_trip_id': self.id},
        }
