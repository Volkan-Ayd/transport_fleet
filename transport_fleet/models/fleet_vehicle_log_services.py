from odoo import fields, models


class FleetVehicleLogServices(models.Model):
    _inherit = 'fleet.vehicle.log.services'

    image_1920 = fields.Image(string='Fotoğraf (Fiş/Arıza)', max_width=1920, max_height=1920)
