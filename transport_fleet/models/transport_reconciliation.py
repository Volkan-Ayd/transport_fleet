from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportReconciliationLine(models.Model):
    _name = 'transport.reconciliation.line'
    _description = 'Müşteri Km Mutabakatı'
    _order = 'id desc'

    partner_id = fields.Many2one('res.partner', string='Müşteri', required=True)
    chassis_number = fields.Char(string='Şasi No', required=True)
    customer_km = fields.Float(string='Müşteri Km', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    customer_price = fields.Monetary(
        string='Müşteri Ücreti', currency_field='currency_id', required=True)

    trip_line_id = fields.Many2one(
        'transport.trip.line', string='Eşleşen Sefer Satırı', compute='_compute_match', store=True)
    trip_id = fields.Many2one(
        'transport.trip', string='Sefer', related='trip_line_id.trip_id', store=True)
    order_line_id = fields.Many2one(
        'sale.order.line', string='Fatura Satırı', compute='_compute_match', store=True)
    order_id = fields.Many2one(
        'sale.order', string='Sipariş No', related='order_line_id.order_id', store=True)
    our_km = fields.Float(
        string='Bizim Km', related='trip_line_id.delivered_km', store=True)
    our_price = fields.Monetary(
        string='Bizim Ücretimiz', currency_field='currency_id', compute='_compute_match', store=True,
        help='Eşleşen fatura satırındaki toplam tutarın, bu şasinin kat ettiği km oranına göre '
             'bölüştürülmüş payı (tahmini - satır birden fazla şasiyi tek kalemde topluyorsa).')
    km_fark = fields.Float(
        string='Km Farkı', compute='_compute_farklar', store=True,
        help='Müşteri Km - Bizim Km.')
    price_fark = fields.Monetary(
        string='Ücret Farkı', currency_field='currency_id', compute='_compute_farklar', store=True,
        help='Müşteri Ücreti - Bizim Ücretimiz.')
    state = fields.Selection([
        ('unmatched', 'Eşleşmedi'),
        ('partner_mismatch', 'Şasi Başka Müşteride'),
        ('pending', 'Karşılaştırıldı'),
        ('applied', 'Düzeltildi'),
    ], string='Durum', compute='_compute_state', store=True)
    applied_date = fields.Datetime(string='Düzeltme Tarihi', readonly=True, copy=False)
    note = fields.Char(string='Not')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('chassis_number', 'partner_id')
    def _compute_match(self):
        for rec in self:
            rec.trip_line_id = False
            rec.order_line_id = False
            rec.our_price = 0.0
            if not rec.chassis_number:
                continue
            candidates = self.env['transport.trip.line'].search([
                ('chassis_number', '=', rec.chassis_number),
            ], order='id desc')
            if not candidates:
                continue
            match = candidates.filtered(lambda line: line.partner_id == rec.partner_id)[:1]
            if not match:
                # Şasi bizim kayıtlarımızda var ama farklı bir müşteriye ait - yanlış
                # müşteriye faturalama ihtimaline karşı ayrı bir durumda işaretlenir.
                rec.trip_line_id = candidates[0]
                continue
            rec.trip_line_id = match
            order_line = self.env['sale.order.line'].search([
                ('transport_trip_line_ids', 'in', match.id),
            ], limit=1)
            rec.order_line_id = order_line
            if order_line:
                group_lines = order_line.transport_trip_line_ids
                total_km = sum(group_lines.mapped('delivered_km'))
                share = (match.delivered_km / total_km) if total_km else 0.0
                rec.our_price = order_line.price_subtotal * share

    @api.depends('trip_line_id', 'order_line_id', 'applied_date')
    def _compute_state(self):
        for rec in self:
            if rec.applied_date:
                rec.state = 'applied'
            elif not rec.trip_line_id:
                rec.state = 'unmatched'
            elif rec.trip_line_id.partner_id != rec.partner_id:
                rec.state = 'partner_mismatch'
            elif not rec.order_line_id:
                rec.state = 'unmatched'
            else:
                rec.state = 'pending'

    @api.depends('customer_km', 'our_km', 'customer_price', 'our_price')
    def _compute_farklar(self):
        for rec in self:
            rec.km_fark = rec.customer_km - rec.our_km
            rec.price_fark = rec.customer_price - rec.our_price

    def action_open_trip(self):
        self.ensure_one()
        if not self.trip_id:
            raise UserError('Bu satır için eşleşen bir sefer bulunamadı.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sefer',
            'res_model': 'transport.trip',
            'view_mode': 'form',
            'res_id': self.trip_id.id,
        }

    def action_apply_customer_values(self):
        """Seçili (eşleşmiş, henüz düzeltilmemiş) satırlardaki müşteri km/ücretini kabul edip,
        bu şasilerin faturalandığı satış sipariş satırlarının km (miktar) ve birim fiyatını buna
        göre düzeltir. Aynı fatura satırında başka (bu düzeltmeye dahil edilmeyen) şasiler de
        varsa, onların mevcut payı değiştirilmeden korunur."""
        applicable = self.filtered(lambda r: r.state == 'pending')
        if not applicable:
            raise UserError(
                'Seçili satırlardan düzeltilebilecek (eşleşmiş ve henüz düzeltilmemiş) kayıt yok.')
        already_invoiced = applicable.filtered(
            lambda r: r.order_line_id.order_id.invoice_ids.filtered(lambda m: m.state == 'posted'))
        if already_invoiced:
            raise UserError(self.env._(
                'Şu şasilerin faturası zaten kesilmiş, buradan otomatik düzeltilemez (alacak '
                'dekontu gerekir): %(chassis)s',
                chassis=', '.join(already_invoiced.mapped('chassis_number')),
            ))

        km_product = self.env.ref('transport_fleet.product_transport_service_km', raise_if_not_found=False)
        km_product_id = km_product.product_variant_id.id if km_product else False

        by_order_line = defaultdict(lambda: self.browse())
        for rec in applicable:
            by_order_line[rec.order_line_id.id] |= rec

        for order_line_id, recs in by_order_line.items():
            order_line = self.env['sale.order.line'].browse(order_line_id)
            group_lines = order_line.transport_trip_line_ids
            old_total_km = sum(group_lines.mapped('delivered_km'))
            total_km = 0.0
            total_amount = 0.0
            km_by_chassis = {}  # satır açıklamasını yeniden yazmak için - düzeltilen şasilerde
            # müşterinin km'si, dokunulmayanlarda kendi orijinal km'si kullanılır.
            for trip_line in group_lines:
                rec = recs.filtered(lambda r, trip_line=trip_line: r.trip_line_id == trip_line)
                if rec:
                    total_km += rec[0].customer_km
                    total_amount += rec[0].customer_price
                    km_by_chassis[trip_line.chassis_number] = rec[0].customer_km
                else:
                    # Bu düzeltmeye dahil olmayan şasinin mevcut payını (orijinal fiyat üzerinden)
                    # olduğu gibi koru.
                    share = (trip_line.delivered_km / old_total_km) if old_total_km else 0.0
                    total_km += trip_line.delivered_km
                    total_amount += order_line.price_subtotal * share
                    km_by_chassis[trip_line.chassis_number] = trip_line.delivered_km
            new_price_unit = (total_amount / total_km) if total_km else order_line.price_unit
            write_vals = {'product_uom_qty': total_km, 'price_unit': new_price_unit}
            # Açıklama metni de ("... toplam X km (ŞASİ1 (Y km), ...)") düzeltilen km'lere göre
            # yeniden yazılır - sadece km başı ürünün satırlarında (araç başı satırında km hiç
            # geçmiyor, yazılacak bir şey yok).
            if km_product_id and order_line.product_id.id == km_product_id:
                vehicle = group_lines.trip_id.vehicle_id[:1]
                detail = ', '.join(
                    f"{chassis} ({km:g} km)" for chassis, km in km_by_chassis.items())
                write_vals['name'] = self.env._(
                    '%(vehicle)s ile taşıma - toplam %(km)s km (%(detail)s)',
                    vehicle=vehicle.license_plate or '-', km=total_km, detail=detail,
                )
            order_line.write(write_vals)
            order_line.order_id.message_post(body=self.env._(
                'Müşteri mutabakatı uygulandı: %(chassis)s şasi(leri) için km/ücret, müşterinin '
                'bildirdiği değerlere göre düzeltildi (yeni toplam: %(km)s km, %(amount)s).',
                chassis=', '.join(recs.mapped('chassis_number')), km=total_km, amount=total_amount,
            ))

        applicable.write({'state': 'applied', 'applied_date': fields.Datetime.now()})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Mutabakat uygulandı',
                'message': f'{len(applicable)} satır için fatura satırları düzeltildi.',
                'type': 'success',
            },
        }
