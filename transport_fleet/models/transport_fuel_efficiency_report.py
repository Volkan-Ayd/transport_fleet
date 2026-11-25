from odoo import fields, models, tools


class TransportFuelEfficiencyReport(models.Model):
    _name = 'transport.fuel.efficiency.report'
    _description = 'Yakıt Verimliliği Raporu'
    _auto = False
    _order = 'date desc'

    trip_id = fields.Many2one('transport.trip', string='Sefer', readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='Çekici', readonly=True)
    driver_id = fields.Many2one('hr.employee', string='Şoför', readonly=True)
    company_id = fields.Many2one('res.company', string='Şirket', readonly=True)
    date = fields.Date(string='Tarih', readonly=True)
    liters = fields.Float(string='Alınan Yakıt (Litre)', readonly=True)
    distance_km = fields.Float(string='Katedilen Km', readonly=True)
    consumption_rate = fields.Float(
        string='Bu Alımın Oranı (L/Km)', digits=(16, 3), readonly=True,
        help='Bu yakıt alımından önceki alıma (yoksa sefer başlangıcına) kadar katedilen km '
             'başına harcanan yakıt.')
    vehicle_avg_rate = fields.Float(
        string='Aracın Genel Ortalaması (L/Km)', digits=(16, 3), readonly=True,
        help='Bu aracın bugüne kadarki tüm yakıt kayıtlarına göre ağırlıklı ortalama tüketimi '
             '(toplam litre / toplam km) - tek tek alımların ortalaması değil, gerçek toplam '
             'tüketim oranı.')
    is_outlier = fields.Boolean(
        string='Aykırı Değer', readonly=True,
        help='Bu alımın oranı, aracın genel ortalamasının %20\'den fazla üzerindeyse işaretlenir '
             '- arıza, usulsüzlük ya da hatalı giriş şüphesiyle incelenmeye değer.')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                SELECT
                    f.id AS id,
                    f.trip_id AS trip_id,
                    t.vehicle_id AS vehicle_id,
                    t.driver_id AS driver_id,
                    t.company_id AS company_id,
                    f.date::date AS date,
                    f.liters AS liters,
                    f.distance_since_last AS distance_km,
                    f.consumption_rate AS consumption_rate,
                    va.vehicle_avg_rate AS vehicle_avg_rate,
                    CASE
                        WHEN va.vehicle_avg_rate > 0 AND f.consumption_rate > va.vehicle_avg_rate * 1.2
                        THEN TRUE ELSE FALSE
                    END AS is_outlier
                FROM transport_trip_fuel f
                JOIN transport_trip t ON t.id = f.trip_id
                LEFT JOIN (
                    SELECT t2.vehicle_id AS vehicle_id,
                           CASE WHEN SUM(f2.distance_since_last) > 0
                                THEN SUM(f2.liters) / SUM(f2.distance_since_last)
                                ELSE 0 END AS vehicle_avg_rate
                    FROM transport_trip_fuel f2
                    JOIN transport_trip t2 ON t2.id = f2.trip_id
                    WHERE f2.distance_since_last > 0
                    GROUP BY t2.vehicle_id
                ) va ON va.vehicle_id = t.vehicle_id
                WHERE f.distance_since_last > 0
            )
        """)
