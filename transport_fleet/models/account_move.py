from odoo import fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    transport_driver_earning_ids = fields.One2many(
        'transport.driver.earning', 'move_id', string='Şoför Hakedişleri')

    def action_add_europe_crossing_line(self):
        self.ensure_one()
        self._add_transport_extra_line(
            'transport_fleet.product_transport_europe_crossing',
            self.env.company.transport_europe_crossing_price)

    def action_add_loading_unloading_line(self):
        self.ensure_one()
        self._add_transport_extra_line(
            'transport_fleet.product_transport_loading_unloading',
            self.env.company.transport_loading_unloading_price)

    def _get_related_grupaj_trip(self):
        self.ensure_one()
        orders = self.invoice_line_ids.sale_line_ids.order_id
        if not orders:
            return self.env['transport.grupaj.trip']
        return self.env['transport.grupaj.trip'].search([('order_id', 'in', orders.ids)], limit=1)

    def _get_transport_extra_product(self, product_xmlid):
        product_tmpl = self.env.ref(product_xmlid, raise_if_not_found=False)
        return product_tmpl.product_variant_id if product_tmpl else False

    def _add_transport_extra_line(self, product_xmlid, price):
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'out_refund'):
            raise UserError('Bu satır sadece satış faturalarına eklenebilir.')
        if self.state != 'draft':
            raise UserError('Onaylanmış bir faturaya yeni satır eklenemez.')
        product = self._get_transport_extra_product(product_xmlid)
        if not product:
            raise UserError('İlgili ürün bulunamadı.')
        # Bu fatura bir Grupaj Seferi'nin siparişinden geldiyse, satırın tutarı taşıma adediyle
        # çarpılır (örn. 5 adet x 300 TL Avrupa Geçiş = 1500 TL); değilse tek satır (adet 1) eklenir.
        trip = self._get_related_grupaj_trip()
        qty = trip.quantity if trip else 1
        self.env['account.move.line'].create({
            'move_id': self.id,
            'product_id': product.id,
            'quantity': qty,
            'price_unit': price,
        })

    def _check_europe_crossing_warning(self):
        """Bu fatura Avrupa-Asya geçişli bir Grupaj Seferi'nin siparişinden geliyorsa ve henüz
        bir Avrupa Geçiş satırı eklenmemişse, onayı durdurup kullanıcıya bir uyarı sihirbazı
        gösteren bir act_window döner; aksi halde False döner (onay normal şekilde devam eder)."""
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'out_refund'):
            return False
        trip = self._get_related_grupaj_trip()
        if not trip or trip.route_continent != 'both':
            return False
        product = self._get_transport_extra_product('transport_fleet.product_transport_europe_crossing')
        if product and product in self.invoice_line_ids.product_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Avrupa-Asya Geçişli Sefer',
            'res_model': 'transport.crossing.confirm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def action_post(self):
        # Sadece tek bir fatura onaylanırken devreye girer (toplu onayda kesintisiz devam eder) -
        # sihirbaz "Devam Et" ile tekrar çağırdığında context bayrağıyla tekrar tetiklenmez.
        if not self.env.context.get('skip_crossing_check') and len(self) == 1:
            warn_action = self._check_europe_crossing_warning()
            if warn_action:
                return warn_action
        return super().action_post()

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            for move in self:
                earnings = move.transport_driver_earning_ids
                if not earnings:
                    continue
                if move.state == 'posted':
                    earnings.filtered(lambda e: e.payment_state == 'to_pay').write({'payment_state': 'paid'})
                elif move.state in ('draft', 'cancel'):
                    # The journal entry was reset or cancelled before accounting confirmed it:
                    # free the earnings up again so they can be picked for payment once more.
                    earnings.filtered(lambda e: e.payment_state == 'paid').write({'payment_state': 'to_pay'})
        return res
