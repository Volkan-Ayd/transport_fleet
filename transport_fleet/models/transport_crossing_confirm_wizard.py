from odoo import fields, models


class TransportCrossingConfirmWizard(models.TransientModel):
    _name = 'transport.crossing.confirm.wizard'
    _description = 'Avrupa-Asya Geçişli Sefer Onay Uyarısı'

    order_id = fields.Many2one('sale.order', string='Sipariş')
    move_id = fields.Many2one('account.move', string='Fatura')

    def action_continue(self):
        """Uyarıyı görmezden gelip siparişi/faturayı olduğu gibi onaylar."""
        self.ensure_one()
        if self.order_id:
            return self.order_id.with_context(skip_crossing_check=True).action_confirm()
        return self.move_id.with_context(skip_crossing_check=True).action_post()

    def action_add_europe_crossing(self):
        """Avrupa Geçiş satırını ekler, siparişi/faturayı onaylamadan sihirbazı kapatır - tutar
        değiştiği için kullanıcı gözden geçirip onayı kendisi tekrar tetikler."""
        self.ensure_one()
        target = self.order_id or self.move_id
        target.action_add_europe_crossing_line()
        return {'type': 'ir.actions.act_window_close'}
