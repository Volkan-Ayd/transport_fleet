from odoo import fields, models

from .transport_trip import PRICING_METHODS
from .transport_trailer import CAPACITY_SELECTION


class ResCompany(models.Model):
    _inherit = 'res.company'

    transport_default_pricing_method = fields.Selection(
        PRICING_METHODS, string='Varsayılan Taşıma Ücretlendirmesi', default='per_vehicle')
    transport_customer_price_per_vehicle = fields.Float(
        string='Araç Başı Satış Fiyatı', default=0.0,
        help='Ücretlendirme yöntemi "Araç Başı" olarak çözümlenen seferlerde, taşınan her araç '
             'için müşteriye faturalanacak birim fiyat. Hesaplama bu fiyat üzerinden yapılır '
             '(ürünün kendi satış fiyatı yerine). Varsayılan yöntem "Km Başı" olsa bile, hangi '
             'teklifte "Araç Başı" seçiliyse o teklif için bu fiyat kullanılır - ikisi '
             'birbirinden bağımsızdır.')
    transport_customer_price_per_km = fields.Float(
        string='Km Başı Satış Fiyatı', default=0.0,
        help='Ücretlendirme yöntemi "Km Başı" olarak çözümlenen seferlerde, teslim edilen her '
             'km için müşteriye faturalanacak birim fiyat. Hesaplama bu fiyat üzerinden yapılır '
             '(ürünün kendi satış fiyatı yerine). Varsayılan yöntem "Araç Başı" olsa bile, '
             'hangi teklifte "Km Başı" seçiliyse o teklif için bu fiyat kullanılır - ikisi '
             'birbirinden bağımsızdır.')
    transport_default_trailer_capacity = fields.Selection(
        CAPACITY_SELECTION, string='Varsayılan Dorse Kapasitesi', default='7')
    transport_driver_rate_per_km = fields.Float(
        string='Şoför Km Ücreti', default=10.0,
        help='Şoför hakedişi hesaplanırken sefer sırasında katedilen her km için ödenecek tutar '
             '(dönüş km hariç).')
    transport_driver_expense_account_id = fields.Many2one(
        'account.account', string='Şoför Hakedişi Gider Hesabı',
        help='Boş bırakılırsa gider tipi bir hesap otomatik aranır.')
    transport_driver_payable_account_id = fields.Many2one(
        'account.account', string='Şoför Hakedişi Borç Hesabı',
        help='Boş bırakılırsa borç (ödenecek) tipi bir hesap otomatik aranır.')
    transport_hgs_expense_account_id = fields.Many2one(
        'account.account', string='HGS Masrafı Gider Hesabı',
        help='Boş bırakılırsa gider tipi bir hesap otomatik aranır.')
    transport_hgs_payable_account_id = fields.Many2one(
        'account.account', string='HGS Masrafı Borç Hesabı',
        help='Boş bırakılırsa borç (ödenecek) tipi bir hesap otomatik aranır.')
    transport_europe_crossing_price = fields.Float(
        string='Avrupa Geçiş Fiyatı', default=0.0,
        help='Satış siparişi/faturaya "Avrupa Geçiş Ekle" ile yeni satır eklendiğinde '
             'kullanılacak birim fiyat.')
    transport_loading_unloading_price = fields.Float(
        string='İndirme-Bindirme Fiyatı', default=0.0,
        help='Satış siparişi/faturaya "İndirme-Bindirme Ekle" ile yeni satır eklendiğinde '
             'kullanılacak birim fiyat.')
