from odoo import models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

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
        return self.env['transport.grupaj.trip'].search([('order_id', '=', self.id)], limit=1)

    def _get_transport_extra_product(self, product_xmlid):
        product_tmpl = self.env.ref(product_xmlid, raise_if_not_found=False)
        return product_tmpl.product_variant_id if product_tmpl else False

    def _add_transport_extra_line(self, product_xmlid, price):
        self.ensure_one()
        product = self._get_transport_extra_product(product_xmlid)
        if not product:
            raise UserError('İlgili ürün bulunamadı.')
        # Bu sipariş bir Grupaj Seferi'nden geldiyse, satırın tutarı taşıma adediyle çarpılır
        # (örn. 5 adet x 300 TL Avrupa Geçiş = 1500 TL); değilse tek satır (adet 1) eklenir.
        trip = self._get_related_grupaj_trip()
        qty = trip.quantity if trip else 1
        self.env['sale.order.line'].create({
            'order_id': self.id,
            'product_id': product.id,
            'product_uom_qty': qty,
            'price_unit': price,
        })

    def _check_europe_crossing_warning(self):
        """Bu sipariş Avrupa-Asya geçişli bir Grupaj Seferi'nden geliyorsa ve henüz bir Avrupa
        Geçiş satırı eklenmemişse, onayı durdurup kullanıcıya bir uyarı sihirbazı gösteren bir
        act_window döner; aksi halde False döner (onay normal şekilde devam eder)."""
        self.ensure_one()
        trip = self._get_related_grupaj_trip()
        if not trip or trip.route_continent != 'both':
            return False
        product = self._get_transport_extra_product('transport_fleet.product_transport_europe_crossing')
        if product and product in self.order_line.product_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Avrupa-Asya Geçişli Sefer',
            'res_model': 'transport.crossing.confirm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_confirm(self):
        # Sadece tek bir sipariş onaylanırken devreye girer (toplu onayda kesintisiz devam eder) -
        # sihirbaz "Devam Et" ile tekrar çağırdığında context bayrağıyla tekrar tetiklenmez.
        if not self.env.context.get('skip_crossing_check') and len(self) == 1:
            warn_action = self._check_europe_crossing_warning()
            if warn_action:
                return warn_action
        return super().action_confirm()
