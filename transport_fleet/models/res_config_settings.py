from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    transport_default_pricing_method = fields.Selection(
        related='company_id.transport_default_pricing_method', readonly=False,
        string='Varsayılan Taşıma Ücretlendirmesi')
    transport_customer_price_per_vehicle = fields.Float(
        related='company_id.transport_customer_price_per_vehicle', readonly=False,
        string='Araç Başı Satış Fiyatı')
    transport_customer_price_per_km = fields.Float(
        related='company_id.transport_customer_price_per_km', readonly=False,
        string='Km Başı Satış Fiyatı')
    transport_default_trailer_capacity = fields.Selection(
        related='company_id.transport_default_trailer_capacity', readonly=False,
        string='Varsayılan Dorse Kapasitesi')
    transport_driver_rate_per_km = fields.Float(
        related='company_id.transport_driver_rate_per_km', readonly=False,
        string='Şoför Km Ücreti')
    transport_driver_expense_account_id = fields.Many2one(
        related='company_id.transport_driver_expense_account_id', readonly=False,
        string='Şoför Hakedişi Gider Hesabı')
    transport_driver_payable_account_id = fields.Many2one(
        related='company_id.transport_driver_payable_account_id', readonly=False,
        string='Şoför Hakedişi Borç Hesabı')
    transport_hgs_expense_account_id = fields.Many2one(
        related='company_id.transport_hgs_expense_account_id', readonly=False,
        string='HGS Masrafı Gider Hesabı')
    transport_hgs_payable_account_id = fields.Many2one(
        related='company_id.transport_hgs_payable_account_id', readonly=False,
        string='HGS Masrafı Borç Hesabı')
    transport_europe_crossing_price = fields.Float(
        related='company_id.transport_europe_crossing_price', readonly=False,
        string='Avrupa Geçiş Fiyatı')
    transport_loading_unloading_price = fields.Float(
        related='company_id.transport_loading_unloading_price', readonly=False,
        string='İndirme-Bindirme Fiyatı')
