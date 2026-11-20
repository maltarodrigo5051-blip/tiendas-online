"""GamerStore: tienda de tecnología con inventario, pasarela de pago y facturas.

Uso:  python -I server.py   ->  http://127.0.0.1:6200          (tienda)
                                 http://127.0.0.1:6200/#admin    (inventario y pedidos)
Stripe (opcional):  $env:STRIPE_SECRET_KEY = "sk_test_..."  antes de arrancar.
"""
import html
import json
import re
import sqlite3
import sys
import urllib.parse
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # con python -I no se agrega la carpeta del script; gateway.py vive aquí
import gateway  # noqa: E402
DB_PATH = ROOT / "gamerstore.db"
TAX_RATE = 0.15                 # IVA de Nicaragua
FREE_SHIPPING_FROM = 10000      # US$100
SHIPPING_CENTS = 500            # US$5
LOW_STOCK = 5
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
STORE = {"name": "GamerStore", "legal": "GamerStore Tecnología S.A.", "ruc": "J0310000123456",
         "address": "Chinandega, Nicaragua", "email": "ventas@gamerstore.example", "phone": "+505 0000 0000"}

U = "https://images.unsplash.com/photo-"
SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    tagline TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    image TEXT NOT NULL DEFAULT '',
    glow TEXT NOT NULL DEFAULT '#22d3ee'
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    created_at TEXT NOT NULL,
    paid_at TEXT,
    status TEXT NOT NULL,          -- pending | requires_action | paid | failed
    customer_name TEXT NOT NULL,
    email TEXT NOT NULL,
    address TEXT NOT NULL,
    subtotal_cents INTEGER NOT NULL,
    tax_cents INTEGER NOT NULL,
    shipping_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    provider TEXT NOT NULL,
    payment_ref TEXT,
    card_brand TEXT,
    card_last4 TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS order_items (
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    product_id INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    ref TEXT
);
"""

DEMO = [
    ("GS-HS-01", "Auriculares Pulse X7", "Audio", "Sonido envolvente 7.1 y micrófono con cancelación de ruido", 8900, 14, U + "1677086813101-496781a0f327", "#22d3ee"),
    ("GS-KB-01", "Teclado mecánico Forge TKL", "Teclados", "Switches rojos lineales, RGB por tecla y cuerpo de aluminio", 12900, 9, U + "1618384887929-16ec33fab9ef", "#fb923c"),
    ("GS-KB-02", "Teclado Aurora 75%", "Teclados", "Hot-swap, teclas PBT y perilla de volumen", 10900, 4, U + "1760708551859-6559dc9640b8", "#2dd4bf"),
    ("GS-MS-01", "Mouse Vector Pro", "Mouse", "Sensor de 26 000 DPI, 58 g e inalámbrico", 6900, 22, U + "1771444700533-ff7aa34d29fe", "#60a5fa"),
    ("GS-GP-01", "Control Nova inalámbrico", "Controles", "Gatillos hápticos, batería de 40 horas", 5900, 18, U + "1612287230202-1ff1d85d1bdf", "#e879f9"),
    ("GS-MN-01", "Monitor Horizon 27\" 165 Hz", "Monitores", "Panel IPS QHD con 1 ms de respuesta", 32900, 6, U + "1626218174358-7769486c4b79", "#a78bfa"),
    ("GS-MC-01", "Micrófono Echo USB", "Streaming", "Condensador cardioide con brazo y filtro antipop", 7900, 3, U + "1590602847861-f357a9332bbc", "#f472b6"),
    ("GS-CH-01", "Silla gamer Titan", "Sillas", "Respaldo reclinable 160° y soporte lumbar", 24900, 5, U + "1770194993269-2521ad916c23", "#f87171"),
]


class ShopError(Exception):
    """Error que se muestra al usuario tal cual."""


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect(path=DB_PATH):
    con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)  # transacciones manuales
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        con.execute("BEGIN")
        for row in DEMO:
            cur = con.execute("INSERT INTO products (sku, name, category, tagline, price_cents, stock, image, glow) "
                              "VALUES (?,?,?,?,?,?,?,?)", row)
            con.execute("INSERT INTO movements (created_at, product_id, delta, reason) VALUES (?,?,?,?)",
                        (now(), cur.lastrowid, row[5], "Inventario inicial"))
        con.execute("COMMIT")
    return con


def rows(cur):
    return [dict(r) for r in cur]


def list_products(con):
    return rows(con.execute("SELECT * FROM products ORDER BY id"))


def totals(subtotal):
    tax = (subtotal * 15 + 50) // 100  # 15 % redondeado al centavo, sin floats
    shipping = 0 if subtotal >= FREE_SHIPPING_FROM else SHIPPING_CENTS
    return {"subtotal_cents": subtotal, "tax_cents": tax, "shipping_cents": shipping,
            "total_cents": subtotal + tax + shipping}


def build_lines(con, items):
    """Valida el carrito contra la base. Devuelve [(producto, qty)]."""
    if not isinstance(items, list) or not items:
        raise ShopError("El carrito está vacío.")
    qty_by_id = {}
    for it in items:
        pid, qty = it.get("id") if isinstance(it, dict) else None, it.get("qty") if isinstance(it, dict) else None
        if not isinstance(pid, int) or not isinstance(qty, int) or not 1 <= qty <= 20:
            raise ShopError("Cantidad inválida en el carrito.")
        qty_by_id[pid] = qty_by_id.get(pid, 0) + qty
    lines = []
    for pid, qty in qty_by_id.items():
        p = con.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        if not p:
            raise ShopError("Un producto del carrito ya no existe.")
        if p["stock"] < qty:
            raise ShopError(f"Solo quedan {p['stock']} de {p['name']}.")
        lines.append((dict(p), qty))
    return lines


def validate_customer(c):
    if not isinstance(c, dict):
        raise ShopError("Faltan tus datos.")
    name, email, address = (str(c.get(k) or "").strip() for k in ("name", "email", "address"))
    if not 3 <= len(name) <= 80:
        raise ShopError("Escribí tu nombre completo.")
    if not EMAIL_RE.match(email):
        raise ShopError("El correo no es válido.")
    if not 8 <= len(address) <= 200:
        raise ShopError("Escribí una dirección de entrega más completa.")
    return name, email, address


def create_order(con, lines, customer, provider):
    name, email, address = customer
    t = totals(sum(p["price_cents"] * q for p, q in lines))
    cur = con.execute(
        "INSERT INTO orders (created_at, status, customer_name, email, address, subtotal_cents, tax_cents, "
        "shipping_cents, total_cents, provider) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now(), "pending", name, email, address, t["subtotal_cents"], t["tax_cents"], t["shipping_cents"],
         t["total_cents"], provider))
    oid = cur.lastrowid
    number = f"GS-{datetime.now():%Y}-{oid:06d}"
    con.execute("UPDATE orders SET number = ? WHERE id = ?", (number, oid))
    for p, q in lines:
        con.execute("INSERT INTO order_items VALUES (?,?,?,?,?,?)", (oid, p["id"], p["sku"], p["name"], q, p["price_cents"]))
    return get_order(con, number)


def get_order(con, number):
    o = con.execute("SELECT * FROM orders WHERE number = ?", (number,)).fetchone()
    if not o:
        return None
    o = dict(o)
    o["items"] = rows(con.execute("SELECT sku, name, qty, unit_cents, product_id FROM order_items WHERE order_id = ?", (o["id"],)))
    return o


def fulfil(con, order, ref, brand=None, last4=None):
    """Marca el pedido como pagado y descuenta stock. Debe correr dentro de una transacción."""
    for it in order["items"]:
        cur = con.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                          (it["qty"], it["product_id"], it["qty"]))
        if cur.rowcount != 1:
            raise ShopError(f"Se acabó el stock de {it['name']} mientras pagabas.")
        con.execute("INSERT INTO movements (created_at, product_id, delta, reason, ref) VALUES (?,?,?,?,?)",
                    (now(), it["product_id"], -it["qty"], "Venta", order["number"]))
    con.execute("UPDATE orders SET status='paid', paid_at=?, payment_ref=?, card_brand=COALESCE(?, card_brand), "
                "card_last4=COALESCE(?, card_last4) WHERE id=?", (now(), ref, brand, last4, order["id"]))


def checkout_card(con, gw, items, customer, token):
    """Cobra con la pasarela propia. Todo en una transacción: o se cobra y descuenta, o nada."""
    customer = validate_customer(customer)
    if not isinstance(token, str) or not token.startswith("tok_"):
        raise ShopError("Falta la tarjeta.")
    con.execute("BEGIN IMMEDIATE")
    try:
        lines = build_lines(con, items)
        order = create_order(con, lines, customer, gw.name)
        try:
            result = gw.charge(token, order["total_cents"])
        except gateway.PaymentError as e:
            con.execute("UPDATE orders SET status='failed', note=? WHERE id=?", (str(e), order["id"]))
            con.execute("COMMIT")  # el intento fallido queda registrado
            raise
        con.execute("UPDATE orders SET card_brand=?, card_last4=?, payment_ref=? WHERE id=?",
                    (result["brand"], result["last4"], result["ref"], order["id"]))
        if result["status"] == "requires_action":
            con.execute("UPDATE orders SET status='requires_action' WHERE id=?", (order["id"],))
            con.execute("COMMIT")
            return {"status": "requires_action", "number": order["number"], "brand": result["brand"], "last4": result["last4"]}
        fulfil(con, get_order(con, order["number"]), result["ref"], result["brand"], result["last4"])
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    return {"status": "paid", "number": order["number"]}


def confirm_3ds(con, gw, number, code):
    con.execute("BEGIN IMMEDIATE")
    try:
        order = get_order(con, str(number))
        if not order or order["status"] != "requires_action":
            raise ShopError("Este pago ya no está esperando verificación.")
        try:
            gw.verify_3ds(code)
        except gateway.PaymentError as e:
            con.execute("UPDATE orders SET status='failed', note=? WHERE id=?", (str(e), order["id"]))
            con.execute("COMMIT")
            raise
        fulfil(con, order, order["payment_ref"])
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    return {"status": "paid", "number": order["number"]}


def checkout_stripe(con, stripe, items, customer, base_url):
    customer = validate_customer(customer)
    con.execute("BEGIN IMMEDIATE")
    try:
        lines = build_lines(con, items)
        order = create_order(con, lines, customer, "stripe")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    stripe_lines = [(p["name"], q, p["price_cents"]) for p, q in lines]
    t = order
    stripe_lines.append(("IVA 15%", 1, t["tax_cents"]))
    if t["shipping_cents"]:
        stripe_lines.append(("Envío", 1, t["shipping_cents"]))
    session = stripe.create_session(order, stripe_lines, base_url)
    con.execute("UPDATE orders SET payment_ref=? WHERE id=?", (session["id"], order["id"]))
    return {"status": "redirect", "url": session["url"], "number": order["number"]}


def confirm_stripe(con, stripe, session_id):
    session = stripe.retrieve_session(session_id)  # se consulta a Stripe: no se confía en el navegador
    number = (session.get("metadata") or {}).get("order_number")
    con.execute("BEGIN IMMEDIATE")
    try:
        order = get_order(con, number or "")
        if not order or order["payment_ref"] != session_id:
            raise ShopError("No se encontró el pedido de este pago.")
        if order["status"] == "paid":  # el usuario recargó la página: no descontar dos veces
            con.execute("COMMIT")
            return {"status": "paid", "number": number}
        if session.get("payment_status") != "paid":
            raise ShopError("Stripe todavía no confirma el pago.")
        pm = session.get("payment_method_types") or ["card"]
        fulfil(con, order, session.get("payment_intent") or session_id, pm[0], None)
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    return {"status": "paid", "number": number}


# ---------- Inventario ----------
def adjust_stock(con, pid, delta, reason):
    if not isinstance(pid, int) or not isinstance(delta, int) or delta == 0 or abs(delta) > 10000:
        raise ShopError("Ajuste inválido.")
    reason = str(reason or "").strip()
    if not 3 <= len(reason) <= 80:
        raise ShopError("Escribí el motivo del ajuste.")
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute("UPDATE products SET stock = stock + ? WHERE id = ? AND stock + ? >= 0", (delta, pid, delta))
        if cur.rowcount != 1:
            raise ShopError("No hay suficiente stock para ese ajuste.")
        con.execute("INSERT INTO movements (created_at, product_id, delta, reason) VALUES (?,?,?,?)", (now(), pid, delta, reason))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return dict(con.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone())


def add_product(con, d):
    sku, name, category, tagline = (str(d.get(k) or "").strip() for k in ("sku", "name", "category", "tagline"))
    price, stock, image = d.get("price_cents"), d.get("stock"), str(d.get("image") or "").strip()
    if not re.match(r"^[A-Z0-9\-]{3,20}$", sku):
        raise ShopError("El SKU debe tener de 3 a 20 letras mayúsculas, números o guiones.")
    if not 2 <= len(name) <= 80 or not 2 <= len(category) <= 30:
        raise ShopError("Revisá el nombre y la categoría.")
    if not isinstance(price, int) or price <= 0 or not isinstance(stock, int) or stock < 0:
        raise ShopError("Revisá el precio y el stock.")
    if image and not image.startswith("https://"):
        raise ShopError("La imagen debe ser una dirección https.")
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute("INSERT INTO products (sku, name, category, tagline, price_cents, stock, image) VALUES (?,?,?,?,?,?,?)",
                          (sku, name, category, tagline[:120], price, stock, image))
        if stock:
            con.execute("INSERT INTO movements (created_at, product_id, delta, reason) VALUES (?,?,?,?)",
                        (now(), cur.lastrowid, stock, "Inventario inicial"))
        con.execute("COMMIT")
    except sqlite3.IntegrityError:
        con.execute("ROLLBACK")
        raise ShopError("Ya existe un producto con ese SKU.")
    return dict(con.execute("SELECT * FROM products WHERE id = ?", (cur.lastrowid,)).fetchone())


def admin_summary(con):
    paid = con.execute("SELECT COUNT(*) n, COALESCE(SUM(total_cents),0) total FROM orders WHERE status='paid'").fetchone()
    units = con.execute("SELECT COALESCE(SUM(i.qty),0) FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.status='paid'").fetchone()[0]
    stock_value = con.execute("SELECT COALESCE(SUM(price_cents*stock),0) FROM products").fetchone()[0]
    low = rows(con.execute("SELECT id, name, stock FROM products WHERE stock <= ? ORDER BY stock", (LOW_STOCK,)))
    return {"orders": paid["n"], "revenue_cents": paid["total"], "units": units, "stock_value_cents": stock_value, "low_stock": low}


def list_orders(con):
    return rows(con.execute("SELECT number, created_at, status, customer_name, total_cents, provider, card_brand, card_last4, note "
                            "FROM orders WHERE number IS NOT NULL ORDER BY id DESC LIMIT 100"))


def list_movements(con):
    return rows(con.execute("SELECT m.created_at, m.delta, m.reason, m.ref, p.name FROM movements m "
                            "JOIN products p ON p.id = m.product_id ORDER BY m.id DESC LIMIT 60"))


# ---------- Factura ----------
def money(cents):
    return f"US$ {cents / 100:,.2f}"


def invoice_html(order):
    e = html.escape
    paid_at = datetime.fromisoformat(order["paid_at"] or order["created_at"])
    inv_no = "FAC-" + order["number"].split("-")[-1]
    method = {"visa": "Visa", "mastercard": "Mastercard", "amex": "American Express"}.get(order["card_brand"] or "", "Tarjeta")
    method += f" terminada en {order['card_last4']}" if order["card_last4"] else ""
    method += " · Stripe" if order["provider"] == "stripe" else " · GamerStore Pay"
    rows_html = "".join(
        f"<tr><td><span class='sku'>{e(i['sku'])}</span>{e(i['name'])}</td><td class='n'>{i['qty']}</td>"
        f"<td class='n'>{money(i['unit_cents'])}</td><td class='n'>{money(i['unit_cents'] * i['qty'])}</td></tr>"
        for i in order["items"])
    tpl = (ROOT / "public" / "factura.html").read_text(encoding="utf-8")
    values = {
        "INV": e(inv_no), "ORDER": e(order["number"]), "DATE": paid_at.strftime("%d/%m/%Y"), "TIME": paid_at.strftime("%I:%M %p"),
        "CUSTOMER": e(order["customer_name"]), "EMAIL": e(order["email"]), "ADDRESS": e(order["address"]),
        "ROWS": rows_html, "SUBTOTAL": money(order["subtotal_cents"]), "TAX": money(order["tax_cents"]),
        "SHIPPING": "Gratis" if not order["shipping_cents"] else money(order["shipping_cents"]),
        "TOTAL": money(order["total_cents"]), "METHOD": e(method), "REF": e(order["payment_ref"] or ""),
        "STORE": e(STORE["name"]), "LEGAL": e(STORE["legal"]), "RUC": e(STORE["ruc"]), "STORE_ADDR": e(STORE["address"]),
        "STORE_EMAIL": e(STORE["email"]), "STORE_PHONE": e(STORE["phone"]),
    }
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], tpl)


# ---------- HTTP ----------
class Handler(SimpleHTTPRequestHandler):
    con = None
    gw = None
    stripe = None
    port = 6200

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "public"), **kw)

    def log_message(self, fmt, *args):
        if "/api/" not in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, q = url.path, urllib.parse.parse_qs(url.query)
        try:
            if path == "/api/products":
                return self.send_json(200, list_products(self.con))
            if path == "/api/config":
                return self.send_json(200, {"stripe": bool(self.stripe), "tax_rate": TAX_RATE,
                                            "free_shipping_from": FREE_SHIPPING_FROM, "shipping_cents": SHIPPING_CENTS})
            if path == "/api/stripe/confirm":
                if not self.stripe:
                    raise ShopError("Stripe no está activado.")
                return self.send_json(200, confirm_stripe(self.con, self.stripe, q.get("session_id", [""])[0]))
            if path == "/api/admin/summary":
                return self.send_json(200, admin_summary(self.con))
            if path == "/api/admin/orders":
                return self.send_json(200, list_orders(self.con))
            if path == "/api/admin/movements":
                return self.send_json(200, list_movements(self.con))
            if path.startswith("/factura/"):
                number = urllib.parse.unquote(path.split("/", 2)[2])
                order = get_order(self.con, number) if re.match(r"^GS-\d{4}-\d{6}$", number) else None
                if not order or order["status"] != "paid":
                    return self.send_text(404, "Factura no encontrada")
                return self.send_text(200, invoice_html(order), "text/html")
        except (ShopError, gateway.PaymentError) as e:
            return self.send_json(400, {"error": str(e)})
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 50_000:
                return self.send_json(413, {"error": "Petición muy grande"})
            d = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(d, dict):
                raise ValueError
            if path == "/gateway/tokens":  # servicio de la pasarela: el único que ve el número completo
                return self.send_json(200, self.gw.tokenize(d.get("number"), d.get("exp_month"), d.get("exp_year"),
                                                            d.get("cvc"), d.get("name")))
            if path == "/api/checkout":
                if d.get("method") == "stripe":
                    if not self.stripe:
                        raise ShopError("Stripe no está activado en esta tienda.")
                    base = f"http://127.0.0.1:{self.port}"
                    return self.send_json(200, checkout_stripe(self.con, self.stripe, d.get("items"), d.get("customer"), base))
                return self.send_json(200, checkout_card(self.con, self.gw, d.get("items"), d.get("customer"), d.get("token")))
            if path == "/api/checkout/confirm":
                return self.send_json(200, confirm_3ds(self.con, self.gw, d.get("number"), d.get("code")))
            if path == "/api/admin/stock":
                return self.send_json(200, adjust_stock(self.con, d.get("id"), d.get("delta"), d.get("reason")))
            if path == "/api/admin/products":
                return self.send_json(200, add_product(self.con, d))
            return self.send_json(404, {"error": "Ruta no existe"})
        except gateway.PaymentError as e:
            return self.send_json(402, {"error": str(e), "code": e.code})
        except ShopError as e:
            return self.send_json(400, {"error": str(e)})
        except (ValueError, TypeError, AttributeError):
            return self.send_json(400, {"error": "Datos mal formados"})

    def send_json(self, code, obj):
        self.send_text(code, json.dumps(obj, ensure_ascii=False), "application/json")

    def send_text(self, code, text, ctype="text/plain"):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6200
    Handler.con = connect()
    Handler.gw = gateway.SimGateway()
    Handler.stripe = gateway.StripeCheckout.from_env()
    Handler.port = port
    print(f"GamerStore en http://127.0.0.1:{port}  (Stripe: {'activado' if Handler.stripe else 'no'})")
    # un solo hilo: la conexión SQLite no se comparte entre hilos
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
