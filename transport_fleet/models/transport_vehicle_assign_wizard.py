from odoo import fields, models


class TransportVehicleAssignWizard(models.TransientModel):
    _name = 'transport.vehicle.assign.wizard'
    _description = 'Araca Teklif Ata / Sefer Başlat'

    vehicle_id = fields.Many2one('fleet.vehicle', required=True)
    lead_id = fields.Many2one(
        'crm.lead', string='Teklif', required=True,
        domain="[('transport_assignment_state', '=', 'pending')]",
        help='Henüz araç atanmamış (Bekliyor durumundaki) bir teklif seçin.')

    def action_confirm(self):
        self.ensure_one()
        self.lead_id.transport_vehicle_id = self.vehicle_id.id
        return self.lead_id.action_start_trip()
