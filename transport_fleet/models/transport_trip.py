from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError

PRICING_METHODS = [
    ('per_vehicle', 'Araç Başı'),
    ('per_km', 'Km Başı'),
]


class TransportTrip(models.Model):
    _name = 'transport.trip'
    _description = 'Taşımacılık Seferi'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Sefer No', default='Yeni', copy=False, readonly=True)
    lead_id = fields.Many2one(
        'crm.lead', string='Ana Teklif', tracking=True,
        help='Sefere yeni şasi satırı eklenirken teklif boş bırakılırsa buradaki teklif varsayılan olarak '
             'kullanılır. Aynı seferde farklı müşterilerin araçları taşınacaksa, her satırda ayrı teklif '
             'seçilebilir.')
    partner_id = fields.Many2one(
        'res.partner', string='Ana Müşteri', related='lead_id.partner_id', store=True, readonly=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Çekici', required=True, tracking=True, copy=False,
        domain=[('vehicle_type', '=', 'other'), ('transport_state', 'in', ('available', 'returning'))],
        context={'show_transport_status': True})
    driver_id = fields.Many2one(
        'hr.employee', string='Şoför', related='vehicle_id.transport_driver_id', store=True, readonly=True)
    trailer_id = fields.Many2one(
        'transport.trailer', string='Dorse', related='vehicle_id.current_trailer_id', store=True, readonly=True)
    odometer = fields.Float(string='Araç Km (Teslim Alırken)', tracking=True)
    last_odometer = fields.Float(string='Son Km Okuması', readonly=True, copy=False)
    start_datetime = fields.Datetime(
        string='Sefer Başlama Saati', readonly=True, copy=False,
        help='Sefer başlatıldığı (Seferi Başlat tıklandığı) an otomatik kaydedilir.')
    end_datetime = fields.Datetime(
        string='Sefer Bitiş Saati', readonly=True, copy=False,
        help='Tüm araçlar teslim edilip sefer tamamlandığında otomatik kaydedilir.')
    return_odometer = fields.Float(
        string='Dönüş Km', readonly=True, copy=False,
        help='Araç boş dönüşle garaja/depoya ulaştığında "Dönüş Tamamlandı" ile girilen km.')
    return_datetime = fields.Datetime(
        string='Dönüş Tamamlanma Saati', readonly=True, copy=False)
    outbound_distance_km = fields.Float(
        string='Boş Gidiş Km', readonly=True, copy=False,
        help='Garajdan, ilk aracın fiilen teslim alındığı noktaya kadar yüksüz kat edilen '
             'mesafe (varsa). Sefer başlarken ("Araç Km" alanı daha önceden, gerçek teslim '
             'alma kmsinden farklı girilmişse) bir defaya mahsus hesaplanır ve sabitlenir.')
    return_distance_km = fields.Float(
        compute='_compute_return_distance_km', store=True, string='Boş Gidiş/Dönüş Km',
        help='Boş Gidiş Km (garajdan ilk teslim almaya kadar) ile boş dönüş mesafesinin '
             '(Son Km Okuması/teslimat bitişi ile dönüş km arasındaki fark) toplamı. Şoför '
             'hakedişine dahil değildir, sadece raporlama/maliyet amaçlıdır.')
    pricing_method = fields.Selection(
        PRICING_METHODS, string='Ücretlendirme Yöntemi', tracking=True, default='per_vehicle')
    cargo_line_ids = fields.One2many('transport.trip.line', 'trip_id', string='Taşınan Araçlar (Şasi No)')
    cargo_count = fields.Integer(compute='_compute_cargo_count', string='Araç Sayısı')
    pending_cargo_count = fields.Integer(compute='_compute_cargo_count', string='Teslim Edilmemiş Araç')
    customer_count = fields.Integer(compute='_compute_cargo_count', string='Müşteri Sayısı')
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('confirmed', 'Sefer Başladı'),
        ('done', 'Tamamlandı'),
        ('cancelled', 'İptal Edildi'),
    ], string='Durum', default='draft', tracking=True, copy=False)
    sale_order_ids = fields.Many2many('sale.order', string='Satış Siparişleri', readonly=True, copy=False)
    sale_order_count = fields.Integer(compute='_compute_sale_order_count')
    billing_status = fields.Selection([
        ('not_invoiced', 'Faturalanmadı'),
        ('partial', 'Kısmi Faturalandı'),
        ('invoiced', 'Faturalandı'),
    ], string='Fatura Durumu', compute='_compute_billing_status', store=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    driver_earning_ids = fields.One2many(
        'transport.driver.earning', 'trip_id', string='Şoför Hakedişi')
    driver_earning_count = fields.Integer(compute='_compute_driver_earning_count')
    fuel_ids = fields.One2many('transport.trip.fuel', 'trip_id', string='Yakıt İşlemleri')
    fuel_count = fields.Integer(compute='_compute_fuel_count')
    hgs_record_ids = fields.One2many('transport.hgs.record', 'trip_id', string='HGS Geçişleri')
    hgs_record_count = fields.Integer(compute='_compute_hgs_record_count')

    @api.depends('return_odometer', 'last_odometer', 'outbound_distance_km')
    def _compute_return_distance_km(self):
        for trip in self:
            distance = trip.return_odometer - trip.last_odometer
            return_leg = distance if trip.return_odometer and distance > 0 else 0.0
            trip.return_distance_km = return_leg + (trip.outbound_distance_km or 0.0)

    @api.depends('driver_earning_ids')
    def _compute_driver_earning_count(self):
        for trip in self:
            trip.driver_earning_count = len(trip.driver_earning_ids)

    @api.depends('fuel_ids')
    def _compute_fuel_count(self):
        for trip in self:
            trip.fuel_count = len(trip.fuel_ids)

    @api.depends('hgs_record_ids')
    def _compute_hgs_record_count(self):
        for trip in self:
            trip.hgs_record_count = len(trip.hgs_record_ids)

    @api.depends('cargo_line_ids.delivered', 'cargo_line_ids.lead_id', 'cargo_line_ids.partner_id')
    def _compute_cargo_count(self):
        for trip in self:
            trip.cargo_count = len(trip.cargo_line_ids)
            trip.pending_cargo_count = len(trip.cargo_line_ids.filtered(lambda line: not line.delivered))
            trip.customer_count = len(trip.cargo_line_ids._get_billing_groups())

    @api.depends('sale_order_ids')
    def _compute_sale_order_count(self):
        for trip in self:
            trip.sale_order_count = len(trip.sale_order_ids)

    @api.depends('sale_order_ids.invoice_status', 'sale_order_ids.invoice_ids.state')
    def _compute_billing_status(self):
        for trip in self:
            orders = trip.sale_order_ids
            if not orders:
                trip.billing_status = 'not_invoiced'
                continue
            if all(order.invoice_status == 'invoiced' for order in orders):
                trip.billing_status = 'invoiced'
            elif any(order.invoice_ids.filtered(lambda move: move.state == 'posted') for order in orders):
                trip.billing_status = 'partial'
            else:
                trip.billing_status = 'not_invoiced'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Yeni') == 'Yeni':
                vals['name'] = self.env['ir.sequence'].next_by_code('transport.trip') or 'Yeni'
            if not vals.get('pricing_method'):
                vals['pricing_method'] = self.env.company.transport_default_pricing_method or 'per_vehicle'
            if not vals.get('last_odometer') and vals.get('vehicle_id'):
                # Taslak aşamasında "Son Km Okuması" aracın o anki bilinen kilometresini
                # göstersin (0 değil) - sefer başlatıldığında zaten gerçek teslim alma kmsiyle
                # güncellenecek.
                vehicle = self.env['fleet.vehicle'].browse(vals['vehicle_id'])
                vals['last_odometer'] = vehicle.odometer
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'vehicle_id' in vals and 'last_odometer' not in vals:
            # Taslak aşamasında araç değiştirilirse "Son Km Okuması" da yeni aracın bilinen
            # kilometresine göre güncellensin (eski aracın veya 0'ın gösterilmesini önler).
            for trip in self.filtered(lambda t: t.state == 'draft'):
                trip.last_odometer = trip.vehicle_id.odometer
        return res

    def _resolve_pricing_method(self, lead, partner=None):
        """Her müşteri satırı kendi teklifinin (veya o teklifin müşteri kartının, ya da - CRM
        teklifi olmayan sefer/satırlarda - doğrudan seçilmiş müşteri kartının) ücretlendirme
        tercihine göre faturalandırılır; seferin pricing_method alanı sadece ilk/varsayılan
        müşteri için bir başlangıç değeridir, tüm sefere dayatılmaz. Aynı seferde biri araç başı
        diğeri km başı anlaşmalı iki müşteri olabilir."""
        self.ensure_one()
        return (
            (lead and lead.transport_pricing_method)
            or (partner and partner.transport_pricing_method)
            or self.pricing_method
            or self.env.company.transport_default_pricing_method
            or 'per_vehicle'
        )

    def _bill_pending_per_vehicle(self, lines):
        """Bu satırlardan, müşterisinin ücretlendirme yöntemi 'araç başı' olarak çözümlenenleri
        hemen (yüklendiği anda) faturalandırır. 'Km başı' çözümlenen satırlar teslimat anında
        _bill_per_km_delivery tarafından faturalandırılacağı için burada atlanır."""
        self.ensure_one()
        to_bill = lines.filtered(
            lambda line: self._resolve_pricing_method(
                line.lead_id or self.lead_id, line.partner_id or self.partner_id) == 'per_vehicle')
        if not to_bill:
            return self.env['sale.order']
        return self._create_sale_orders(to_bill)

    def action_confirm(self):
        for trip in self:
            if trip.state != 'draft':
                continue
            if not trip.cargo_line_ids:
                raise UserError('Sefer başlatmadan önce en az bir araç şasi numarası okutmalısınız.')
            if not trip.odometer:
                raise UserError('Çekicinin kilometresini girmeden sefer başlatılamaz.')
            if trip.vehicle_id.transport_state not in ('available', 'returning'):
                raise UserError(
                    f'{trip.vehicle_id.license_plate} şu an müsait veya dönüş yolunda değil, sefer başlatılamaz.')
            trip.vehicle_id.odometer = trip.odometer
            trip.vehicle_id.transport_state = 'on_trip'
            trip.last_odometer = trip.odometer
            trip.cargo_line_ids.write({'pickup_odometer': trip.odometer})
            vals = {'state': 'confirmed', 'start_datetime': fields.Datetime.now()}
            orders = trip._bill_pending_per_vehicle(trip.cargo_line_ids)
            if orders:
                vals['sale_order_ids'] = [(4, order.id) for order in orders]
            trip.write(vals)
            trip.message_post(body=self.env._(
                'Sefer başladı: %(vehicle)s, %(count)s araç yüklendi (%(customers)s müşteri), km: %(km)s.',
                vehicle=trip.vehicle_id.license_plate, count=len(trip.cargo_line_ids),
                customers=trip.customer_count, km=trip.odometer,
            ))
        return True

    def _start_from_pickup(self, line, pickup_km):
        """Sefer taslak haldeyken bir satırın kendi "Teslim Al" penceresinden tetiklenebilir: bu,
        "Sefer Başlat" ile aynı durum geçişini (taslak -> başladı) yapar ama SADECE bu satırı
        işler - diğer satırların teslim alma km'si burada toptan doldurulmaz; her araç (örn. 50
        km ileride) kendi "Teslim Al" penceresiyle ayrı ayrı teslim alınabilir."""
        self.ensure_one()
        if self.vehicle_id.transport_state not in ('available', 'returning'):
            raise UserError(
                f'{self.vehicle_id.license_plate} şu an müsait veya dönüş yolunda değil, sefer başlatılamaz.')
        # "Araç Km" (garajdan çıkış) bu teslim alma kmsinden önceden/daha düşük bir değerle
        # girilmişse, aradaki fark boş gidiş mesafesidir - bir defaya mahsus sabitlenir; sonraki
        # satırların teslim alma km'leri (yüklü seyir) bu değeri bir daha değiştirmez.
        self.outbound_distance_km = max(0.0, pickup_km - self.odometer) if self.odometer else 0.0
        if not self.odometer:
            self.odometer = pickup_km
        self.vehicle_id.odometer = pickup_km
        self.vehicle_id.transport_state = 'on_trip'
        self.last_odometer = pickup_km
        orders = self._bill_pending_per_vehicle(line)
        vals = {'state': 'confirmed', 'start_datetime': fields.Datetime.now()}
        if orders:
            vals['sale_order_ids'] = [(4, order.id) for order in orders]
        self.write(vals)
        self.message_post(body=self.env._(
            'Sefer başladı (%(chassis)s aracının teslim alınmasıyla): %(vehicle)s, km: %(km)s. '
            'Diğer araçlar kendi teslim alma işlemleriyle (farklı km\'lerden) eklenecek.',
            chassis=line.chassis_number, vehicle=self.vehicle_id.license_plate, km=pickup_km,
        ))

    def action_cancel(self):
        for trip in self:
            if trip.state not in ('draft', 'confirmed'):
                raise UserError(
                    f'{trip.name} tamamlanmış veya zaten iptal edilmiş, iptal edilemez.')
            leads = (trip.lead_id | trip.cargo_line_ids.lead_id)
            orders_to_cancel = trip.sale_order_ids.filtered(
                lambda o: o.state in ('draft', 'sent', 'sale')
                and not o.invoice_ids.filtered(lambda move: move.state == 'posted'))
            already_invoiced = trip.sale_order_ids - orders_to_cancel
            if orders_to_cancel:
                orders_to_cancel.action_cancel()
            trip.vehicle_id.transport_state = 'available'
            leads.write({'transport_vehicle_id': False})
            trip.state = 'cancelled'
            body = self.env._(
                'Sefer iptal edildi. %(vehicle)s müsait duruma alındı.',
                vehicle=trip.vehicle_id.license_plate,
            )
            if already_invoiced:
                body += self.env._(
                    ' Not: %(orders)s zaten faturalandığı için otomatik iptal edilmedi, elle kontrol edin.',
                    orders=', '.join(already_invoiced.mapped('name')),
                )
            trip.message_post(body=body)
        return True

    def action_open_return_wizard(self):
        """Şoför, boş dönüşle garaja/depoya ulaştığında bunu tetikler. Boş dönüş mesafesinin
        hesaplanabilmesi için garaja ulaşıldığındaki km'yi soran bir pencere açar."""
        self.ensure_one()
        if self.state != 'done':
            raise UserError(f'{self.name} henüz tamamlanmadı.')
        if self.return_datetime:
            raise UserError(f'{self.name} için dönüş zaten tamamlanmış.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Dönüş Tamamlandı',
            'res_model': 'transport.trip.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_trip_id': self.id},
        }

    def action_open_add_cargo_wizard(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError('Sadece devam eden bir sefere yolda yeni müşteri/araç eklenebilir.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yolda Yeni Müşteri / Araç Ekle',
            'res_model': 'transport.trip.add.cargo.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_trip_id': self.id},
        }

    def action_open_expense_wizard(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'done'):
            raise UserError('Masraf sadece sefer sırasında veya dönüş aşamasında eklenebilir.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Masraf Ekle',
            'res_model': 'transport.trip.expense.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_trip_id': self.id},
        }

    def action_open_fuel_wizard(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'done'):
            raise UserError('Yakıt sadece sefer sırasında veya dönüş aşamasında eklenebilir.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yakıt Ekle',
            'res_model': 'transport.trip.fuel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_trip_id': self.id},
        }

    def _add_cargo(self, lead, chassis_records, new_odometer):
        self.ensure_one()
        if new_odometer < self.last_odometer:
            raise UserError(
                f'Yeni km, son kayıtlı km ({self.last_odometer}) değerinden küçük olamaz.')
        # Faturalama bu metodun sonunda zaten elle/gruplu olarak yapılıyor - create() üzerindeki
        # otomatik "sefer sırasında eklenen satırı hemen faturalandır" mantığının burada tekrar
        # tetiklenip mükerrer satış siparişi satırı oluşturmasını önler.
        new_lines = self.env['transport.trip.line'].with_context(transport_skip_auto_bill=True).create([{
            'trip_id': self.id,
            'lead_id': lead.id,
            'chassis_number': chassis.chassis_number,
            'note': chassis.note,
            'pickup_location': chassis.pickup_location,
            'destination': chassis.destination,
            'pickup_odometer': new_odometer,
        } for chassis in chassis_records])
        self.last_odometer = new_odometer
        self.vehicle_id.odometer = new_odometer
        # Bu şasileri fiilen taşıyan araca bağla: bu, teklifin atama durumunu (ve dolayısıyla
        # Kazanıldı aşamasına geçişini) tetikler - sefere yolda eklenen müşteriler de normal
        # "tır atandı" akışıyla aynı şekilde Kazanıldı'ya geçsin.
        chassis_records.filtered(lambda chassis: not chassis.vehicle_id).write(
            {'vehicle_id': self.vehicle_id.id})
        orders = self._bill_pending_per_vehicle(new_lines)
        if orders:
            self.sale_order_ids = [(4, order.id) for order in orders]
        self.message_post(body=self.env._(
            '%(partner)s müşterisinin %(count)s aracı bu durakta yüklendi (şasi: %(chassis)s), km: %(km)s.',
            partner=lead.partner_id.name or lead.name, count=len(new_lines),
            chassis=', '.join(new_lines.mapped('chassis_number')), km=new_odometer,
        ))
        return new_lines

    def action_open_end_wizard(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError('Sefer başlamadan durak/teslimat işlemi yapılamaz.')
        if not self.pending_cargo_count:
            raise UserError('Bu seferde teslim edilmemiş araç kalmadı.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Seferi Sonlandır',
            'res_model': 'transport.trip.end.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_trip_id': self.id},
        }

    def _deliver_lines(self, lines, new_odometer):
        self.ensure_one()
        for line in lines:
            pickup = line.pickup_odometer or self.odometer
            line.write({
                'delivered': True,
                'delivered_odometer': new_odometer,
                'delivered_km': new_odometer - pickup,
                'delivered_date': fields.Datetime.now(),
            })
        self.last_odometer = new_odometer
        self.vehicle_id.odometer = new_odometer
        # Sadece müşterisi 'km başı' çözümlenen satırları burada faturalandır; 'araç başı'
        # çözümlenenler zaten yüklendiği anda (_bill_pending_per_vehicle ile) faturalandırılmıştı.
        km_lines = lines.filtered(
            lambda line: self._resolve_pricing_method(
                line.lead_id or self.lead_id, line.partner_id or self.partner_id) == 'per_km')
        if km_lines:
            self._bill_per_km_delivery(km_lines)
        remaining = self.cargo_line_ids.filtered(lambda line: not line.delivered)
        if not remaining:
            self.write({'state': 'done', 'end_datetime': fields.Datetime.now()})
            self.vehicle_id.transport_state = 'returning'
            self._create_driver_earning()
        self.message_post(body=self.env._(
            '%(count)s araç teslim edildi (şasi: %(chassis)s), her biri kendi yüklendiği km\'den '
            'bu teslimat kmsine (%(km)s) kadar hesaplandı. %(rest)s',
            count=len(lines), chassis=', '.join(lines.mapped('chassis_number')), km=new_odometer,
            rest=(self.env._('Sefer tamamlandı, araç dönüşe geçti.') if not remaining else
                  self.env._('Kalan %(n)s araç ile sefer sürüyor.', n=len(remaining))),
        ))

    def _create_driver_earning(self):
        """Sefer tamamlandığında (tüm araçlar teslim edildiğinde), şoförün sefer sırasında katettiği
        mesafe (dönüş km hariç) üzerinden hakediş kaydı oluşturur."""
        self.ensure_one()
        if not self.driver_id:
            return
        distance = self.last_odometer - self.odometer
        if distance <= 0:
            return
        rate = self.env.company.transport_driver_rate_per_km or 0.0
        self.env['transport.driver.earning'].create({
            'trip_id': self.id,
            'driver_id': self.driver_id.id,
            'earning_type': 'distance',
            'distance_km': distance,
            'rate_per_km': rate,
            'amount': distance * rate,
        })

    def _bill_per_km_delivery(self, lines):
        self.ensure_one()
        product_tmpl = self.env.ref('transport_fleet.product_transport_service_km', raise_if_not_found=False)
        product = product_tmpl.product_variant_id if product_tmpl else False
        if not product:
            return
        # Filo ayarlarında girilen "Km Başı Satış Fiyatı" varsa hesaplama bu fiyat üzerinden
        # yapılır; boşsa (yapılandırılmamışsa) ürünün kendi satış fiyatına geri dönülür.
        price_per_km = self.env.company.transport_customer_price_per_km
        for group in lines._get_billing_groups():
            partner, lead, group_lines = group['partner'], group['lead'], group['lines']
            if not partner:
                continue
            total_km = sum(group_lines.mapped('delivered_km'))
            if total_km <= 0:
                continue
            order = self._find_order_for(partner, lead)
            if not order:
                order_vals = {'partner_id': partner.id, 'origin': self.name}
                if lead and 'opportunity_id' in self.env['sale.order']._fields:
                    order_vals['opportunity_id'] = lead.id
                order = self.env['sale.order'].create(order_vals)
                self.sale_order_ids = [(4, order.id)]
            detail = ', '.join(
                f"{line.chassis_number} ({line.delivered_km:g} km)" for line in group_lines)
            line_vals = {
                'order_id': order.id,
                'product_id': product.id,
                'product_uom_qty': total_km,
                'name': self.env._(
                    '%(vehicle)s ile taşıma - toplam %(km)s km (%(detail)s)',
                    vehicle=self.vehicle_id.license_plate, km=total_km, detail=detail,
                ),
                'transport_trip_line_ids': [(6, 0, group_lines.ids)],
            }
            if price_per_km:
                line_vals['price_unit'] = price_per_km
            self.env['sale.order.line'].create(line_vals)
            if order.state == 'draft':
                order.action_confirm()

    def _find_order_for(self, partner, lead):
        self.ensure_one()
        for order in self.sale_order_ids:
            if lead and order.opportunity_id == lead:
                return order
            if not lead and order.partner_id == partner and not order.opportunity_id:
                return order
        return False

    def _create_sale_orders(self, lines):
        self.ensure_one()
        product_tmpl = self.env.ref('transport_fleet.product_transport_service', raise_if_not_found=False)
        product = product_tmpl.product_variant_id if product_tmpl else False
        if not product:
            raise UserError('Nakliye hizmeti ürünü bulunamadı.')
        # Filo ayarlarında girilen "Araç Başı Satış Fiyatı" varsa hesaplama bu fiyat üzerinden
        # yapılır; boşsa (yapılandırılmamışsa) ürünün kendi satış fiyatına geri dönülür. Bu,
        # şirketin varsayılan ücretlendirme yönteminden (Araç Başı/Km Başı) bağımsızdır - hangi
        # teklifte hangi yöntem seçiliyse o fiyat kullanılır.
        price_per_vehicle = self.env.company.transport_customer_price_per_vehicle
        orders = self.env['sale.order']
        for group in lines._get_billing_groups():
            partner, lead, group_lines = group['partner'], group['lead'], group['lines']
            if not partner:
                raise UserError(
                    f'{group_lines[0].chassis_number} şasili araç için müşteri bulunamadı: '
                    'satırda bir teklif seçilmeli (veya sefere ana teklif atanmalı).')
            line_name = self.env._(
                '%(vehicle)s ile araç nakliyesi (%(count)s araç, şasi no: %(chassis)s)',
                vehicle=self.vehicle_id.license_plate,
                count=len(group_lines),
                chassis=', '.join(group_lines.mapped('chassis_number')),
            )
            order_line_vals = {
                'product_id': product.id,
                'product_uom_qty': len(group_lines),
                'name': line_name,
                'transport_trip_line_ids': [(6, 0, group_lines.ids)],
            }
            if price_per_vehicle:
                order_line_vals['price_unit'] = price_per_vehicle
            order_vals = {
                'partner_id': partner.id,
                'origin': self.name,
                'order_line': [(0, 0, order_line_vals)],
            }
            if lead and 'opportunity_id' in self.env['sale.order']._fields:
                order_vals['opportunity_id'] = lead.id
            order = self.env['sale.order'].create(order_vals)
            order.action_confirm()
            orders |= order
        return orders

    def action_view_sale_orders(self):
        self.ensure_one()
        if len(self.sale_order_ids) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Satış Siparişi',
                'res_model': 'sale.order',
                'view_mode': 'form',
                'res_id': self.sale_order_ids.id,
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Satış Siparişleri',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.sale_order_ids.ids)],
        }


class TransportTripLine(models.Model):
    _name = 'transport.trip.line'
    _description = 'Taşınan Araç (Şasi No)'
    _rec_name = 'chassis_number'
    _order = 'id'

    _chassis_unique = models.Constraint(
        'UNIQUE(trip_id, chassis_number)',
        'Bu şasi numarası bu seferde zaten okutuldu!',
    )

    trip_id = fields.Many2one('transport.trip', required=True, ondelete='cascade')
    lead_id = fields.Many2one(
        'crm.lead', string='Teklif',
        help='Bu araç hangi müşteri teklifine ait? Boş bırakılırsa seferin ana teklifi kullanılır. '
             'CRM dışında (teklifsiz) oluşturulan seferlerde boş bırakılabilir; bu durumda '
             'müşteri bu satırdan elle seçilir.')
    partner_id = fields.Many2one(
        'res.partner', string='Müşteri',
        help='Teklif seçilince otomatik doldurulur; CRM dışında (teklifsiz) oluşturulan '
             'seferlerde elle seçilebilir.')
    chassis_number = fields.Char(string='Şasi No (Barkod)', required=True)
    note = fields.Char(string='Not')
    pickup_location = fields.Char(
        string='Alım Yeri',
        help='Bu aracın teslim alınacağı yer. Teklifteki şasi satırından (gelen mailde '
             'yakalanmışsa) otomatik taşınır; elle de değiştirilebilir.')
    destination = fields.Char(
        string='Varış Yeri',
        help='Bu aracın teslim edileceği yer. Teklifteki şasi satırından (gelen mailde '
             'yakalanmışsa) otomatik taşınır; elle de değiştirilebilir.')
    pickup_odometer = fields.Float(
        string='Yüklendiği Km', readonly=True, copy=False,
        help='Bu araç çekiciye yüklendiğinde aracın kilometresi. Farklı müşterilerin araçları '
             'farklı duraklarda yüklenmişse, mesafe her satır için kendi yükleme kmsinden hesaplanır.')
    delivered = fields.Boolean(string='Teslim Edildi', default=False, readonly=True, copy=False)
    delivered_odometer = fields.Float(
        string='Teslim Edildiği Km', readonly=True, copy=False,
        help='Bu araç teslim edildiğinde çekicinin kilometresi (örn. 21000).')
    delivered_km = fields.Float(
        string='Kat Edilen Km', readonly=True, copy=False,
        help='Bu aracın yüklendiği km ile teslim edildiği km arasındaki fark (örn. 21000 - 20000 = 1000 km).')
    delivered_date = fields.Datetime(string='Teslim Tarihi', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            trip = self.env['transport.trip'].browse(vals['trip_id']) if vals.get('trip_id') else False
            if not vals.get('lead_id') and trip and trip.lead_id:
                vals['lead_id'] = trip.lead_id.id
            if not vals.get('partner_id'):
                if vals.get('lead_id'):
                    vals['partner_id'] = self.env['crm.lead'].browse(vals['lead_id']).partner_id.id
                elif trip and trip.partner_id:
                    # CRM dışında (teklifsiz) oluşturulan seferde ana müşteri varsa ondan
                    # miras alınır - hiçbiri yoksa satırda müşteri elle seçilir.
                    vals['partner_id'] = trip.partner_id.id
        lines = super().create(vals_list)
        # Sefer zaten başlamışken (seferde) listeye elle yeni satır eklendiğinde - "Yolda Yeni
        # Müşteri/Araç Ekle" sihirbazının dışında, doğrudan satır listesinden - müşterisi "araç
        # başı" olarak çözümlenen satırlar hemen faturalandırılır (aksi halde hiç
        # faturalandırılmazlardı). "Yolda Ekle" sihirbazı ve ilk toplu "Sefer Başlat" kendi
        # faturalamasını zaten yaptığı için transport_skip_auto_bill bağlamıyla burayı atlar.
        if not self.env.context.get('transport_skip_auto_bill'):
            for trip in lines.trip_id:
                if trip.state != 'confirmed':
                    continue
                trip_lines = lines.filtered(lambda line, trip=trip: line.trip_id == trip)
                orders = trip._bill_pending_per_vehicle(trip_lines)
                if orders:
                    trip.sale_order_ids = [(4, order.id) for order in orders]
        return lines

    @api.onchange('lead_id')
    def _onchange_lead_id(self):
        if self.lead_id:
            self.partner_id = self.lead_id.partner_id

    def action_open_damage_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasar Bildir',
            'res_model': 'transport.trip.line.damage.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_line_id': self.id},
        }

    def action_open_pickup_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Araç Teslim Al',
            'res_model': 'transport.trip.line.pickup.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_line_id': self.id},
        }

    def action_open_deliver_wizard(self):
        self.ensure_one()
        if self.delivered:
            raise UserError(f'{self.chassis_number} zaten teslim edilmiş.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Araç Teslim Et',
            'res_model': 'transport.trip.line.deliver.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_line_id': self.id},
        }

    @api.depends('chassis_number', 'partner_id')
    def _compute_display_name(self):
        for line in self:
            if line.partner_id:
                line.display_name = f"{line.chassis_number} ({line.partner_id.name})"
            else:
                line.display_name = line.chassis_number

    def _get_billing_groups(self):
        """Group these lines by their billing customer: the line's own müşteri (elle seçilmiş
        olabilir, CRM teklifi olmayan seferlerde de), yoksa teklifin/seferin müşterisi. Returns
        a list of {'partner', 'lead', 'lines'} dicts."""
        groups = defaultdict(lambda: {'partner': False, 'lead': False, 'lines': self.browse()})
        for line in self:
            lead = line.lead_id or line.trip_id.lead_id
            partner = line.partner_id or (lead.partner_id if lead else line.trip_id.partner_id)
            key = lead.id if lead else (partner.id if partner else False)
            group = groups[key]
            group['partner'] = partner
            group['lead'] = lead
            group['lines'] |= line
        return list(groups.values())
