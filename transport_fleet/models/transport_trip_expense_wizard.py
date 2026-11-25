import mimetypes

from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportTripExpenseWizard(models.TransientModel):
    _name = 'transport.trip.expense.wizard'
    _description = 'Sefere Masraf Ekle'

    trip_id = fields.Many2one('transport.trip')
    grupaj_trip_id = fields.Many2one('transport.grupaj.trip', string='Grupaj Seferi')
    vehicle_id = fields.Many2one('fleet.vehicle', compute='_compute_vehicle_driver', readonly=True)
    driver_id = fields.Many2one('hr.employee', compute='_compute_vehicle_driver', readonly=True)
    service_type_id = fields.Many2one(
        'fleet.service.type', string='Masraf Türü', required=True,
        help='Örn. Lastik Değiştirme, Arıza Giderme vb.')
    description = fields.Char(string='Açıklama')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(string='Tutar', currency_field='currency_id', required=True)
    payment_method = fields.Selection([
        ('cash', 'Nakit'),
        ('company_card', 'Şirket Kredi Kartı'),
        ('bank_transfer', 'EFT/Havale'),
    ], string='Ödeme Yöntemi', default='cash', required=True,
        help='Nakit: tutar şoförün cebinden çıktı, hakedişine iade olarak eklenir ve ona '
             'ödenebilir. Şirket Kredi Kartı / EFT-Havale: şirket doğrudan ödediği için '
             'tedarikçiye satınalma siparişi (RFQ) oluşturulur; bilgi amaçlı şoför hakedişine de '
             'eklenir ama bu kayıt için şoföre ayrıca ödeme yapılamaz (durumu "Şirket Ödedi").')
    vendor_id = fields.Many2one(
        'res.partner', string='Tedarikçi',
        help='Nakit dışında bir ödeme yöntemi seçildiyse, masrafın faturalanacağı tedarikçi/servis.')
    image_1920 = fields.Image(
        string='Fotoğraf (Fiş/Arıza)', max_width=1920, max_height=1920,
        help='Fiş, fatura veya arızanın fotoğrafı. Odoo bu görseli otomatik olarak 1920x1920 ile sınırlar.')

    @api.depends('trip_id.vehicle_id', 'trip_id.driver_id', 'grupaj_trip_id.vehicle_id', 'grupaj_trip_id.driver_id')
    def _compute_vehicle_driver(self):
        for wiz in self:
            ref = wiz.trip_id or wiz.grupaj_trip_id
            wiz.vehicle_id = ref.vehicle_id
            wiz.driver_id = ref.driver_id

    def action_confirm(self):
        self.ensure_one()
        if not self.trip_id and not self.grupaj_trip_id:
            raise UserError('Sefer bulunamadı.')
        if not self.amount:
            raise UserError('Masraf tutarı girilmelidir.')
        if self.payment_method != 'cash' and not self.vendor_id:
            raise UserError('Nakit dışında bir ödeme yöntemi seçildiyse bir tedarikçi seçmelisiniz.')
        trip = self.trip_id or self.grupaj_trip_id
        trip_model = 'transport.trip' if self.trip_id else 'transport.grupaj.trip'
        vehicle = trip.vehicle_id
        driver = trip.driver_id

        service_vals = {
            'vehicle_id': vehicle.id,
            'service_type_id': self.service_type_id.id,
            'amount': self.amount,
            'description': self.description or self.service_type_id.name,
            'date_from': fields.Date.context_today(self),
            'state': 'done',
            'image_1920': self.image_1920,
        }
        if self.payment_method == 'cash' and driver.work_contact_id:
            service_vals['purchaser_id'] = driver.work_contact_id.id
        elif self.vendor_id:
            service_vals['vendor_id'] = self.vendor_id.id
        service = self.env['fleet.vehicle.log.services'].create(service_vals)

        # Fotoğraf masraf kaydının kendi "Fotoğraf" alanında kalır (yukarıda image_1920 ile
        # zaten kaydedildi), ama ayrıca gerçek bir ek olarak sefer chatter'ına da taşınır ki
        # masrafla ilgili tüm bilgiler (tutar, tür, ödeme yöntemi) ve fotoğraf aynı mesajda
        # tek bakışta görülebilsin.
        attachment = self.env['ir.attachment']
        if self.image_1920:
            ext = mimetypes.guess_extension(self.image_1920.mimetype) or '.png'
            safe_type_name = self.service_type_id.name.replace('/', '-')
            attachment = self.env['ir.attachment'].create({
                'name': f'masraf_{safe_type_name}{ext}',
                'raw': self.image_1920.content,
                'res_model': trip_model,
                'res_id': trip.id,
            })

        if self.payment_method == 'cash':
            if not driver:
                raise UserError('Bu sefere atanmış bir şoför bulunamadı.')
            earning = self.env['transport.driver.earning'].create({
                'trip_id': self.trip_id.id if self.trip_id else False,
                'grupaj_trip_id': self.grupaj_trip_id.id if self.grupaj_trip_id else False,
                'driver_id': driver.id,
                'earning_type': 'expense',
                'amount': self.amount,
                'fleet_service_id': service.id,
            })
            if attachment:
                earning.message_post(body=self.env._(
                    '%(vehicle)s için %(amount)s tutarında masraf (%(type)s), nakit ödendi.',
                    vehicle=vehicle.license_plate, amount=self.amount,
                    type=self.service_type_id.name,
                ), attachment_ids=attachment.ids)
            trip.message_post(body=self.env._(
                '%(driver)s, %(vehicle)s için %(amount)s tutarında masraf yaptı (%(type)s) ve kendisi '
                'nakit ödedi; hakedişine eklendi.',
                driver=driver.name, vehicle=vehicle.license_plate, amount=self.amount,
                type=self.service_type_id.name,
            ), attachment_ids=attachment.ids)
            return {
                'type': 'ir.actions.act_window',
                'name': 'Şoför Hakedişi',
                'res_model': 'transport.driver.earning',
                'view_mode': 'form',
                'res_id': earning.id,
            }

        # Şirket Kredi Kartı / EFT-Havale: şirket doğrudan ödedi, tedarikçiye satınalma siparişi
        # oluşturulur. Bilgi amaçlı şoför hakedişine de eklenir, ama bu kayıt için şoföre ayrıca
        # ödeme yapılamaz (durumu baştan "Şirket Ödedi" olarak sabitlenir).
        product_tmpl = self.env.ref('transport_fleet.product_transport_expense', raise_if_not_found=False)
        product = product_tmpl.product_variant_id if product_tmpl else False
        if not product:
            raise UserError('Araç masrafı ürünü bulunamadı.')
        purchase_order = self.env['purchase.order'].create({
            'partner_id': self.vendor_id.id,
            'origin': trip.name,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': self.description or self.service_type_id.name,
                'product_qty': 1,
                'price_unit': self.amount,
            })],
        })
        service.vendor_id = self.vendor_id.id
        if driver:
            company_earning = self.env['transport.driver.earning'].create({
                'trip_id': self.trip_id.id if self.trip_id else False,
                'grupaj_trip_id': self.grupaj_trip_id.id if self.grupaj_trip_id else False,
                'driver_id': driver.id,
                'earning_type': 'expense',
                'amount': self.amount,
                'fleet_service_id': service.id,
                'payment_state': 'company_paid',
            })
            if attachment:
                company_earning.message_post(body=self.env._(
                    '%(vehicle)s için %(amount)s tutarında masraf (%(type)s), şirket ödedi.',
                    vehicle=vehicle.license_plate, amount=self.amount,
                    type=self.service_type_id.name,
                ), attachment_ids=attachment.ids)
        payment_method_label = dict(self._fields['payment_method'].selection).get(self.payment_method)
        trip.message_post(body=self.env._(
            '%(vehicle)s için %(amount)s tutarında masraf oluştu (%(type)s), şirket %(method)s ile '
            'ödedi. %(vendor)s\'a satınalma siparişi (%(po)s) oluşturuldu.',
            vehicle=vehicle.license_plate, amount=self.amount, type=self.service_type_id.name,
            method=payment_method_label, vendor=self.vendor_id.name, po=purchase_order.name,
        ), attachment_ids=attachment.ids)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Satınalma Siparişi',
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'res_id': purchase_order.id,
        }
