// GamerStore: la tienda (catálogo, carrito, checkout) y el panel de inventario.
const $ = (id) => document.getElementById(id);
const money = (c) => "US$ " + (c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
let products = [];
let config = { stripe: false, free_shipping_from: 10000, shipping_cents: 500 };
let filter = "Todos";
const cart = new Map(); // id -> qty

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) k.includes("-") ? n.setAttribute(k, v) : (n[k] = v); // aria-* van como atributo
  n.append(...kids);
  return n;
}
function svg(path, extra = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.innerHTML = `<path d="${path}"/>${extra}`;
  return s;
}
function replay(node, cls) { node.classList.remove(cls); void node.offsetWidth; node.classList.add(cls); }

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || "El servidor no respondió."), { status: res.status, code: data.code });
  return data;
}

function toast(text, kind = "") {
  const t = el("div", { className: "toast " + kind }, el("i"), el("span", { textContent: text }));
  $("toasts").append(t);
  setTimeout(() => { t.classList.add("out"); t.addEventListener("animationend", () => t.remove()); }, 2800);
}

// Mismo cálculo que el servidor (el servidor decide el monto real al cobrar).
function totals(sub) {
  const tax = Math.floor((sub * 15 + 50) / 100);
  const shipping = sub === 0 || sub >= config.free_shipping_from ? 0 : config.shipping_cents;
  return { sub, tax, shipping, total: sub + tax + shipping };
}

// ---------- Carrito (se recuerda en este navegador) ----------
function saveCart() { try { localStorage.setItem("gamerstore-cart", JSON.stringify([...cart])); } catch { /* sin almacenamiento */ } }
function loadCart() {
  try { for (const [id, q] of JSON.parse(localStorage.getItem("gamerstore-cart") || "[]")) cart.set(id, q); } catch { /* carrito vacío */ }
}
const byId = (id) => products.find((p) => p.id === id);
function cartLines() {
  return [...cart].map(([id, qty]) => ({ p: byId(id), qty })).filter((l) => l.p);
}
function cartSubtotal() { return cartLines().reduce((s, l) => s + l.p.price_cents * l.qty, 0); }

function addToCart(p, fromImg) {
  const qty = (cart.get(p.id) || 0) + 1;
  if (qty > p.stock) return toast(p.stock ? `Solo hay ${p.stock} disponibles de ${p.name}` : `${p.name} está agotado`, "bad");
  cart.set(p.id, qty);
  saveCart();
  flyTo(fromImg, $("open-cart"));
  setTimeout(() => { renderCartBadge(true); replay($("open-cart"), "shake"); }, calm() ? 0 : 620);
  toast(`${p.name} agregado al carrito`, "ok");
  renderCart();
}

function setQty(id, qty) {
  const p = byId(id);
  if (qty <= 0) cart.delete(id);
  else if (qty > p.stock) return toast(`Solo hay ${p.stock} disponibles`, "bad");
  else cart.set(id, qty);
  saveCart();
  renderCartBadge(true);
  renderCart();
}

function renderCartBadge(pop) {
  const n = [...cart.values()].reduce((a, b) => a + b, 0);
  $("cart-count").textContent = n;
  if (pop) replay($("cart-count"), "pop");
}

function sumsDl(t) {
  const row = (k, v, cls = "") => el("div", { className: cls }, el("dt", { textContent: k }), el("dd", { textContent: v }));
  return [row("Subtotal", money(t.sub)), row("IVA (15%)", money(t.tax)), row("Envío", t.shipping ? money(t.shipping) : "Gratis"), row("Total", money(t.total), "total")];
}

function renderCart() {
  const lines = cartLines();
  const list = $("cart-items");
  list.replaceChildren(...lines.map(({ p, qty }) => el("li", { className: "citem" },
    el("img", { src: img(p.image, 160), alt: "" }),
    el("div", {}, el("h4", { textContent: p.name }), el("div", { className: "unit", textContent: money(p.price_cents) }),
      el("div", { className: "qty" },
        el("button", { textContent: "−", "aria-label": "Quitar uno", onclick: () => setQty(p.id, qty - 1) }),
        el("output", { textContent: qty }),
        el("button", { textContent: "+", "aria-label": "Agregar uno", onclick: () => setQty(p.id, qty + 1) }))),
    el("div", {}, el("div", { className: "line-total", textContent: money(p.price_cents * qty) }),
      el("button", { className: "rm", textContent: "Quitar", onclick: () => setQty(p.id, 0) })))));
  const sub = cartSubtotal();
  const t = totals(sub);
  $("cart-empty").hidden = lines.length > 0;
  $("cart-sums").replaceChildren(...sumsDl(t));
  $("go-checkout").disabled = !lines.length;
  const left = config.free_shipping_from - sub;
  $("ship").hidden = !lines.length;
  $("ship-text").innerHTML = left > 0 ? `Te faltan <b>${money(left)}</b> para el envío gratis` : "<b>¡Tenés envío gratis!</b>";
  $("ship-fill").style.width = Math.min(100, (sub / config.free_shipping_from) * 100) + "%";
}

function openCart() {
  $("scrim").hidden = false;
  $("drawer").classList.add("open");
  $("drawer").setAttribute("aria-hidden", "false");
  document.body.classList.add("lock");
  renderCart();
}
function closeCart() {
  $("scrim").hidden = true;
  $("drawer").classList.remove("open");
  $("drawer").setAttribute("aria-hidden", "true");
  document.body.classList.remove("lock");
}

// La foto del producto vuela hacia el botón del carrito.
function flyTo(fromImg, target) {
  if (calm() || !fromImg) return;
  const a = fromImg.getBoundingClientRect(), b = target.getBoundingClientRect();
  const f = el("img", { className: "flyer", src: fromImg.currentSrc || fromImg.src, alt: "" });
  const size = Math.min(a.width, 120);
  Object.assign(f.style, { left: a.left + a.width / 2 - size / 2 + "px", top: a.top + a.height / 2 - size / 2 + "px", width: size + "px", height: size + "px" });
  document.body.append(f);
  const dx = b.left + b.width / 2 - (a.left + a.width / 2), dy = b.top + b.height / 2 - (a.top + a.height / 2);
  f.animate([
    { transform: "translate(0,0) scale(1) rotate(0)", opacity: 1 },
    { transform: `translate(${dx * 0.45}px, ${dy * 0.45 - 90}px) scale(0.75) rotate(-8deg)`, opacity: 1, offset: 0.5 },
    { transform: `translate(${dx}px, ${dy}px) scale(0.15) rotate(10deg)`, opacity: 0.3 },
  ], { duration: 650, easing: "cubic-bezier(0.45, 0, 0.2, 1)" }).finished.then(() => f.remove());
}

// ---------- Catálogo ----------
const img = (url, w) => url ? `${url}?w=${w}&q=80&auto=format&fit=crop` : "";

function renderFilters() {
  const cats = ["Todos", ...new Set(products.map((p) => p.category))];
  $("filters").replaceChildren(...cats.map((c) => el("button", {
    className: "chip" + (c === filter ? " is-active" : ""), textContent: c,
    onclick: () => { filter = c; renderFilters(); renderGrid(); },
  })));
}

const io = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
}, { threshold: 0.12 }) : null;

function renderGrid() {
  const list = products.filter((p) => filter === "Todos" || p.category === filter);
  $("grid").replaceChildren(...list.map((p, i) => {
    const photo = el("img", { src: img(p.image, 640), alt: p.name, loading: "lazy" });
    const out = p.stock === 0, low = p.stock > 0 && p.stock <= 5;
    const add = el("button", { className: "add", disabled: out }, svg("M12 5v14M5 12h14"), out ? "Agotado" : "Agregar");
    add.onclick = () => {
      addToCart(p, photo);
      add.classList.add("added");
      add.lastChild.textContent = "Agregado";
      setTimeout(() => { add.classList.remove("added"); add.lastChild.textContent = "Agregar"; }, 1400);
    };
    const card = el("article", { className: "card reveal" },
      el("div", { className: "card-inner" },
        el("div", { className: "card-media" }, photo,
          el("span", { className: "stock-tag" + (out ? " out" : low ? " low" : ""), textContent: out ? "Agotado" : low ? `Últimas ${p.stock}` : "En stock" })),
        el("div", { className: "card-body" },
          el("span", { className: "cat", textContent: p.category }),
          el("h3", { textContent: p.name }),
          el("p", { className: "tagline", textContent: p.tagline }),
          el("div", { className: "card-foot" }, el("span", { className: "price", textContent: money(p.price_cents) }), add))));
    card.style.setProperty("--glow", p.glow || "#22d3ee");
    card.style.transitionDelay = `${(i % 4) * 70}ms`;
    // foco de luz que sigue al mouse dentro de la tarjeta
    card.addEventListener("pointermove", (ev) => {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${ev.clientX - r.left}px`);
      card.style.setProperty("--my", `${ev.clientY - r.top}px`);
    });
    if (io) io.observe(card); else card.classList.add("in");
    return card;
  }));
}

// El hero se inclina un poco siguiendo el mouse.
$("hero-art").addEventListener("pointermove", (ev) => {
  if (calm()) return;
  const r = ev.currentTarget.getBoundingClientRect();
  const x = (ev.clientX - r.left) / r.width - 0.5, y = (ev.clientY - r.top) / r.height - 0.5;
  const frame = ev.currentTarget.querySelector(".frame");
  frame.style.setProperty("--ry", `${x * 14}deg`);
  frame.style.setProperty("--rx", `${-y * 10}deg`);
});
$("hero-art").addEventListener("pointerleave", (ev) => {
  const frame = ev.currentTarget.querySelector(".frame");
  frame.style.removeProperty("--ry");
  frame.style.removeProperty("--rx");
});

// ---------- Checkout ----------
const form = $("co-form");
function openCheckout() {
  closeCart();
  $("checkout").hidden = false;
  document.body.classList.add("lock");
  $("stripe-method").hidden = !config.stripe;
  $("co-error").textContent = "";
  const lines = cartLines();
  $("co-items").replaceChildren(...lines.map(({ p, qty }) => el("li", {}, el("img", { src: img(p.image, 120), alt: "" }),
    el("div", {}, el("b", { textContent: p.name }), el("span", { textContent: `${qty} × ${money(p.price_cents)}` })),
    el("strong", { textContent: money(p.price_cents * qty) }))));
  const t = totals(cartSubtotal());
  $("co-sums").replaceChildren(...sumsDl(t));
  $("pay-label").textContent = `Pagar ${money(t.total)}`;
  setTimeout(() => form.fullname.focus(), 50);
}
function closeCheckout() {
  $("checkout").hidden = true;
  document.body.classList.remove("lock");
}

function brandOf(n) {
  if (/^4/.test(n)) return "visa";
  if (/^(5[1-5]|2[2-7])/.test(n)) return "mastercard";
  if (/^3[47]/.test(n)) return "amex";
  return "";
}

function syncCard() {
  const digits = form.number.value.replace(/\D/g, "").slice(0, 19);
  form.number.value = digits.replace(/(.{4})/g, "$1 ").trim();
  const shown = (digits + "•".repeat(Math.max(0, 16 - digits.length))).replace(/(.{4})/g, "$1 ").trim();
  $("cv-number").textContent = shown;
  const brand = brandOf(digits);
  $("card3d").dataset.brand = brand;
  $("cv-brand").textContent = { visa: "VISA", mastercard: "MASTERCARD", amex: "AMEX" }[brand] || "GAMERSTORE";
  $("cv-name").textContent = form.holder.value.trim() || "TU NOMBRE";
  let exp = form.exp.value.replace(/\D/g, "").slice(0, 4);
  if (exp.length > 2) exp = exp.slice(0, 2) + "/" + exp.slice(2);
  form.exp.value = exp;
  $("cv-exp").textContent = exp || "MM/AA";
  form.cvc.value = form.cvc.value.replace(/\D/g, "").slice(0, 4);
  $("cv-cvc").textContent = form.cvc.value ? "•".repeat(form.cvc.value.length) : "•••";
}
for (const name of ["number", "holder", "exp", "cvc"]) form[name].addEventListener("input", syncCard);
form.cvc.addEventListener("focus", () => $("card3d").classList.add("flip"));
form.cvc.addEventListener("blur", () => $("card3d").classList.remove("flip"));
for (const b of document.querySelectorAll(".test-cards button")) {
  b.onclick = () => {
    form.number.value = b.dataset.card;
    form.exp.value = "1230";
    form.cvc.value = "123";
    if (!form.holder.value) form.holder.value = form.fullname.value || "Rodrigo Poveda";
    syncCard();
  };
}
for (const r of form.paymethod) r.addEventListener("change", () => { $("card-fields").hidden = form.paymethod.value !== "card"; });

function invalid(input, msg) {
  replay(input, "invalid");
  input.focus();
  $("co-error").textContent = msg;
  return false;
}
function validateForm() {
  form.querySelectorAll(".invalid").forEach((i) => i.classList.remove("invalid"));
  if (form.fullname.value.trim().length < 3) return invalid(form.name, "Escribí tu nombre completo.");
  if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(form.email.value.trim())) return invalid(form.email, "El correo no es válido.");
  if (form.address.value.trim().length < 8) return invalid(form.address, "Escribí una dirección más completa.");
  if (form.paymethod.value !== "card") return true;
  if (form.number.value.replace(/\D/g, "").length < 13) return invalid(form.number, "Revisá el número de la tarjeta.");
  if (form.holder.value.trim().length < 3) return invalid(form.holder, "Escribí el nombre como aparece en la tarjeta.");
  if (!/^\d{2}\/\d{2}$/.test(form.exp.value)) return invalid(form.exp, "La fecha va así: MM/AA.");
  if (form.cvc.value.length < 3) return invalid(form.cvc, "El CVC tiene 3 dígitos (4 en Amex).");
  return true;
}

function loading(btn, on) { btn.classList.toggle("loading", on); btn.disabled = on; }

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("co-error").textContent = "";
  if (!validateForm()) return;
  const btn = $("pay-btn");
  loading(btn, true);
  const items = cartLines().map(({ p, qty }) => ({ id: p.id, qty }));
  const customer = { name: form.fullname.value.trim(), email: form.email.value.trim(), address: form.address.value.trim() };
  try {
    if (form.paymethod.value === "stripe") {
      const r = await api("/api/checkout", { method: "stripe", items, customer });
      location.href = r.url;
      return;
    }
    // 1) la tarjeta va a la pasarela, que devuelve un token de un solo uso
    const [mm, yy] = form.exp.value.split("/");
    const tok = await api("/gateway/tokens", { number: form.number.value, exp_month: mm, exp_year: yy, cvc: form.cvc.value, name: form.holder.value });
    // 2) la tienda cobra con el token: nunca ve el número completo
    const r = await api("/api/checkout", { method: "card", items, customer, token: tok.token });
    form.cvc.value = "";
    form.number.value = "";
    syncCard();
    if (r.status === "requires_action") openTds(r);
    else paid(r.number);
  } catch (e) {
    $("co-error").textContent = e.message;
    replay($("co-error"), "invalid");
    if (e.status === 400 && /stock|carrito|existe/i.test(e.message)) refreshProducts();
  } finally {
    loading(btn, false);
  }
});

// ---------- 3-D Secure ----------
let tdsOrder = null;
function openTds(r) {
  tdsOrder = r.number;
  $("tds-amount").textContent = money(totals(cartSubtotal()).total);
  $("tds-card").textContent = `${(r.brand || "").toUpperCase()} •••• ${r.last4}`;
  $("tds-error").textContent = "";
  $("tds-code").value = "";
  $("tds").hidden = false;
  setTimeout(() => $("tds-code").focus(), 60);
}
$("tds-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("tds-btn");
  loading(btn, true);
  try {
    await api("/api/checkout/confirm", { number: tdsOrder, code: $("tds-code").value });
    $("tds").hidden = true;
    paid(tdsOrder);
  } catch (e) {
    $("tds-error").textContent = e.message + (e.code === "authentication_failed" ? " El pago se canceló; volvé a intentarlo." : "");
    replay($("tds-code"), "invalid");
    if (e.code === "authentication_failed") {
      setTimeout(() => {
        $("tds").hidden = true;
        $("co-error").textContent = "Tu banco no aprobó el pago. Volvé a ingresar la tarjeta para intentarlo de nuevo.";
        form.number.focus();
      }, 2200);
    }
  } finally {
    loading(btn, false);
  }
});

// ---------- Pago aprobado ----------
function paid(number) {
  closeCheckout();
  cart.clear();
  saveCart();
  renderCartBadge(false);
  renderCart();
  $("done-sub").textContent = `Pedido ${number}. Tu factura ya está lista.`;
  $("invoice-link").href = "/factura/" + encodeURIComponent(number);
  $("success").hidden = false;
  document.body.classList.add("lock");
  const ring = document.querySelector(".ring");
  ring.replaceWith(ring.cloneNode(true)); // reinicia la animación del check
  confetti();
  refreshProducts();
}
$("keep-shopping").onclick = () => { $("success").hidden = true; document.body.classList.remove("lock"); };

function confetti() {
  if (calm()) return;
  const box = $("confetti");
  box.replaceChildren();
  const colors = ["#22d3ee", "#8b5cf6", "#e879f9", "#34d399", "#fbbf24"];
  for (let i = 0; i < 60; i++) {
    const c = el("i");
    c.style.background = colors[i % colors.length];
    box.append(c);
    const a = Math.random() * Math.PI * 2, d = 180 + Math.random() * 320;
    c.animate([
      { transform: "translate(-50%, -50%) rotate(0)", opacity: 1 },
      { transform: `translate(${Math.cos(a) * d}px, ${Math.sin(a) * d * 0.6 + 320}px) rotate(${Math.random() * 900}deg)`, opacity: 0 },
    ], { duration: 1400 + Math.random() * 800, delay: 150 + Math.random() * 120, easing: "cubic-bezier(.15,.7,.4,1)", fill: "forwards" });
  }
}

// ---------- Inventario ----------
function countUp(node, to, fmt) {
  if (calm()) { node.textContent = fmt(to); return; }
  const start = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - start) / 900);
    node.textContent = fmt(Math.round(to * (1 - Math.pow(1 - k, 3))));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
  setTimeout(() => { node.textContent = fmt(to); }, 1000); // por si el navegador pausa la animación
}

async function loadAdmin(flashId) {
  const [s, orders, moves] = await Promise.all([api("/api/admin/summary"), api("/api/admin/orders"), api("/api/admin/movements")]);
  products = await api("/api/products");
  const kpis = [
    ["Ingresos", s.revenue_cents, money, "#22d3ee"], ["Pedidos pagados", s.orders, String, "#8b5cf6"],
    ["Unidades vendidas", s.units, String, "#e879f9"], ["Valor del inventario", s.stock_value_cents, money, "#34d399"],
  ];
  $("kpis").replaceChildren(...kpis.map(([label, value, fmt, color], i) => {
    const strong = el("strong", { textContent: fmt(0) });
    const k = el("div", { className: "kpi" }, el("p", { textContent: label }), strong);
    k.style.setProperty("--kc", color);
    k.style.animationDelay = `${i * 70}ms`;
    countUp(strong, value, fmt);
    return k;
  }));
  $("low-alert").hidden = !s.low_stock.length;
  $("low-alert").textContent = `Stock bajo: ${s.low_stock.map((p) => `${p.name} (${p.stock})`).join(", ")}. Conviene reponer pronto.`;

  const max = Math.max(...products.map((p) => p.stock), 20);
  $("inv-count").textContent = `${products.length} productos`;
  $("inventory").replaceChildren(...products.map((p) => {
    const qty = el("input", { type: "number", min: 1, value: 1, "aria-label": "Cantidad a ajustar" });
    const adjust = async (sign) => {
      const n = parseInt(qty.value, 10);
      if (!n || n < 1) return toast("Escribí una cantidad válida", "bad");
      try {
        await api("/api/admin/stock", { id: p.id, delta: sign * n, reason: sign > 0 ? "Ingreso de mercadería" : "Salida manual (merma o daño)" });
        toast(`${p.name}: ${sign > 0 ? "+" : "−"}${n} unidades`, "ok");
        loadAdmin(p.id);
      } catch (e) { toast(e.message, "bad"); }
    };
    const state = p.stock === 0 ? "out" : p.stock <= 5 ? "low" : "";
    const bar = el("span");
    const row = el("div", { className: "inv-row" + (p.id === flashId ? " flash" : "") },
      el("img", { src: img(p.image, 120), alt: "" }),
      el("div", {}, el("b", { textContent: p.name }), el("small", { textContent: `${p.sku} · ${p.category} · ${money(p.price_cents)}` })),
      el("div", { className: "meter " + state }, el("span", { textContent: p.stock === 0 ? "Agotado" : `${p.stock} unidades` }), el("div", { className: "meter-bar" }, bar)),
      el("div", { className: "adj" },
        el("button", { textContent: "−", title: "Sacar del inventario", onclick: () => adjust(-1) }), qty,
        el("button", { textContent: "+", title: "Agregar al inventario", onclick: () => adjust(1) })));
    requestAnimationFrame(() => { bar.style.width = Math.max(3, (p.stock / max) * 100) + "%"; });
    return row;
  }));

  const statusText = { paid: "Pagado", failed: "Rechazado", pending: "Pendiente", requires_action: "Esperando banco" };
  $("orders").replaceChildren(...(orders.length ? orders.map((o) => el("div", { className: "order-row" },
    el("div", {}, el("b", { textContent: `${o.number} · ${o.customer_name}` }),
      el("small", { textContent: `${new Date(o.created_at).toLocaleString("es-NI")} · ${o.card_brand ? o.card_brand.toUpperCase() + " " + (o.card_last4 || "") : o.provider}${o.note ? " · " + o.note : ""}` })),
    el("span", { className: "status " + o.status, textContent: statusText[o.status] || o.status }),
    o.status === "paid" ? el("a", { href: "/factura/" + o.number, target: "_blank", rel: "noopener", textContent: money(o.total_cents) + " · Factura" })
      : el("span", { className: "muted", textContent: money(o.total_cents) }))) : [el("p", { className: "muted", textContent: "Todavía no hay pedidos." })]));

  $("moves").replaceChildren(...moves.map((m) => el("li", {},
    el("span", { className: "delta " + (m.delta > 0 ? "up" : "down"), textContent: (m.delta > 0 ? "+" : "") + m.delta }),
    el("div", {}, el("b", { textContent: m.name }), el("br"),
      el("small", { textContent: `${m.reason}${m.ref ? " · " + m.ref : ""} · ${new Date(m.created_at).toLocaleString("es-NI")}` })))));
}

$("new-product").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  try {
    const p = await api("/api/admin/products", {
      sku: f.sku.value.trim().toUpperCase(), name: f.pname.value, category: f.category.value, tagline: f.tagline.value,
      price_cents: Math.round(parseFloat(f.price.value) * 100), stock: parseInt(f.stock.value, 10), image: f.image.value.trim(),
    });
    toast(`${p.name} agregado al inventario`, "ok");
    f.reset();
    loadAdmin(p.id);
  } catch (e) { toast(e.message, "bad"); }
});
$("refresh-admin").onclick = () => loadAdmin();

// ---------- Rutas ----------
function route() {
  const admin = location.hash === "#admin";
  $("store").hidden = admin;
  $("admin").hidden = !admin;
  for (const a of document.querySelectorAll(".links a")) a.classList.toggle("is-active", a.dataset.route === (admin ? "admin" : "store"));
  if (admin) loadAdmin().catch((e) => toast(e.message, "bad"));
}
window.addEventListener("hashchange", route);

async function refreshProducts() {
  products = await api("/api/products");
  for (const [id, q] of cart) { const p = byId(id); if (!p || p.stock === 0) cart.delete(id); else if (q > p.stock) cart.set(id, p.stock); }
  saveCart();
  renderFilters();
  renderGrid();
  renderCart();
  renderCartBadge(false);
}

// ---------- Eventos generales ----------
$("open-cart").onclick = openCart;
$("close-cart").onclick = closeCart;
$("scrim").onclick = closeCart;
$("go-checkout").onclick = openCheckout;
$("close-checkout").onclick = closeCheckout;
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape") return;
  if (!$("tds").hidden) return; // el banco no se cierra con Escape
  if (!$("success").hidden) $("keep-shopping").click();
  else if (!$("checkout").hidden) closeCheckout();
  else closeCart();
});

// Vuelta desde Stripe Checkout
async function stripeReturn() {
  const q = new URLSearchParams(location.search);
  const session = q.get("stripe_session"), cancel = q.get("stripe_cancel");
  if (!session && !cancel) return;
  history.replaceState(null, "", location.pathname + location.hash);
  if (cancel) return toast("Cancelaste el pago en Stripe. Tu carrito sigue aquí.");
  try {
    const r = await api("/api/stripe/confirm?session_id=" + encodeURIComponent(session));
    paid(r.number);
  } catch (e) { toast(e.message, "bad"); }
}

(async function init() {
  loadCart();
  try {
    [config, products] = await Promise.all([api("/api/config"), api("/api/products")]);
  } catch {
    toast("No se pudo conectar con la tienda. ¿Está corriendo el servidor?", "bad");
    return;
  }
  await refreshProducts();
  route();
  stripeReturn();
})();
