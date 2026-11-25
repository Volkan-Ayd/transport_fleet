from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

OWNER_TYPES = [
    ('vehicle', 'Araç'),
    ('trailer', 'Dorse'),
    ('employee', 'Şoför'),
]

DOC_TYPES = [
    # Araç / Dorse
    ('inspection', 'Muayene'),
    ('traffic_insurance', 'Zorunlu Trafik Sigortası'),
    ('kasko', 'Kasko'),
    ('k_certificate', 'K Yetki Belgesi (K1/K2/U-NET)'),
    ('tachograph', 'Takograf Kalibrasyonu'),
    ('adr_vehicle', 'ADR Aracı Belgesi'),
    ('registration', 'Ruhsat'),
    # Şoför
    ('license', 'Ehliyet'),
    ('src', 'SRC Belgesi'),
    ('psychotechnic', 'Psikoteknik'),
    ('health', 'Sağlık Raporu'),
    ('adr_driver', 'ADR Sürücü Sertifikası'),
    ('other', 'Diğer'),
]

DOC_TYPES_BY_OWNER = {
    'vehicle': {'inspection', 'traffic_insurance', 'kasko', 'k_certificate',
                'tachograph', 'adr_vehicle', 'registration', 'other'},
    'trailer': {'inspection', 'traffic_insurance', 'kasko', 'adr_vehicle',
                'registration', 'other'},
    'employee': {'license', 'src', 'psychotechnic', 'health', 'adr_driver', 'other'},
}


class TransportDocument(models.Model):
    _name = 'transport.document'
    _description = 'Taşımacılık Belgesi'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expiry_date, id'

    name = fields.Char(compute='_compute_name', store=True)
    owner_type = fields.Selection(OWNER_TYPES, string='Belge Sahibi Tipi',
                                  required=True, default='vehicle')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Araç', ondelete='cascade', index=True)
    trailer_id = fields.Many2one('transport.trailer', string='Dorse', ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Şoför', ondelete='cascade', index=True,
                                  domain=[('is_driver', '=', True)])
    owner_name = fields.Char(compute='_compute_owner_name', string='Sahibi')
    doc_type = fields.Selection(DOC_TYPES, string='Belge Türü', required=True, tracking=True)
    reference = fields.Char(string='Belge / Poliçe No')
    issue_date = fields.Date(string='Başlangıç Tarihi')
    expiry_date = fields.Date(string='Bitiş Tarihi', tracking=True)
    alert_days = fields.Integer(string='Uyarı (gün önce)', default=30)
    status = fields.Selection([
        ('valid', 'Geçerli'),
        ('expiring', 'Süresi Yaklaşıyor'),
        ('expired', 'Süresi Dolmuş'),
    ], compute='_compute_status', string='Durum')
    responsible_id = fields.Many2one('res.users', string='Sorumlu',
                                     default=lambda self: self.env.user)
    attachment_ids = fields.Many2many('ir.attachment', string='Ekler')
    note = fields.Text(string='Not')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    last_alert_status = fields.Char(copy=False)

    @api.depends('doc_type', 'vehicle_id', 'trailer_id', 'employee_id', 'owner_type')
    def _compute_name(self):
        labels = dict(DOC_TYPES)
        for rec in self:
            owner = rec._get_owner_name()
            rec.name = ' - '.join(filter(None, [labels.get(rec.doc_type), owner]))

    def _get_owner_name(self):
        self.ensure_one()
        if self.owner_type == 'vehicle':
            return self.vehicle_id.license_plate or self.vehicle_id.display_name
        if self.owner_type == 'trailer':
            return self.trailer_id.license_plate
        return self.employee_id.name

    @api.depends('owner_type', 'vehicle_id', 'trailer_id', 'employee_id')
    def _compute_owner_name(self):
        for rec in self:
            rec.owner_name = rec._get_owner_name()

    @api.depends('expiry_date', 'alert_days')
    def _compute_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.expiry_date:
                rec.status = 'valid'
            elif rec.expiry_date < today:
                rec.status = 'expired'
            elif rec.expiry_date <= today + timedelta(days=rec.alert_days):
                rec.status = 'expiring'
            else:
                rec.status = 'valid'

    @api.constrains('owner_type', 'vehicle_id', 'trailer_id', 'employee_id', 'doc_type')
    def _check_owner(self):
        field_by_owner = {'vehicle': 'vehicle_id', 'trailer': 'trailer_id', 'employee': 'employee_id'}
        for rec in self:
            if not rec[field_by_owner[rec.owner_type]]:
                raise ValidationError('Belge sahibi (araç / dorse / şoför) seçilmelidir.')
            if rec.doc_type not in DOC_TYPES_BY_OWNER[rec.owner_type]:
                raise ValidationError('Seçilen belge türü bu belge sahibi tipi için geçerli değil.')

    def write(self, vals):
        if 'expiry_date' in vals:
            vals['last_alert_status'] = False
        return super().write(vals)

    @api.model
    def _cron_check_expiry(self):
        """Süresi yaklaşan / dolan belgeler için sorumluya bir kez aktivite oluşturur."""
        docs = self.search([('expiry_date', '!=', False)])
        for doc in docs:
            if doc.status == 'valid' or doc.last_alert_status == doc.status:
                continue
            summary = ('Belge süresi doldu: ' if doc.status == 'expired'
                       else 'Belge süresi yaklaşıyor: ') + (doc.name or '')
            doc.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=doc.expiry_date,
                summary=summary,
                user_id=(doc.responsible_id or self.env.user).id,
            )
            doc.last_alert_status = doc.status
