from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    is_driver = fields.Boolean(string='Şoför')
    license_class = fields.Selection([
        ('B', 'B'), ('C', 'C'), ('CE', 'CE'),
        ('D', 'D'), ('DE', 'DE'),
    ], string='Ehliyet Sınıfı')
    driver_state = fields.Selection([
        ('available', 'Müsait'),
        ('on_trip', 'Seferde'),
        ('rest', 'Dinlenmede'),
        ('leave', 'İzinli'),
    ], string='Şoför Durumu', default='available')
    document_ids = fields.One2many('transport.document', 'employee_id', string='Belgeler')
    expiring_document_count = fields.Integer(compute='_compute_expiring_document_count')
    assigned_vehicle_ids = fields.One2many('fleet.vehicle', 'transport_driver_id', string='Atanmış Araçlar')

    @api.depends('document_ids.status')
    def _compute_expiring_document_count(self):
        for rec in self:
            rec.expiring_document_count = len(
                rec.document_ids.filtered(lambda d: d.status != 'valid'))

    def action_view_transport_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Belgeler',
            'res_model': 'transport.document',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id, 'default_owner_type': 'employee'},
        }
