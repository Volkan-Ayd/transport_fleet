from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    transport_trip_line_ids = fields.Many2many(
        'transport.trip.line', string='Taşınan Araçlar (Şasi No)',
        help='Bu satırda faturalandırılan şasi satırları. Km başı faturalamada birden fazla şasi '
             'tek satırda toplanabilir - mutabakat ekranı, düzeltmeyi bu bağlantı üzerinden yapar.')
