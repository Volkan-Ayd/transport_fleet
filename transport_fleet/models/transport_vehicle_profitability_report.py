from odoo import fields, models, tools


class TransportVehicleProfitabilityReport(models.Model):
    _name = 'transport.vehicle.profitability.report'
    _description = 'Araç/Şoför Kârlılık Analizi'
    _auto = False
    _order = 'date desc'

    trip_name = fields.Char(string='Sefer No', readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='Çekici', readonly=True)
    driver_id = fields.Many2one('hr.employee', string='Şoför', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Müşteri', readonly=True)
    lead_id = fields.Many2one('crm.lead', string='Teklif', readonly=True)
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('confirmed', 'Sefer Başladı'),
        ('done', 'Tamamlandı'),
    ], string='Sefer Durumu', readonly=True)
    company_id = fields.Many2one('res.company', string='Şirket', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Para Birimi', readonly=True)
    date = fields.Date(string='Tarih', readonly=True, help='Seferin başlama tarihi (yoksa oluşturulma tarihi).')
    revenue = fields.Monetary(
        string='Ciro (KDV Hariç)', currency_field='currency_id', readonly=True,
        help='Bu sefere ait satış siparişlerinin KDV hariç toplamı (iptal edilen siparişler '
             'hariç tutulur).')
    driver_cost = fields.Monetary(
        string='Şoför Hakedişi', currency_field='currency_id', readonly=True,
        help='Bu seferle ilgili tüm şoför hakedişi kayıtlarının (mesafe + masraf, ödeme '
             'durumundan bağımsız) toplamı.')
    fuel_cost = fields.Monetary(
        string='Yakıt Maliyeti', currency_field='currency_id', readonly=True,
        help='Bu seferde kaydedilen yakıt alımlarının (litre x birim fiyat) toplamı.')
    hgs_cost = fields.Monetary(
        string='HGS Maliyeti', currency_field='currency_id', readonly=True,
        help='Bu sefer sırasında (araç/saat eşleşmesiyle) bu sefere bağlanan HGS geçişlerinin '
             'toplam tutarı.')
    net_profit = fields.Monetary(
        string='Net Kâr', currency_field='currency_id', readonly=True,
        help='Ciro - (Şoför Hakedişi + Yakıt + HGS). Henüz faturalanmamış/tamamlanmamış '
             'seferlerde eksik veri nedeniyle gerçek değerden sapabilir.')
    return_distance_km = fields.Float(
        string='Boş Gidiş/Dönüş Km', readonly=True,
        help='Garajdan ilk teslim almaya (boş gidiş, varsa) ve teslimat bitişinden garaja '
             '(boş dönüş, dönüş tamamlandıysa) kadar yüksüz kat edilen toplam mesafe. Net kâr '
             'hesabına dahil edilmez, sadece bilgi/raporlama amaçlıdır.')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                SELECT
                    t.id AS id,
                    t.name AS trip_name,
                    t.vehicle_id AS vehicle_id,
                    t.driver_id AS driver_id,
                    t.partner_id AS partner_id,
                    t.lead_id AS lead_id,
                    t.state AS state,
                    t.company_id AS company_id,
                    rc.currency_id AS currency_id,
                    COALESCE(t.start_datetime, t.create_date)::date AS date,
                    t.return_distance_km AS return_distance_km,
                    COALESCE(rev.revenue, 0) AS revenue,
                    COALESCE(de.driver_cost, 0) AS driver_cost,
                    COALESCE(fu.fuel_cost, 0) AS fuel_cost,
                    COALESCE(hgs.hgs_cost, 0) AS hgs_cost,
                    COALESCE(rev.revenue, 0)
                        - COALESCE(de.driver_cost, 0)
                        - COALESCE(fu.fuel_cost, 0)
                        - COALESCE(hgs.hgs_cost, 0) AS net_profit
                FROM transport_trip t
                JOIN res_company rc ON rc.id = t.company_id
                LEFT JOIN (
                    SELECT rel.transport_trip_id AS trip_id, SUM(so.amount_untaxed) AS revenue
                    FROM sale_order_transport_trip_rel rel
                    JOIN sale_order so ON so.id = rel.sale_order_id
                    WHERE so.state != 'cancel'
                    GROUP BY rel.transport_trip_id
                ) rev ON rev.trip_id = t.id
                LEFT JOIN (
                    SELECT trip_id, SUM(amount) AS driver_cost
                    FROM transport_driver_earning
                    GROUP BY trip_id
                ) de ON de.trip_id = t.id
                LEFT JOIN (
                    SELECT trip_id, SUM(total_cost) AS fuel_cost
                    FROM transport_trip_fuel
                    GROUP BY trip_id
                ) fu ON fu.trip_id = t.id
                LEFT JOIN (
                    SELECT trip_id, SUM(amount) AS hgs_cost
                    FROM transport_hgs_record
                    WHERE trip_id IS NOT NULL
                    GROUP BY trip_id
                ) hgs ON hgs.trip_id = t.id
                WHERE t.state != 'cancelled'
            )
        """)
