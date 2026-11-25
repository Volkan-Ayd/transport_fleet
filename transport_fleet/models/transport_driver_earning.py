from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError


class TransportDriverEarning(models.Model):
    _name = 'transport.driver.earning'
    _description = 'Şoför Hakedişi'
    _inherit = ['mail.thread']
    _order = 'id desc'

    trip_id = fields.Many2one('transport.trip', ondelete='cascade', string='Sefer')
    grupaj_trip_id = fields.Many2one(
        'transport.grupaj.trip', ondelete='cascade', string='Grupaj Seferi')
    driver_id = fields.Many2one('hr.employee', required=True, string='Şoför')
    vehicle_id = fields.Many2one(
        'fleet.vehicle', compute='_compute_vehicle_id', store=True, string='Çekici')
    date = fields.Date(string='Tarih', default=fields.Date.context_today)
    earning_type = fields.Selection([
        ('distance', 'Mesafe Hakedişi'),
        ('expense', 'Masraf İadesi'),
    ], string='Tür', default='distance', required=True)
    distance_km = fields.Float(
        string='Mesafe (Km)',
        help='Sefer başında girilen km ile tüm araçlar teslim edildiğinde girilen son km arasındaki fark. '
             'Dönüş yolundaki km dahil değildir.')
    rate_per_km = fields.Float(string='Km Ücreti')
    fleet_service_id = fields.Many2one(
        'fleet.vehicle.log.services', string='Bakım/Masraf Kaydı', readonly=True, copy=False)
    service_type_id = fields.Many2one(
        'fleet.service.type', related='fleet_service_id.service_type_id', store=True,
        string='Masraf Türü', help='Masraf İadesi türündeki hakedişlerde, masrafın türü.')
    expense_image = fields.Image(
        string='Fotoğraf', related='fleet_service_id.image_1920', max_width=256, max_height=256)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(string='Tutar', currency_field='currency_id')
    payment_state = fields.Selection([
        ('unpaid', 'Ödenmedi'),
        ('to_pay', 'Fiş Oluşturuldu (Onay Bekliyor)'),
        ('paid', 'Ödendi'),
        ('company_paid', 'Şirket Ödedi'),
    ], string='Ödeme Durumu', default='unpaid', tracking=True, copy=False,
        help='"Şirket Ödedi": masraf şirket kredi kartı veya EFT/Havale ile doğrudan ödendiği '
             'için bu kayıt sadece bilgi amaçlıdır, şoföre bu tutar için ayrıca ödeme yapılmaz.')
    move_id = fields.Many2one('account.move', string='Yevmiye Fişi', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('trip_id.vehicle_id', 'grupaj_trip_id.vehicle_id')
    def _compute_vehicle_id(self):
        for earning in self:
            earning.vehicle_id = earning.trip_id.vehicle_id or earning.grupaj_trip_id.vehicle_id

    @api.constrains('trip_id', 'grupaj_trip_id')
    def _check_trip_reference(self):
        for earning in self:
            if bool(earning.trip_id) == bool(earning.grupaj_trip_id):
                raise UserError(
                    'Şoför hakedişi tam olarak bir Sefer veya bir Grupaj Seferine bağlı olmalıdır.')

    def action_open_trip(self):
        self.ensure_one()
        if self.grupaj_trip_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Grupaj Seferi',
                'res_model': 'transport.grupaj.trip',
                'view_mode': 'form',
                'res_id': self.grupaj_trip_id.id,
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sefer',
            'res_model': 'transport.trip',
            'view_mode': 'form',
            'res_id': self.trip_id.id,
        }

    def action_open_fleet_service(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bakım/Masraf Kaydı',
            'res_model': 'fleet.vehicle.log.services',
            'view_mode': 'form',
            'res_id': self.fleet_service_id.id,
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

    def _get_expense_account(self):
        account = self.env.company.transport_driver_expense_account_id
        if not account:
            account = self.env['account.account'].search([
                ('account_type', '=', 'expense'),
                ('company_ids', 'in', self.env.company.id),
            ], limit=1)
        if not account:
            raise UserError(
                'Şoför hakedişi için gider hesabı bulunamadı. Ayarlar > Fleet > Taşımacılık\'tan '
                'bir hesap seçin.')
        return account

    def _get_payable_account(self):
        account = self.env.company.transport_driver_payable_account_id
        if not account:
            account = self.env['account.account'].search([
                ('account_type', '=', 'liability_payable'),
                ('company_ids', 'in', self.env.company.id),
            ], limit=1)
        if not account:
            raise UserError(
                'Şoför hakedişi için borç hesabı bulunamadı. Ayarlar > Fleet > Taşımacılık\'tan '
                'bir hesap seçin.')
        return account

    def action_pay_drivers(self):
        """Seçili hakediş kayıtlarını şoföre göre gruplayıp her şoför için bir yevmiye masraf fişi
        oluşturur. Zaten ödeme sürecinde veya ödenmiş olan kayıtlar atlanır (çift ödeme engeli)."""
        payable = self.filtered(lambda e: e.payment_state == 'unpaid')
        already_in_progress = self - payable
        if not payable:
            raise UserError('Seçili hakedişlerin hepsi zaten ödeme sürecinde veya ödenmiş.')
        expense_account = self._get_expense_account()
        payable_account = self._get_payable_account()
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'), ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError('Genel yevmiye defteri (journal) bulunamadı.')

        moves = self.env['account.move']
        by_driver = defaultdict(lambda: self.browse())
        for earning in payable:
            by_driver[earning.driver_id.id] |= earning

        for driver_id, earnings in by_driver.items():
            driver = self.env['hr.employee'].browse(driver_id)
            total = sum(earnings.mapped('amount'))
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': fields.Date.context_today(self),
                'ref': self.env._('%(driver)s şoför hakedişi ödemesi', driver=driver.name),
                'line_ids': [
                    (0, 0, {
                        'name': self.env._('%(driver)s hakediş/masraf ödemesi', driver=driver.name),
                        'account_id': expense_account.id,
                        'debit': total,
                        'credit': 0,
                    }),
                    (0, 0, {
                        'name': self.env._('%(driver)s hakediş/masraf ödemesi', driver=driver.name),
                        'account_id': payable_account.id,
                        'debit': 0,
                        'credit': total,
                    }),
                ],
            })
            earnings.write({'payment_state': 'to_pay', 'move_id': move.id})
            moves |= move

        if already_in_progress:
            already_in_progress.message_post(body=self.env._(
                'Bu hakediş zaten ödeme sürecinde veya ödenmiş olduğu için bu işlemde atlandı.'))

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
