"""Pasarela de pago de GamerStore.

Dos procesadores con la misma idea que usan las pasarelas reales:

1. SimGateway: procesador propio en modo prueba. La tarjeta se convierte en un
   token de un solo uso (como Stripe.js); la tienda solo ve el token, la marca y
   los últimos 4 dígitos. Nunca guarda el número completo ni el CVC.
2. Stripe Checkout: si existe la variable STRIPE_SECRET_KEY (clave de prueba
   sk_test_...), se crea una sesión de pago real en Stripe con su API REST.

Tarjetas de prueba (las mismas que usa Stripe en modo prueba):
    4242 4242 4242 4242   Visa, aprobada
    5555 5555 5555 4444   Mastercard, aprobada
    4000 0027 6000 3184   pide verificación 3-D Secure (código 123456)
    4000 0000 0000 9995   rechazada: fondos insuficientes
    4000 0000 0000 0002   rechazada por el banco
"""
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

TOKEN_TTL_S = 600
THREE_DS_CODE = "123456"  # en modo prueba el "banco" siempre manda este código

DECLINES = {
    "4000000000009995": ("insufficient_funds", "Fondos insuficientes. Probá con otra tarjeta."),
    "4000000000000002": ("card_declined", "El banco rechazó la tarjeta."),
}
REQUIRES_3DS = {"4000002760003184"}


class PaymentError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def luhn_ok(number):
    digits = [int(d) for d in number]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card_brand(number):
    if number.startswith("4"):
        return "visa"
    if number[:2] in {"51", "52", "53", "54", "55"} or 2221 <= int(number[:4] or 0) <= 2720:
        return "mastercard"
    if number[:2] in {"34", "37"}:
        return "amex"
    return "card"


class SimGateway:
    """Procesador de pagos simulado, con tokens de un solo uso."""

    name = "gamerstore_pay"

    def __init__(self):
        self._tokens = {}
        self._lock = threading.Lock()

    def tokenize(self, number, exp_month, exp_year, cvc, holder):
        number = "".join(ch for ch in str(number) if ch.isdigit())
        holder = (holder or "").strip()
        if not 13 <= len(number) <= 19 or not luhn_ok(number):
            raise PaymentError("invalid_number", "El número de tarjeta no es válido.")
        try:
            month, year = int(exp_month), int(exp_year)
        except (TypeError, ValueError):
            raise PaymentError("invalid_expiry", "La fecha de vencimiento no es válida.")
        if year < 100:
            year += 2000
        today = date.today()
        if not 1 <= month <= 12 or (year, month) < (today.year, today.month):
            raise PaymentError("expired_card", "La tarjeta está vencida.")
        brand = card_brand(number)
        cvc = str(cvc or "")
        if not cvc.isdigit() or len(cvc) != (4 if brand == "amex" else 3):
            raise PaymentError("invalid_cvc", "El código de seguridad no es válido.")
        if len(holder) < 3:
            raise PaymentError("invalid_name", "Escribí el nombre como aparece en la tarjeta.")
        token = "tok_" + secrets.token_hex(12)
        with self._lock:
            self._purge()
            # el número completo vive solo aquí, en memoria, y se borra al usar el token
            self._tokens[token] = {"number": number, "brand": brand, "last4": number[-4:],
                                   "holder": holder, "created": time.time()}
        return {"token": token, "brand": brand, "last4": number[-4:]}

    def _purge(self):
        now = time.time()
        for t in [t for t, v in self._tokens.items() if now - v["created"] > TOKEN_TTL_S]:
            del self._tokens[t]

    def charge(self, token, amount_cents):
        """Cobra un token. Devuelve dict con status 'succeeded' o 'requires_action'."""
        if amount_cents <= 0:
            raise PaymentError("invalid_amount", "El monto debe ser mayor que cero.")
        with self._lock:
            self._purge()
            card = self._tokens.pop(token, None)  # un solo uso
        if not card:
            raise PaymentError("invalid_token", "El pago expiró. Volvé a ingresar la tarjeta.")
        number = card.pop("number")
        info = {"brand": card["brand"], "last4": card["last4"], "holder": card["holder"]}
        if number in DECLINES:
            code, msg = DECLINES[number]
            raise PaymentError(code, msg)
        if number in REQUIRES_3DS:
            return {"status": "requires_action", "ref": "pi_" + secrets.token_hex(10), **info}
        return {"status": "succeeded", "ref": "ch_" + secrets.token_hex(10), **info}

    @staticmethod
    def verify_3ds(code):
        if str(code).strip() != THREE_DS_CODE:
            raise PaymentError("authentication_failed", "El código de verificación no es correcto.")


class StripeCheckout:
    """Stripe Checkout por API REST (sin librerías). Solo se activa con una clave de prueba."""

    name = "stripe"
    API = "https://api.stripe.com/v1"

    def __init__(self, secret_key):
        if not secret_key.startswith("sk_test_"):
            # shortcut: solo modo prueba; para producción hace falta webhook firmado y revisión de seguridad
            raise ValueError("Usá una clave de prueba de Stripe (sk_test_...).")
        self.key = secret_key

    @classmethod
    def from_env(cls):
        key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        return cls(key) if key else None

    def _request(self, method, path, params=None):
        data = urllib.parse.urlencode(params or {}).encode() if method == "POST" else None
        req = urllib.request.Request(self.API + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.key}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = json.loads(e.read() or b"{}").get("error", {}).get("message", "Stripe rechazó la petición")
            raise PaymentError("stripe_error", msg)
        except urllib.error.URLError:
            raise PaymentError("stripe_unreachable", "No se pudo conectar con Stripe.")

    def create_session(self, order, lines, base_url):
        params = {
            "mode": "payment",
            "success_url": f"{base_url}/?stripe_session={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base_url}/?stripe_cancel={order['number']}",
            "customer_email": order["email"],
            "metadata[order_number]": order["number"],
        }
        for i, (name, qty, unit_cents) in enumerate(lines):
            params[f"line_items[{i}][quantity]"] = qty
            params[f"line_items[{i}][price_data][currency]"] = "usd"
            params[f"line_items[{i}][price_data][unit_amount]"] = unit_cents
            params[f"line_items[{i}][price_data][product_data][name]"] = name
        session = self._request("POST", "/checkout/sessions", params)
        return {"id": session["id"], "url": session["url"]}

    def retrieve_session(self, session_id):
        if not session_id.startswith("cs_"):
            raise PaymentError("invalid_session", "Sesión de pago inválida.")
        return self._request("GET", "/checkout/sessions/" + urllib.parse.quote(session_id))
