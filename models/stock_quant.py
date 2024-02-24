from odoo import api, fields, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    show_location_report = fields.Boolean(compute='compute_show_location_report', store=True)

    def compute_show_location_report(self):
        for quant_id in self:
            if quant_id.location_id.usage in ('production', 'transit'):
                quant_id.show_location_report = True
            else:
                quant_id.show_location_report = False
