from odoo import fields, models

from .transport_trip import PRICING_METHODS


class ResPartner(models.Model):
    _inherit = 'res.partner'

    transport_pricing_method = fields.Selection(
        PRICING_METHODS, string='Taşıma Ücretlendirmesi',
        help='Bu müşteriden gelen nakliye tekliflerinde ve seferlerde kullanılacak varsayılan '
             'ücretlendirme yöntemi (Araç Başı / Km Başı). Teklif üzerinde değiştirilebilir.')
