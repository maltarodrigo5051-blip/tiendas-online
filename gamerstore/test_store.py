"""Pruebas de la pasarela, el checkout y el inventario.  Uso:  python -m unittest test_store -v"""
import unittest

import gateway
import server

CUSTOMER = {"name": "Rodrigo Poveda", "email": "cliente@example.com", "address": "Barrio Central, Chinandega"}


def card(number, cvc="123", exp=("12", "2030")):
    return dict(number=number, exp_month=exp[0], exp_year=exp[1], cvc=cvc, holder="RODRIGO POVEDA")


class PasarelaTest(unittest.TestCase):
    def setUp(self):
        self.gw = gateway.SimGateway()

    def tok(self, number, **kw):
        return self.gw.tokenize(**card(number, **kw))

    def test_luhn_y_marca(self):
        self.assertTrue(gateway.luhn_ok("4242424242424242"))
        self.assertFalse(gateway.luhn_ok("4242424242424241"))
        self.assertEqual(gateway.card_brand("5555555555554444"), "mastercard")
        self.assertEqual(gateway.card_brand("4242424242424242"), "visa")

    def test_token_no_expone_el_numero(self):
        t = self.tok("4242 4242 4242 4242")
        self.assertEqual((t["brand"], t["last4"]), ("visa", "4242"))
        self.assertNotIn("number", t)

    def test_rechazos_al_tokenizar(self):
        for kwargs, code in [({"number": "4242424242424241"}, "invalid_number"),
                             ({"number": "4242424242424242", "exp": ("01", "2020")}, "expired_card"),
                             ({"number": "4242424242424242", "cvc": "12"}, "invalid_cvc")]:
            with self.assertRaises(gateway.PaymentError) as ctx:
                self.tok(**kwargs)
            self.assertEqual(ctx.exception.code, code)

    def test_cobros(self):
        self.assertEqual(self.gw.charge(self.tok("4242424242424242")["token"], 1000)["status"], "succeeded")
        self.assertEqual(self.gw.charge(self.tok("4000002760003184")["token"], 1000)["status"], "requires_action")
        with self.assertRaises(gateway.PaymentError) as ctx:
            self.gw.charge(self.tok("4000000000009995")["token"], 1000)
        self.assertEqual(ctx.exception.code, "insufficient_funds")

    def test_token_de_un_solo_uso(self):
        t = self.tok("4242424242424242")["token"]
        self.gw.charge(t, 1000)
        with self.assertRaises(gateway.PaymentError):
            self.gw.charge(t, 1000)


class TiendaTest(unittest.TestCase):
    def setUp(self):
        self.con = server.connect(":memory:")
        self.gw = gateway.SimGateway()
        self.p = server.list_products(self.con)[0]  # Auriculares Pulse X7, US$89, stock 14

    def stock(self):
        return self.con.execute("SELECT stock FROM products WHERE id=?", (self.p["id"],)).fetchone()[0]

    def buy(self, number, qty=2):
        token = self.gw.tokenize(**card(number))["token"]
        return server.checkout_card(self.con, self.gw, [{"id": self.p["id"], "qty": qty}], CUSTOMER, token)

    def test_totales_con_iva_y_envio(self):
        self.assertEqual(server.totals(8900), {"subtotal_cents": 8900, "tax_cents": 1335, "shipping_cents": 500, "total_cents": 10735})
        self.assertEqual(server.totals(17800)["shipping_cents"], 0)  # desde US$100 el envío es gratis

    def test_compra_aprobada_descuenta_stock_y_genera_factura(self):
        r = self.buy("4242424242424242")
        self.assertEqual(r["status"], "paid")
        self.assertEqual(self.stock(), 12)
        order = server.get_order(self.con, r["number"])
        self.assertEqual((order["card_brand"], order["card_last4"]), ("visa", "4242"))
        self.assertEqual(order["total_cents"], 17800 + 2670)
        html = server.invoice_html(order)
        self.assertIn("FAC-", html)
        self.assertIn("Rodrigo Poveda", html)

    def test_rechazo_no_toca_stock(self):
        with self.assertRaises(gateway.PaymentError):
            self.buy("4000000000009995")
        self.assertEqual(self.stock(), 14)
        status = self.con.execute("SELECT status FROM orders ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(status, "failed")

    def test_3ds(self):
        r = self.buy("4000002760003184")
        self.assertEqual(r["status"], "requires_action")
        self.assertEqual(self.stock(), 14)  # todavía no se cobra
        with self.assertRaises(gateway.PaymentError):
            server.confirm_3ds(self.con, self.gw, r["number"], "000000")
        r2 = self.buy("4000002760003184")
        server.confirm_3ds(self.con, self.gw, r2["number"], "123456")
        self.assertEqual(self.stock(), 12)
        with self.assertRaises(server.ShopError):  # no se puede confirmar dos veces
            server.confirm_3ds(self.con, self.gw, r2["number"], "123456")

    def test_sin_stock_suficiente(self):
        with self.assertRaises(server.ShopError):
            self.buy("4242424242424242", qty=15)
        self.assertEqual(self.stock(), 14)

    def test_datos_del_cliente(self):
        token = self.gw.tokenize(**card("4242424242424242"))["token"]
        bad = dict(CUSTOMER, email="no-es-correo")
        with self.assertRaises(server.ShopError):
            server.checkout_card(self.con, self.gw, [{"id": self.p["id"], "qty": 1}], bad, token)

    def test_ajuste_de_inventario(self):
        server.adjust_stock(self.con, self.p["id"], 6, "Compra a proveedor")
        self.assertEqual(self.stock(), 20)
        with self.assertRaises(server.ShopError):
            server.adjust_stock(self.con, self.p["id"], -50, "Merma")
        self.assertEqual(server.list_movements(self.con)[0]["reason"], "Compra a proveedor")

    def test_factura_escapa_html(self):
        token = self.gw.tokenize(**card("4242424242424242"))["token"]
        evil = dict(CUSTOMER, name="<script>alert(1)</script>")
        r = server.checkout_card(self.con, self.gw, [{"id": self.p["id"], "qty": 1}], evil, token)
        self.assertNotIn("<script>alert", server.invoice_html(server.get_order(self.con, r["number"])))


if __name__ == "__main__":
    unittest.main()
