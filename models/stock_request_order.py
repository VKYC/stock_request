# Copyright 2018 Creu Blanca
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class StockRequestOrder(models.Model):
    _name = "stock.request.order"
    _description = "Stock Request Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        warehouse = None
        if "warehouse_id" not in res and res.get("company_id"):
            warehouse = self.env["stock.warehouse"].search(
                [("company_id", "=", res["company_id"])], limit=1
            )
        if warehouse:
            res["warehouse_id"] = warehouse.id
            res["location_id"] = warehouse.lot_stock_id.id
        return res

    def __get_request_order_states(self):
        return self.env["stock.request"].fields_get(allfields=["state"])["state"][
            "selection"
        ]

    def _get_request_order_states(self):
        return self.__get_request_order_states()

    def _get_default_requested_by(self):
        return self.env["res.users"].browse(self.env.uid)

    name = fields.Char(
        copy=False,
        required=True,
        readonly=True,
        states={"draft": [("readonly", False)]},
        default="/",
    )
    state = fields.Selection(
        selection=_get_request_order_states,
        string="Status",
        copy=False,
        default="draft",
        index=True,
        readonly=True,
        tracking=True,
        compute="_compute_state",
        store=True,
    )
    requested_by = fields.Many2one(
        "res.users",
        required=True,
        tracking=True,
        default=lambda s: s._get_default_requested_by(),
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Warehouse",
        check_company=True,
        readonly=True,
        ondelete="cascade",
        required=True,
        states={"draft": [("readonly", False)]},
    )
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location",
        domain="not allow_virtual_location and "
        "[('usage', 'in', ['internal', 'transit'])] or []",
        readonly=True,
        ondelete="cascade",
        required=True,
        states={"draft": [("readonly", False)]},
    )
    allow_virtual_location = fields.Boolean(
        related="company_id.stock_request_allow_virtual_loc", readonly=True
    )
    procurement_group_id = fields.Many2one(
        "procurement.group",
        "Procurement Group",
        readonly=True,
        states={"draft": [("readonly", False)]},
        help="Moves created through this stock request will be put in this "
        "procurement group. If none is given, the moves generated by "
        "procurement rules will be grouped into one big picking.",
    )
    company_id = fields.Many2one(
        "res.company",
        "Company",
        required=True,
        readonly=True,
        states={"draft": [("readonly", False)]},
        default=lambda self: self.env.company,
    )
    expected_date = fields.Datetime(
        default=fields.Datetime.now,
        index=True,
        required=True,
        readonly=True,
        states={"draft": [("readonly", False)]},
        help="Date when you expect to receive the goods.",
    )
    picking_policy = fields.Selection(
        [
            ("direct", "Receive each product when available"),
            ("one", "Receive all products at once"),
        ],
        string="Shipping Policy",
        required=True,
        readonly=True,
        states={"draft": [("readonly", False)]},
        default="direct",
    )
    move_ids = fields.One2many(
        comodel_name="stock.move",
        compute="_compute_move_ids",
        string="Stock Moves",
        readonly=True,
    )
    picking_ids = fields.One2many(
        "stock.picking",
        compute="_compute_picking_ids",
        string="Pickings",
        readonly=True,
    )
    picking_count = fields.Integer(
        string="Delivery Orders", compute="_compute_picking_ids", readonly=True
    )
    stock_request_ids = fields.One2many(
        "stock.request", inverse_name="order_id", copy=True
    )
    stock_request_count = fields.Integer(
        string="Stock requests", compute="_compute_stock_request_count", readonly=True
    )
    route_ids = fields.Many2many(comodel_name='stock.location.route', compute='compute_route_ids', string='Ruta')

    _sql_constraints = [
        ("name_uniq", "unique(name, company_id)", "Stock Request name must be unique")
    ]

    def compute_route_ids(self):
        for order_id in self:
            route_ids = self.env['stock.location.route']
            for request_id in order_id.stock_request_ids:
                if request_id.route_id not in route_ids:
                    route_ids += request_id.route_id
            order_id.route_ids = route_ids

    @api.depends("stock_request_ids.state")
    def _compute_state(self):
        for item in self:
            states = item.stock_request_ids.mapped("state")
            if not item.stock_request_ids or all(x == "draft" for x in states):
                item.state = "draft"
            elif all(x == "cancel" for x in states):
                item.state = "cancel"
            elif all(x in ("done", "cancel") for x in states):
                item.state = "done"
            else:
                item.state = "open"

    @api.depends("stock_request_ids.allocation_ids")
    def _compute_picking_ids(self):
        for record in self:
            record.picking_ids = record.stock_request_ids.mapped("picking_ids")
            record.picking_count = len(record.picking_ids)

    @api.onchange('stock_request_ids')
    def _onchange_stock_request_ids(self):
        for order_id in self:
            for request_id in order_id.stock_request_ids:
                if request_id.product_uom_qty and len(request_id.route_id.rule_ids) > 1:
                    available_qty = self.env["stock.quant"].\
                        _get_available_quantity(request_id.product_id, request_id.route_id.rule_ids[0].location_src_id)
                    if available_qty <= 0:
                        raise UserError(f"No hay cantidad disponible de productos: {request_id.product_id.display_name}"
                                        f" en esta ruta {request_id.route_id.name}.")
                    elif available_qty == request_id.product_uom_qty or available_qty <= request_id.product_uom_qty:
                        request_id.product_uom_qty = available_qty



    @api.depends("stock_request_ids")
    def _compute_move_ids(self):
        for record in self:
            record.move_ids = record.stock_request_ids.mapped("move_ids")

    @api.depends("stock_request_ids")
    def _compute_stock_request_count(self):
        for record in self:
            record.stock_request_count = len(record.stock_request_ids)

    @api.onchange("requested_by")
    def onchange_requested_by(self):
        self.change_childs()

    @api.onchange("expected_date")
    def onchange_expected_date(self):
        self.change_childs()

    @api.onchange("picking_policy")
    def onchange_picking_policy(self):
        self.change_childs()

    @api.onchange("location_id")
    def onchange_location_id(self):
        if self.location_id:
            loc_wh = self.location_id.warehouse_id
            if loc_wh and self.warehouse_id != loc_wh:
                self.warehouse_id = loc_wh
                self.with_context(no_change_childs=True).onchange_warehouse_id()
        self.change_childs()

    @api.onchange("warehouse_id")
    def onchange_warehouse_id(self):
        if self.warehouse_id:
            # search with sudo because the user may not have permissions
            loc_wh = self.location_id.warehouse_id
            if self.warehouse_id != loc_wh:
                self.location_id = self.warehouse_id.lot_stock_id
                self.with_context(no_change_childs=True).onchange_location_id()
            if self.warehouse_id.company_id != self.company_id:
                self.company_id = self.warehouse_id.company_id
                self.with_context(no_change_childs=True).onchange_company_id()
        self.change_childs()

    @api.onchange("procurement_group_id")
    def onchange_procurement_group_id(self):
        self.change_childs()

    @api.onchange("company_id")
    def onchange_company_id(self):
        if self.company_id and (
            not self.warehouse_id or self.warehouse_id.company_id != self.company_id
        ):
            self.warehouse_id = self.env["stock.warehouse"].search(
                [("company_id", "=", self.company_id.id)], limit=1
            )
            self.with_context(no_change_childs=True).onchange_warehouse_id()
        self.change_childs()

    def change_childs(self):
        if not self._context.get("no_change_childs", False):
            for line in self.stock_request_ids:
                line.warehouse_id = self.warehouse_id
                line.location_id = self.location_id
                line.company_id = self.company_id
                line.picking_policy = self.picking_policy
                line.expected_date = self.expected_date
                line.requested_by = self.requested_by
                line.procurement_group_id = self.procurement_group_id

    def action_confirm(self):
        if not self.stock_request_ids:
            raise UserError(
                _("There should be at least one request item for confirming the order.")
            )
        self.mapped("stock_request_ids").action_confirm()
        return True

    def action_draft(self):
        self.mapped("stock_request_ids").action_draft()
        return True

    def action_cancel(self):
        self.mapped("stock_request_ids").action_cancel()
        return True

    def action_done(self):
        return True

    def action_view_transfer(self):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "stock.action_picking_tree_all"
        )

        pickings = self.mapped("picking_ids")
        if len(pickings) > 1:
            action["domain"] = [("id", "in", pickings.ids)]
        elif pickings:
            action["views"] = [(self.env.ref("stock.view_picking_form").id, "form")]
            action["res_id"] = pickings.id
        return action

    def action_view_stock_requests(self):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "stock_request.action_stock_request_form"
        )
        if len(self.stock_request_ids) > 1:
            action["domain"] = [("order_id", "in", self.ids)]
        elif self.stock_request_ids:
            action["views"] = [
                (self.env.ref("stock_request.view_stock_request_form").id, "form")
            ]
            action["res_id"] = self.stock_request_ids.id
        return action

    @api.model
    def create(self, vals):
        upd_vals = vals.copy()
        if upd_vals.get("name", "/") == "/":
            upd_vals["name"] = self.env["ir.sequence"].next_by_code(
                "stock.request.order"
            )
        return super().create(upd_vals)

    def unlink(self):
        if self.filtered(lambda r: r.state != "draft"):
            raise UserError(_("Only orders on draft state can be unlinked"))
        return super().unlink()

    @api.constrains("warehouse_id", "company_id")
    def _check_warehouse_company(self):
        if any(
            request.warehouse_id.company_id != request.company_id for request in self
        ):
            raise ValidationError(
                _(
                    "The company of the stock request must match with "
                    "that of the warehouse."
                )
            )

    @api.constrains("location_id", "company_id")
    def _check_location_company(self):
        if any(
            request.location_id.company_id
            and request.location_id.company_id != request.company_id
            for request in self
        ):
            raise ValidationError(
                _(
                    "The company of the stock request must match with "
                    "that of the location."
                )
            )

    @api.model
    def _create_from_product_multiselect(self, products):
        if not products:
            return False
        if products._name not in ("product.product", "product.template"):
            raise ValidationError(
                _("This action only works in the context of products")
            )
        if products._name == "product.template":
            # search instead of mapped so we don't include archived variants
            products = self.env["product.product"].search(
                [("product_tmpl_id", "in", products.ids)]
            )
        expected = self.default_get(["expected_date"])["expected_date"]
        order = self.env["stock.request.order"].create(
            dict(
                expected_date=expected,
                stock_request_ids=[
                    (
                        0,
                        0,
                        dict(
                            product_id=product.id,
                            product_uom_id=product.uom_id.id,
                            product_uom_qty=1.0,
                            expected_date=expected,
                        ),
                    )
                    for product in products
                ],
            )
        )
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "stock_request.stock_request_order_action"
        )
        action["views"] = [
            (self.env.ref("stock_request.stock_request_order_form").id, "form")
        ]
        action["res_id"] = order.id
        return action
