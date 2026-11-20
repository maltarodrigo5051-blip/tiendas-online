# 🛒 Tiendas en línea con pagos

Tiendas donde el cliente **compra y paga con tarjeta**. Tienen carrito, cobro, inventario y facturas.

Cada carpeta de este repositorio lleva al código completo del proyecto.

| Proyecto | Para qué sirve | Tecnologías | Código |
|---|---|---|---|
| 🛒 **GamerStore** | Tienda de tecnología y gaming con pasarela de pago propia y Stripe | Python, SQLite, JavaScript | [gamerstore](https://github.com/maltarodrigo5051-blip/gamerstore) |

---

## 🛒 GamerStore: tienda gamer con pagos

**Para qué sirve:** vender productos de tecnología y gaming en línea, cobrar con tarjeta y llevar el inventario y las facturas en un solo sistema.

**Cómo funciona el pago (como Stripe):**
1. La tarjeta va a la pasarela, que la valida (número, vencimiento, CVC y marca) y devuelve un **token de un solo uso**.
2. La tienda cobra con ese token. **Nunca guarda el número completo ni el CVC**, solo la marca y los últimos 4 dígitos.
3. Cada cobro es una sola transacción: o se cobra y baja el stock, o no pasa nada.
4. Si el banco lo pide, se abre la verificación **3-D Secure** con un código.

**Además:**
- Puede cobrar con **Stripe de verdad**. Al volver del pago, el servidor le pregunta a Stripe si se pagó, sin confiar en el navegador.
- Tiene control de inventario y genera facturas profesionales.
- Trae tarjetas de prueba para ver pagos aprobados, rechazados y con código del banco.

---

### Ver el código en tu computadora

```bash
git clone --recurse-submodules https://github.com/maltarodrigo5051-blip/tiendas-online.git
```

📂 Otros grupos: [Páginas web](https://github.com/maltarodrigo5051-blip/paginas-web) · [Sistemas](https://github.com/maltarodrigo5051-blip/sistemas)
