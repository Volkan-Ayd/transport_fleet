from odoo import api, fields, models
from odoo.exceptions import UserError

from .crm_lead import _detect_route_continent


class CrmLeadGrupaj(models.Model):
    _name = 'crm.lead.grupaj'
    _description = 'Teklif - Grupaj Satırı'
    _rec_name = 'grupaj_no'
    _order = 'id'

    lead_id = fields.Many2one('crm.lead', required=True, ondelete='cascade')
    trip_id = fields.Many2one(
        'transport.grupaj.trip', string='Grupaj Seferi', readonly=True, copy=False,
        help='Bu satırdan "Sefer Başlat" ile oluşturulan Grupaj Seferi. Doluysa bu satır zaten '
             'sefere dönüştürülmüştür.')
    firma = fields.Char(string='Firma')
    # Aktivite Kodu ve Grupaj No örnek veride sayısal görünüyor ama ikisi de referans/kimlik
    # numarası - Integer tutulursa (a) Grupaj No gibi büyük değerler 32-bit sınırını (~2,1 milyar)
    # aşabilir, (b) arayüzde binlik ayraçlı ("16.110.822") gösterilir; ikisi de istenmiyor, bu
    # yüzden Char kullanılıyor.
    activity_code = fields.Char(string='Aktivite Kodu')
    grupaj_no = fields.Char(string='Grupaj No')
    start_date = fields.Date(string='Başlangıç Tarihi')
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Çekici Plaka',
        domain=[('transport_state', 'in', ('available', 'returning')), ('vehicle_type', '=', 'other')],
        context={'show_transport_status': True},
        help='Excel\'den aktarıldığında boş gelir - Taşımacılık sekmesindeki gibi buradan '
             'kendi filonuzdaki çekiciyi seçersiniz. Seçtiğinizde MT alanı o aracın şoförüyle '
             'otomatik doldurulur.')
    subcontractor_tractor_plate = fields.Char(string='Taşeron Çekici Plaka')
    route_info = fields.Char(string='Rota Bilgisi')
    quantity = fields.Integer(string='Miktar')
    activity_group_name = fields.Char(string='Aktivite Grup Adı')
    km = fields.Float(string='Kilometre')
    vehicle_coefficient = fields.Float(string='Araç Katsayısı')
    extra_km = fields.Float(string='İlave Km')
    invoice_status = fields.Char(string='Fatura Durumu')
    mt = fields.Char(string='MT')
    is_duplicate = fields.Boolean(
        compute='_compute_duplicate', string='Mükerrer',
        help='Aynı Aktivite Kodu + Grupaj No kombinasyonu geçmişte (başka bir teklifte/e-postada '
             'olabilir) başka bir satırda da var.')
    duplicate_info = fields.Char(compute='_compute_duplicate', string='Mükerrer Bilgisi')
    route_continent = fields.Selection([
        ('europe', 'Avrupa'),
        ('asia', 'Asya'),
        ('both', 'Avrupa-Asya (Geçişli)'),
    ], string='Rota Kıtası', compute='_compute_route_continent', store=True,
        help='Rota Bilgisi metninde geçen il (ve İstanbul/Çanakkale için ilçe) adları İl/İlçe/'
             'Mahalle Referansı tablosundaki kıta bilgisiyle karşılaştırılarak otomatik '
             'yakalanır (örn. İstanbul içi Avrupa/Asya yakası arası geçiş).')

    @api.depends('route_info')
    def _compute_route_continent(self):
        for rec in self:
            rec.route_continent = _detect_route_continent(rec.route_info)

    @api.depends('activity_code', 'grupaj_no')
    def _compute_duplicate(self):
        for rec in self:
            if not rec.activity_code or not rec.grupaj_no:
                rec.is_duplicate = False
                rec.duplicate_info = False
                continue
            others = self.search([
                ('activity_code', '=', rec.activity_code),
                ('grupaj_no', '=', rec.grupaj_no),
                ('id', '!=', rec.id),
            ])
            if not others:
                rec.is_duplicate = False
                rec.duplicate_info = False
                continue
            rec.is_duplicate = True
            trips = others.mapped('trip_id').filtered(lambda t: t)
            leads = ', '.join(others.mapped('lead_id.name'))
            if trips:
                rec.duplicate_info = self.env._(
                    'Bu aktivite kodu/grupaj no daha önce de geldi (%(lead)s) ve sefer '
                    'oluşturuldu: %(trips)s.',
                    lead=leads, trips=', '.join(trips.mapped('name')))
            else:
                rec.duplicate_info = self.env._(
                    'Bu aktivite kodu/grupaj no daha önce de geldi (%(lead)s), henüz sefer '
                    'oluşturulmamış.', lead=leads)

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id:
            self.mt = self.vehicle_id.transport_driver_id.name

    def action_start_trip(self):
        """Bu Grupaj satırından bir Grupaj Seferi oluşturur (satırdaki bilgiler sefer kartına
        kopyalanır) ve "Grupaj Seferleri" listesine ekler. Satır zaten bir sefere dönüştürülmüşse
        tekrar oluşturmaz, var olan seferi açar."""
        self.ensure_one()
        if not self.trip_id:
            if not self.vehicle_id:
                raise UserError('Sefer başlatmadan önce bu satıra bir çekici (Çekici Plaka) atamalısınız.')
            self.trip_id = self.env['transport.grupaj.trip'].create({
                'grupaj_id': self.id,
                'firma': self.firma,
                'activity_code': self.activity_code,
                'grupaj_no': self.grupaj_no,
                'start_date': self.start_date,
                'vehicle_id': self.vehicle_id.id,
                'subcontractor_tractor_plate': self.subcontractor_tractor_plate,
                'route_info': self.route_info,
                'quantity': self.quantity,
                'activity_group_name': self.activity_group_name,
                'km': self.km,
                'vehicle_coefficient': self.vehicle_coefficient,
                'extra_km': self.extra_km,
                'invoice_status': self.invoice_status,
                'mt': self.mt,
            }).id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Grupaj Seferi',
            'res_model': 'transport.grupaj.trip',
            'view_mode': 'form',
            'res_id': self.trip_id.id,
        }
