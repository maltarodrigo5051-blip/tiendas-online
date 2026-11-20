# GamerStore

Tienda en línea de tecnología y gaming con **pasarela de pago propia**, **control de inventario** y **facturas profesionales**. Hecha con Python (solo biblioteca estándar), SQLite y JavaScript, sin instalar nada.

## Lo fuerte: la pasarela de pago

Funciona con la misma idea que Stripe:

1. La tarjeta va a la pasarela (`/gateway/tokens`), que la valida (algoritmo de Luhn, vencimiento, CVC, marca) y devuelve un **token de un solo uso**.
2. La tienda cobra con ese token. **Nunca guarda el número completo ni el CVC**: solo la marca y los últimos 4 dígitos.
3. Cada cobro corre en **una transacción**: o se cobra y se descuenta el stock, o no pasa nada. Los intentos rechazados quedan registrados.
4. Si el banco lo pide, se abre la **verificación 3-D Secure** con un código.

**Tarjetas de prueba** (cualquier fecha futura y CVC 123):

| Tarjeta | Resultado |
|---|---|
| 4242 4242 4242 4242 | Aprobada (Visa) |
| 5555 5555 5555 4444 | Aprobada (Mastercard) |
| 4000 0027 6000 3184 | Pide código del banco: **123456** |
| 4000 0000 0000 9995 | Rechazada: fondos insuficientes |
| 4000 0000 0000 0002 | Rechazada por el banco |

**Stripe de verdad (opcional):** con una clave de prueba de Stripe aparece la opción "Stripe" y el pago pasa por Stripe Checkout. Al volver, el servidor le pregunta a Stripe si el pago se hizo, sin confiar en el navegador.

```powershell
$env:STRIPE_SECRET_KEY = "sk_test_..."
python -I server.py
```

## Inventario (`/#admin`)

- Ingresos, pedidos pagados, unidades vendidas y valor del inventario.
- Alerta de stock bajo (5 unidades o menos).
- Sumar o sacar stock; cada movimiento queda en el historial con su motivo.
- Agregar productos nuevos.
- Lista de pedidos (pagados, rechazados o esperando al banco) con su factura.

## Factura

`/factura/GS-2026-000001`: factura con datos de la tienda, cliente, productos, IVA del 15 %, envío, forma de pago y referencia de la transacción. Se imprime o se guarda como PDF desde el navegador.

## Cómo correrlo

Requiere Python 3. Doble clic en `iniciar.bat`, o:

```powershell
python -I server.py
```

Abrí http://127.0.0.1:6200. La primera vez crea `gamerstore.db` con 8 productos de ejemplo.

## Pruebas

```powershell
python -m unittest test_store -v
```

13 pruebas: validación de tarjetas, rechazos, tokens de un solo uso, 3-D Secure, IVA y envío, stock que no baja si el pago falla, ajustes de inventario y que la factura no ejecute HTML del cliente.

## Límites conocidos

- Es un proyecto de portafolio: la pasarela propia es una simulación en modo prueba y el servidor solo escucha en `127.0.0.1`.
- El panel de inventario no tiene usuario y contraseña. Antes de ponerlo en internet hay que agregar inicio de sesión y HTTPS.
- Las fotos son de [Unsplash](https://unsplash.com) (licencia libre).
