from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    transport_type = fields.Selection([
        ('tractor', 'Çekici (Tır)'),
        ('truck', 'Kamyon'),
        ('light_truck', 'Kamyonet / Panelvan'),
        ('other', 'Diğer'),
    ], string='Taşımacılık Tipi', default='tractor', tracking=True)
    transport_state = fields.Selection([
        ('available', 'Müsait'),
        ('on_trip', 'Seferde'),
        ('returning', 'Dönüş Yolunda'),
        ('maintenance', 'Bakımda'),
        ('breakdown', 'Arızalı'),
    ], string='Operasyon Durumu', default='available', required=True, tracking=True)
    axle_count = fields.Integer(string='Aks Sayısı', default=2)
    max_payload = fields.Float(string='Azami Yük (kg)')
    gross_weight = fields.Float(string='Azami Brüt Ağırlık (kg)')
    fuel_tank_capacity = fields.Float(string='Yakıt Deposu (L)')
    is_adr = fields.Boolean(string='ADR Uygun')
    hgs_tag = fields.Char(string='HGS / OGS No')
    transport_driver_id = fields.Many2one(
        'hr.employee', string='Atanmış Şoför', domain=[('is_driver', '=', True)], tracking=True)
    current_trailer_id = fields.Many2one(
        'transport.trailer', string='Bağlı Dorse', copy=False, tracking=True)
    document_ids = fields.One2many('transport.document', 'vehicle_id', string='Belgeler')
    expiring_document_count = fields.Integer(compute='_compute_expiring_document_count')
    current_trip_id = fields.Many2one(
        'transport.trip', string='Sefer', compute='_compute_current_trip_id',
        help='Aracın devam eden (seferde/dönüş yolunda) seferi varsa o; yoksa en son '
             'tamamlanan/iptal edilen seferi gösterir.')
    transport_state_since = fields.Datetime(
        string='Durum Değişim Zamanı', readonly=True, copy=False,
        help='Operasyon Durumu alanının en son değiştiği an.')
    transport_idle_hours = fields.Float(
        string='Müsait Olma Süresi (Saat)', compute='_compute_transport_idle_hours',
        help='Aracın en son "Müsait" ya da "Dönüş Yolunda" durumuna geçtiği andan bu yana '
             'geçen süre. Yeni iş atarken en uzun süredir boş duran aracı önceliklendirmek '
             'için kullanılır.')
    transport_driver_month_km = fields.Float(
        string='Bu Ay Katedilen Km (Şoför)', compute='_compute_transport_driver_month_km',
        help='Atanmış şoförün bu ay (hakediş kayıtlarına göre) kat ettiği toplam mesafe. İş '
             'yükünü adil dağıtmak için en az km yapan şoförü önceliklendirmek amacıyla '
             'kullanılır.')

    @api.depends('document_ids.status')
    def _compute_expiring_document_count(self):
        for rec in self:
            rec.expiring_document_count = len(
                rec.document_ids.filtered(lambda d: d.status != 'valid'))

    @api.depends('transport_state', 'transport_state_since')
    def _compute_transport_idle_hours(self):
        now = fields.Datetime.now()
        for vehicle in self:
            if vehicle.transport_state in ('available', 'returning') and vehicle.transport_state_since:
                vehicle.transport_idle_hours = (now - vehicle.transport_state_since).total_seconds() / 3600.0
            else:
                vehicle.transport_idle_hours = 0.0

    @api.depends('transport_driver_id')
    def _compute_transport_driver_month_km(self):
        month_start = fields.Date.context_today(self).replace(day=1)
        for vehicle in self:
            if not vehicle.transport_driver_id:
                vehicle.transport_driver_month_km = 0.0
                continue
            earnings = self.env['transport.driver.earning'].search([
                ('driver_id', '=', vehicle.transport_driver_id.id),
                ('earning_type', '=', 'distance'),
                ('date', '>=', month_start),
            ])
            vehicle.transport_driver_month_km = sum(earnings.mapped('distance_km'))

    def write(self, vals):
        if vals.get('transport_state') == 'available' and not self.env.context.get('transport_skip_return_guard'):
            # "Dönüşte" -> "Müsait" geçişi dönüş kmsini kaybetmeden sadece "Dönüş Tamamlandı"
            # sihirbazından yapılmalı. Bu geçişi kanban'da sürükleyerek (ya da formdan elle) direkt
            # yapmaya çalışmak - km bilgisi hiç girilmeden aracın müsaite geçmesine yol açardı.
            blocked = self.filtered(lambda v: v.transport_state == 'returning')
            if blocked:
                raise UserError(self.env._(
                    '%(vehicles)s dönüş yolunda. Durumu doğrudan "Müsait"e çekmek yerine '
                    '"Dönüş Tamamlandı" düğmesini kullanın - garaja ulaşıldığındaki km de '
                    'orada sorulur.',
                    vehicles=', '.join(blocked.mapped('license_plate')),
                ))
        changed = self.browse()
        if 'transport_state' in vals:
            changed = self.filtered(lambda v: v.transport_state != vals['transport_state'])
        res = super().write(vals)
        if changed:
            changed.transport_state_since = fields.Datetime.now()
        return res

    @api.depends('transport_state')
    def _compute_current_trip_id(self):
        for vehicle in self:
            trip = self.env['transport.trip'].search([
                ('vehicle_id', '=', vehicle.id), ('state', '=', 'confirmed'),
            ], limit=1)
            if not trip:
                trip = self.env['transport.trip'].search([
                    ('vehicle_id', '=', vehicle.id),
                ], order='id desc', limit=1)
            vehicle.current_trip_id = trip.id

    @api.depends('transport_state')
    @api.depends_context('show_transport_status')
    def _compute_display_name(self):
        super()._compute_display_name()
        if self.env.context.get('show_transport_status'):
            state_labels = dict(self._fields['transport_state'].selection)
            for rec in self:
                if rec.transport_state:
                    rec.display_name = f"{rec.display_name} ({state_labels.get(rec.transport_state)})"

    @api.onchange('transport_driver_id')
    def _onchange_transport_driver_id(self):
        contact = self.transport_driver_id.work_contact_id
        if contact:
            self.driver_id = contact

    @api.constrains('current_trailer_id')
    def _check_trailer_unique(self):
        for rec in self.filtered('current_trailer_id'):
            other = self.search([
                ('current_trailer_id', '=', rec.current_trailer_id.id),
                ('id', '!=', rec.id),
            ], limit=1)
            if other:
                raise ValidationError(
                    f'{rec.current_trailer_id.license_plate} dorsesi zaten '
                    f'{other.license_plate} plakalı çekiciye bağlı.')

    def action_view_transport_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Belgeler',
            'res_model': 'transport.document',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id, 'default_owner_type': 'vehicle'},
        }

    def action_assign_lead_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Teklif Ata / Sefer Başlat',
            'res_model': 'transport.vehicle.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_vehicle_id': self.id},
        }

    def action_open_return_wizard(self):
        """Şoför veya dispatcher, dönüş yolundaki araç depoya/garaja ulaştığında bunu tetikler.
        Boş dönüş mesafesinin de hesaplanabilmesi için garaja ulaşıldığındaki km'yi soran bir
        pencere açar (tek başına aracı müsaite almaz, gerçek işlem sihirbazda yapılır)."""
        self.ensure_one()
        if self.transport_state != 'returning':
            raise UserError(f'{self.license_plate} şu an dönüş yolunda değil.')
        trip = self.current_trip_id
        if not trip or trip.state != 'done' or trip.return_datetime:
            raise UserError(
                f'{self.license_plate} için dönüş bilgisi girilecek uygun bir sefer bulunamadı.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Dönüş Tamamlandı',
            'res_model': 'transport.trip.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_trip_id': trip.id},
        }

    def action_assign_to_lead_from_suggestion(self):
        """"Araç/Şoför Öner" penceresinden bir satır seçilip bu aksiyon çalıştırıldığında, o aracı
        önerinin açıldığı teklifin Ana Aracı olarak atar ve teklif kartına geri döner."""
        self.ensure_one()
        lead_id = self.env.context.get('suggest_for_lead_id')
        if not lead_id:
            raise UserError('Bu öneri hangi teklif için açıldığı bulunamadı.')
        lead = self.env['crm.lead'].browse(lead_id)
        lead.transport_vehicle_id = self.id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': lead.id,
        }
