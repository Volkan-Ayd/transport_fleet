from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportHgsRecord(models.Model):
    _name = 'transport.hgs.record'
    _description = 'HGS Geçiş Kaydı'
    _inherit = ['mail.thread']
    _order = 'entry_date desc, id desc'

    _reference_no_unique = models.Constraint(
        'UNIQUE(reference_no)',
        'Bu referans numaralı HGS kaydı zaten içeri aktarılmış (aynı Excel dosyası iki kez '
        'yüklenmiş olabilir).',
    )

    license_plate = fields.Char(string='Plaka', required=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Araç', compute='_compute_vehicle_id', store=True,
        help='Plaka metnine göre otomatik eşleşen araç. Eşleşme bulunamazsa masraf '
             'oluşturulamaz, önce Çekiciler/Araçlar listesinde plakanın doğru yazıldığından '
             'emin olun.')
    trip_id = fields.Many2one(
        'transport.trip', string='Sefer', compute='_compute_trip_id', store=True,
        help='Giriş tarihi/saati, aracın o an sürmekte olduğu seferin başlama ve bitiş '
             'saatleri arasına denk geliyorsa otomatik doldurulur.')
    trailer_plate = fields.Char(string='Dorse Plaka')
    hgs_card_no = fields.Char(string='HGS Kart No')
    entry_date = fields.Datetime(string='Giriş Tarihi')
    exit_date = fields.Datetime(string='Çıkış Tarihi')
    entry_station = fields.Char(string='Giriş İstasyonu')
    exit_station = fields.Char(string='Çıkış İstasyonu')
    province = fields.Char(string='İl')
    district = fields.Char(string='İlçe')
    terminal = fields.Char(string='Terminal')
    vat_percent = fields.Float(string='KDV (%)')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(string='Tutar (₺)', currency_field='currency_id', required=True)
    reference_no = fields.Char(string='Referans No')
    system_date = fields.Datetime(string='Sistem Tarihi')
    invoice_no = fields.Char(string='Fatura No')
    expense_state = fields.Selection([
        ('pending', 'Beklemede'),
        ('done', 'Masraf Oluşturuldu'),
    ], string='Masraf Durumu', default='pending', readonly=True, copy=False, tracking=True)
    move_id = fields.Many2one('account.move', string='Yevmiye Fişi', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('license_plate')
    def _compute_vehicle_id(self):
        vehicles = self.env['fleet.vehicle'].search([('license_plate', '!=', False)])
        by_plate = {
            (v.license_plate or '').upper().replace(' ', ''): v for v in vehicles
        }
        for rec in self:
            key = (rec.license_plate or '').upper().replace(' ', '')
            rec.vehicle_id = by_plate.get(key, self.env['fleet.vehicle'])

    @api.depends('vehicle_id', 'entry_date')
    def _compute_trip_id(self):
        for rec in self:
            rec.trip_id = False
            if not rec.vehicle_id or not rec.entry_date:
                continue
            rec.trip_id = self.env['transport.trip'].search([
                ('vehicle_id', '=', rec.vehicle_id.id),
                ('state', '!=', 'cancelled'),
                ('start_datetime', '!=', False),
                ('start_datetime', '<=', rec.entry_date),
                '|', ('end_datetime', '=', False), ('end_datetime', '>=', rec.entry_date),
            ], order='start_datetime desc', limit=1)

    @api.depends('license_plate', 'amount', 'entry_date')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.license_plate or '?']
            if rec.entry_date:
                parts.append(fields.Datetime.to_string(rec.entry_date))
            if rec.amount:
                parts.append(f'{rec.amount:g} ₺')
            rec.display_name = ' - '.join(parts)

    def _get_hgs_expense_account(self):
        account = self.env.company.transport_hgs_expense_account_id
        if not account:
            account = self.env['account.account'].search([
                ('account_type', '=', 'expense'),
                ('company_ids', 'in', self.env.company.id),
            ], limit=1)
        if not account:
            raise UserError(
                'HGS masrafı için gider hesabı bulunamadı. Ayarlar > Fleet > Taşımacılık\'tan '
                'bir hesap seçin.')
        return account

    def _get_hgs_payable_account(self):
        account = self.env.company.transport_hgs_payable_account_id
        if not account:
            account = self.env['account.account'].search([
                ('account_type', '=', 'liability_payable'),
                ('company_ids', 'in', self.env.company.id),
            ], limit=1)
        if not account:
            raise UserError(
                'HGS masrafı için borç hesabı bulunamadı. Ayarlar > Fleet > Taşımacılık\'tan '
                'bir hesap seçin.')
        return account

    def action_create_expense(self):
        """Seçili HGS kayıtlarını plaka (araç) bazında gruplayıp her araç için tek bir yevmiye
        masraf fişi oluşturur - tutarlar toplanır. Zaten masrafa dönüştürülmüş kayıtlar atlanır
        (çift masraflandırmayı engeller)."""
        pending = self.filtered(lambda rec: rec.expense_state == 'pending')
        already_done = self - pending
        if not pending:
            raise UserError('Seçili kayıtların hepsi zaten masrafa dönüştürülmüş.')
        unmatched = pending.filtered(lambda rec: not rec.vehicle_id)
        if unmatched:
            raise UserError(self.env._(
                'Şu plakalar için araç eşleşmedi: %(plates)s. Önce Çekiciler/Araçlar '
                'listesinde plakanın doğru yazıldığından emin olun.',
                plates=', '.join(sorted(set(unmatched.mapped('license_plate')))),
            ))

        expense_account = self._get_hgs_expense_account()
        payable_account = self._get_hgs_payable_account()
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'), ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError('Genel yevmiye defteri (journal) bulunamadı.')

        moves = self.env['account.move']
        by_vehicle = defaultdict(lambda: self.browse())
        for rec in pending:
            by_vehicle[rec.vehicle_id.id] |= rec

        for vehicle_id, records in by_vehicle.items():
            vehicle = self.env['fleet.vehicle'].browse(vehicle_id)
            total = sum(records.mapped('amount'))
            line_name = self.env._(
                '%(vehicle)s HGS masrafı (%(count)s geçiş)',
                vehicle=vehicle.license_plate, count=len(records))
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': fields.Date.context_today(self),
                'ref': line_name,
                'line_ids': [
                    (0, 0, {
                        'name': line_name, 'account_id': expense_account.id,
                        'debit': total, 'credit': 0,
                    }),
                    (0, 0, {
                        'name': line_name, 'account_id': payable_account.id,
                        'debit': 0, 'credit': total,
                    }),
                ],
            })
            records.write({'move_id': move.id, 'expense_state': 'done'})
            moves |= move

        if already_done:
            already_done.message_post(body=self.env._(
                'Bu kayıt zaten bir masraf fişine dönüştürülmüş olduğu için bu işlemde atlandı.'))

        if len(moves) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Yevmiye Fişi',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': moves.id,
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yevmiye Fişleri',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
        }

    def action_open_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yevmiye Fişi',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }
