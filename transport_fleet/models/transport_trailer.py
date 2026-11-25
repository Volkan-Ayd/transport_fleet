from odoo import api, fields, models

CAPACITY_SELECTION = [(str(i), str(i)) for i in range(1, 11)]


class TransportTrailer(models.Model):
    _name = 'transport.trailer'
    _description = 'Dorse'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'license_plate'
    _order = 'license_plate'

    _plate_unique = models.Constraint(
        'UNIQUE(license_plate, company_id)',
        'Bu plaka zaten kayıtlı!',
    )

    license_plate = fields.Char(string='Plaka', required=True, tracking=True)
    trailer_type = fields.Selection([
        ('curtain', 'Tenteli'),
        ('reefer', 'Frigorifik'),
        ('flatbed', 'Açık Kasa / Platform'),
        ('lowbed', 'Lowbed'),
        ('tanker', 'Tanker'),
        ('container', 'Konteyner Taşıyıcı'),
        ('tipper', 'Damperli'),
        ('other', 'Diğer'),
    ], string='Dorse Tipi', default='curtain', required=True, tracking=True)
    brand = fields.Char(string='Marka')
    model_year = fields.Integer(string='Model Yılı')
    axle_count = fields.Integer(string='Aks Sayısı', default=3)
    max_payload = fields.Float(string='Azami Yük (kg)')
    volume_m3 = fields.Float(string='Hacim (m³)')
    length_m = fields.Float(string='Uzunluk (m)')
    state = fields.Selection([
        ('available', 'Müsait'),
        ('on_trip', 'Seferde'),
        ('returning', 'Dönüş Yolunda'),
        ('maintenance', 'Bakımda'),
        ('breakdown', 'Arızalı'),
    ], string='Durum', default='available', required=True, tracking=True)
    tractor_ids = fields.One2many('fleet.vehicle', 'current_trailer_id', string='Bağlı Çekici')
    tractor_id = fields.Many2one('fleet.vehicle', string='Çekici', compute='_compute_tractor_id')
    document_ids = fields.One2many('transport.document', 'trailer_id', string='Belgeler')
    expiring_document_count = fields.Integer(compute='_compute_expiring_document_count')
    capacity = fields.Selection(
        CAPACITY_SELECTION, string='Kapasite (Araç Sayısı)', default='7', required=True, tracking=True,
        help='Bu dorsenin aynı anda taşıyabileceği araç sayısı.')
    note = fields.Text(string='Not')
    gps_device_id = fields.Char(
        string='GPS Takip Cihazı No',
        help='Bu dorseye takılı GPS takip cihazının seri/ID numarası (varsa).')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Şirket', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('capacity'):
                vals['capacity'] = self.env.company.transport_default_trailer_capacity or '7'
        return super().create(vals_list)

    @api.depends('tractor_ids')
    def _compute_tractor_id(self):
        for rec in self:
            rec.tractor_id = rec.tractor_ids[:1]

    @api.depends('document_ids.status')
    def _compute_expiring_document_count(self):
        for rec in self:
            rec.expiring_document_count = len(
                rec.document_ids.filtered(lambda d: d.status != 'valid'))

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Belgeler',
            'res_model': 'transport.document',
            'view_mode': 'list,form',
            'domain': [('trailer_id', '=', self.id)],
            'context': {'default_trailer_id': self.id, 'default_owner_type': 'trailer'},
        }
