/* App del cliente conectada al servidor (backend/main.py).
 *
 *   GET  /api/catalogo          modelos y colores (PNG + sidecar de tu catalogo)
 *   POST /api/sesion            foto del cliente  -> ventanas detectadas
 *   POST /api/sesion/ejemplo    foto de ejemplo   -> ventanas detectadas
 *   POST /api/render            sesion + ventanas + color -> imagen con la ventana nueva
 *   POST /api/presupuesto       solicitud del cliente
 */
(function () {
  "use strict";

  const API = String(window.API_BASE || "").replace(/\/$/, "");
  const ruta = p => (p && p.startsWith("/") ? API + p : p);
  let CATALOGO = [], EJEMPLOS = [];

  // =========================================================== estado
  const E = {
    pila: [], actual: null,
    producto: null, variante: null,   // modelo y color (cada color es un PNG del catalogo)
    sesion: null,
    foto: null,                       // {url, ancho, alto, nombre, ejemplo}
    ventanas: [],                     // {id, quad, interior, origen, sel, ancho_mm, alto_mm}
    editando: null, verEntera: false, resEntera: false,
    filtro: "Todas", busqueda: "", proyectoId: null,
    resultado: null,                  // {resultado, descarga, original, img}
  };
  const $ = (s, r = document) => r.querySelector(s);
  const pantalla = $("#pantalla");
  const fmt = n => Number(n).toLocaleString("es-ES", { maximumFractionDigits: 0 });
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const h = html => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const plural = (n, a, b) => `${n} ${n === 1 ? a : b}`;

  // ---------------------------------------------------------- llamadas al servidor
  async function api(camino, { metodo = "GET", json, form } = {}) {
    let r;
    try {
      r = await fetch(API + camino, {
        method: metodo,
        headers: json ? { "Content-Type": "application/json" } : undefined,
        body: json ? JSON.stringify(json) : form,
      });
    } catch {
      throw new Error("No hay conexión con el servidor. Comprueba tu conexión e inténtalo de nuevo.");
    }
    if (!r.ok) {
      let detalle = "";
      try { detalle = (await r.json()).detail; } catch { /* sin cuerpo */ }
      const e = new Error(typeof detalle === "string" && detalle ? detalle : `Error ${r.status} del servidor`);
      e.estado = r.status; throw e;
    }
    return r.json();
  }

  // ---------------------------------------------------------- almacenamiento local (puede fallar: modo privado)
  const guardado = {
    leer(k, def) { try { const v = localStorage.getItem("ventanas." + k); return v ? JSON.parse(v) : def; } catch { return def; } },
    escribir(k, v) { try { localStorage.setItem("ventanas." + k, JSON.stringify(v)); return true; } catch { return false; } },
  };
  const favoritos = new Set(guardado.leer("favoritos", []));

  // ---------------------------------------------------------- iconos
  const I = {
    atras: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
    corazon: '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
    camara: '<svg viewBox="0 0 24 24"><path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h2.2l1.5-2h5.6l1.5 2h2.2A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z"/><circle cx="12" cy="13" r="3.5"/></svg>',
    galeria: '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="14" rx="1.5"/><path d="M4 16l4.5-4.5 4 4 2.5-2.5L20 18"/><circle cx="15.5" cy="9.5" r="1.5"/></svg>',
    ajustar: '<svg viewBox="0 0 24 24"><path d="M5 5h4M5 5v4M19 5h-4M19 5v4M5 19h4M5 19v-4M19 19h-4M19 19v-4"/></svg>',
    metro: '<svg viewBox="0 0 24 24"><path d="M3.5 15.5l12-12 5 5-12 12z"/><path d="M8 11l2 2M11 8l2 2M14 5l2 2"/></svg>',
    papelera: '<svg viewBox="0 0 24 24"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    flechas: '<svg viewBox="0 0 24 24"><path d="M9 7l-5 5 5 5M15 7l5 5-5 5"/></svg>',
    buscar: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>',
    mas: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    descargar: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
    carpeta: '<svg viewBox="0 0 24 24"><path d="M4 7.5A1.5 1.5 0 0 1 5.5 6H10l2 2h6.5A1.5 1.5 0 0 1 20 9.5V18a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18z"/></svg>',
    ventana: '<svg viewBox="0 0 64 76"><rect x="1" y="1" width="62" height="74" rx="2"/><rect x="7" y="7" width="22" height="62"/><rect x="35" y="7" width="22" height="62"/><path d="M1 12V1h11M52 1h11v11M63 64v11H52M12 75H1V64" stroke-width="2.4"/></svg>',
    nube: '<svg viewBox="0 0 24 24"><path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9.5 4.3 4.3 0 0 0 7 18z"/><path d="M4 4l16 16"/></svg>',
  };

  // ---------------------------------------------------------- utilidades de interfaz
  let _toast;
  function aviso(texto, ms = 3400) {
    const t = $("#toast"); t.textContent = texto; t.hidden = false;
    clearTimeout(_toast); _toast = setTimeout(() => (t.hidden = true), ms);
  }
  function cargando(texto, imagen) {
    $("#cargando").hidden = !texto;
    if (!texto) return;
    $("#cargando-texto").textContent = texto;
    const img = $("#cargando-img");
    if (imagen !== undefined) { img.hidden = !imagen; if (imagen) img.src = imagen; }
  }

  function abrirHoja(html, alMontar) {
    const hoja = $("#hoja"), fondo = $("#hoja-fondo");
    hoja.innerHTML = ""; hoja.appendChild(typeof html === "string" ? h(`<div>${html}</div>`) : html);
    hoja.hidden = fondo.hidden = false;
    fondo.onclick = cerrarHoja;
    alMontar && alMontar(hoja);
    setTimeout(() => (hoja.querySelector("input") || hoja).focus?.(), 50);
  }
  function cerrarHoja() { $("#hoja").hidden = $("#hoja-fondo").hidden = true; }

  function cabecera(titulo, { atras = true, derecha = "", paso = "" } = {}) {
    return `<header class="cabecera">
      ${atras ? `<button class="redondo" data-atras aria-label="Volver">${I.atras}</button>` : ""}
      <h2>${esc(titulo)}</h2>${paso ? `<span class="paso">${paso}</span>` : ""}${derecha}</header>`;
  }
  function progreso(n) { return `<div class="progreso" aria-label="Paso ${n} de 3">${[1, 2, 3].map(i => `<i class="${i <= n ? "hecho" : ""}"></i>`).join("")}</div>`; }

  // ---------------------------------------------------------- navegacion
  const PESTANAS = ["inicio", "catalogo", "proyectos"];
  const PANTALLAS = {};
  function ir(nombre, datos = {}, { apilar = true } = {}) {
    if (apilar && E.actual) E.pila.push(E.actual);
    E.actual = { nombre, datos };
    pintar();
  }
  function atras() { E.actual = E.pila.pop() || { nombre: "inicio", datos: {} }; pintar(); }
  function pestana(nombre) { E.pila = []; E.actual = { nombre, datos: {} }; pintar(); }
  function pintar() {
    cerrarHoja();
    $("#toast").hidden = true;
    const { nombre, datos } = E.actual;
    const conPestanas = PESTANAS.includes(nombre);
    $("#app").classList.toggle("con-pestanas", conPestanas);
    $("#app").classList.toggle("sin-pestanas", !conPestanas);
    $("#pestanas").hidden = !conPestanas;
    document.querySelectorAll("#pestanas button").forEach(b => b.classList.toggle("activa", b.dataset.tab === nombre));
    pantalla.innerHTML = "";
    window.scrollTo(0, 0);
    PANTALLAS[nombre](datos);
    pantalla.querySelectorAll("[data-atras]").forEach(b => (b.onclick = atras));
  }
  document.querySelectorAll("#pestanas button").forEach(b => (b.onclick = () => pestana(b.dataset.tab)));

  // ---------------------------------------------------------- catalogo: modelos y colores
  const modelo = id => CATALOGO.find(p => p.id === id);
  const variante = (p, vid) => p.variantes.find(v => v.id === vid) || p.variantes[0];
  const subtitulo = p => [p.material, p.apertura].filter(Boolean).join(" · ");
  const precioDesde = p => (p.precio_m2 ? `desde ${fmt(p.precio_m2)} €/m²` : "Precio a consultar");

  function lamina(p, vid) {
    const v = variante(p, vid);
    const img = h(`<img src="${esc(ruta(v.imagen))}" alt="${esc(p.nombre)} en ${esc(v.nombre)}" loading="lazy" decoding="async">`);
    img.onerror = () => img.classList.add("sin-imagen");
    return img;
  }
  function tarjetaProducto(p) {
    const el = h(`<button class="tarjeta">
        <div class="lamina">${p.destacado ? '<span class="etiqueta">Destacado</span>' : ""}</div>
        <div class="info"><span class="nombre">${esc(p.nombre)}</span><span class="sub">${esc(subtitulo(p))}</span>
          <span class="precio">${precioDesde(p)}</span>
          <span class="puntos">${p.variantes.map(v => `<i style="background:${esc(v.hex)}" title="${esc(v.nombre)}"></i>`).join("")}</span></div>
      </button>`);
    el.querySelector(".lamina").appendChild(lamina(p));
    el.onclick = () => ir("ficha", { id: p.id });
    return el;
  }
  function selectorColor(p, actual, alCambiar) {
    const el = h(`<div><div class="colores" role="radiogroup" aria-label="Color">${p.variantes.map(v =>
      `<button class="color ${v.id === actual ? "activo" : ""}" role="radio" aria-checked="${v.id === actual}" data-c="${esc(v.id)}" style="background:${esc(v.hex)}" aria-label="${esc(v.nombre)}"></button>`).join("")}</div>
      <p class="color-nombre"></p></div>`);
    const nombre = vid => { const v = variante(p, vid); el.querySelector(".color-nombre").innerHTML = `<b>${esc(v.nombre)}</b>${v.codigo ? ` · ${esc(v.codigo)}` : ""}`; };
    nombre(actual);
    el.querySelector(".colores").onclick = e => {
      const c = e.target.dataset.c; if (!c) return;
      el.querySelectorAll(".color").forEach(b => { b.classList.toggle("activo", b.dataset.c === c); b.setAttribute("aria-checked", b.dataset.c === c); });
      nombre(c); alCambiar(c);
    };
    return el;
  }

  // ---------------------------------------------------------- imagenes y comparador
  function cargarImagen(src) {
    return new Promise((ok, ko) => {
      const i = new Image(); i.crossOrigin = "anonymous";
      i.onload = () => ok(i); i.onerror = () => ko(new Error("No se ha podido cargar la imagen"));
      i.src = src;
    });
  }
  function comparador(antes, despues, { rotulos = true, inicial = 50 } = {}) {
    const el = h(`<div class="comparador" style="--corte:${inicial}%" aria-label="Compara antes y después. Arrastra para mover el corte.">
        <div class="linea-corte"></div>
        <div class="tirador">${I.flechas}</div>
        ${rotulos ? '<span class="rotulo izq">ANTES</span><span class="rotulo der">DESPUÉS</span>' : ""}
      </div>`);
    despues.className = "despues"; antes.className = "antes";
    el.prepend(antes); el.prepend(despues);
    const mover = ev => {
      const r = el.getBoundingClientRect();
      el.style.setProperty("--corte", `${Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)) * 100}%`);
    };
    el.addEventListener("pointerdown", ev => { el.setPointerCapture(ev.pointerId); mover(ev); });
    el.addEventListener("pointermove", ev => { if (el.hasPointerCapture(ev.pointerId)) mover(ev); });
    el.tabIndex = 0;
    el.addEventListener("keydown", ev => {
      const v = parseFloat(el.style.getPropertyValue("--corte")) || 50;
      if (ev.key === "ArrowLeft") el.style.setProperty("--corte", `${Math.max(0, v - 5)}%`);
      if (ev.key === "ArrowRight") el.style.setProperty("--corte", `${Math.min(100, v + 5)}%`);
    });
    return el;
  }
  function encuadre(ventanas, ancho, alto, margen) {
    if (!ventanas.length) return [0, 0, ancho, alto];
    const xs = ventanas.flatMap(v => v.quad.map(p => p[0])), ys = ventanas.flatMap(v => v.quad.map(p => p[1]));
    const m = margen * Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 0.22 * ancho);
    return [Math.max(0, Math.min(...xs) - m), Math.max(0, Math.min(...ys) - m), Math.min(ancho, Math.max(...xs) + m), Math.min(alto, Math.max(...ys) + m)];
  }
  // recorta `img` (de cualquier tamano) en la zona roi, dada en pixeles de la foto de ancho `anchoFoto`
  // resolucion del recorte: la de la pantalla real (retina incluida), no menos
  const ANCHO_PANTALLA = Math.min(2200, Math.round(Math.min(window.innerWidth || 420, 520) * (window.devicePixelRatio || 2)));
  function recortar(img, [x0, y0, x1, y1], anchoFoto, maxAncho = ANCHO_PANTALLA) {
    const k = img.naturalWidth / anchoFoto, w = (x1 - x0) * k, hh = (y1 - y0) * k, f = Math.min(2, maxAncho / w);
    const cv = document.createElement("canvas");
    cv.width = Math.max(1, Math.round(w * f)); cv.height = Math.max(1, Math.round(hh * f));
    const cx = cv.getContext("2d"); cx.imageSmoothingQuality = "high";
    cx.drawImage(img, x0 * k, y0 * k, w, hh, 0, 0, cv.width, cv.height);
    return cv;
  }

  // ---------------------------------------------------------- presupuesto orientativo
  function medidasDe(v) {
    const [a, b, c, d] = v.quad;
    const wq = (Math.hypot(b[0] - a[0], b[1] - a[1]) + Math.hypot(c[0] - d[0], c[1] - d[1])) / 2;
    const hq = (Math.hypot(d[0] - a[0], d[1] - a[1]) + Math.hypot(c[0] - b[0], c[1] - b[1])) / 2;
    const ancho = v.ancho_mm || 1200, alto = v.alto_mm || Math.round((v.ancho_mm || 1200) * hq / wq / 10) * 10;
    return { ancho, alto, reales: !!(v.ancho_mm && v.alto_mm) };
  }
  function estimacion(p, ventanas) {
    let m2 = 0, reales = true;
    for (const v of ventanas) { const m = medidasDe(v); m2 += (m.ancho * m.alto) / 1e6; reales = reales && m.reales; }
    if (!p.precio_m2) return { min: null, max: null, m2, reales };
    const base = Math.max(1, m2) * p.precio_m2;
    return { min: Math.round(base * 0.9 / 10) * 10, max: Math.round(base * 1.15 / 10) * 10, m2, reales };
  }
  const rango = est => (est.min ? `${fmt(est.min)} – ${fmt(est.max)} €` : "A consultar");

  // =========================================================== 1. INICIO
  PANTALLAS.inicio = () => {
    const lanzador = h(`<section class="lanzador">
        <span class="marco-ventana" aria-hidden="true">${I.ventana}</span>
        <span class="chip-ia"><i></i>Detección automática</span>
        <h1>Prueba ventanas en tu fachada</h1>
        <p>Desde la calle, de frente a la fachada.</p>
        <div class="botones">
          <label class="boton" for="i-camara">${I.camara} Hacer foto</label>
          <label class="boton claro" for="i-galeria">${I.galeria} Galería</label>
        </div>
        <input id="i-camara" class="oculto" type="file" accept="image/*" capture="environment">
        <input id="i-galeria" class="oculto" type="file" accept="image/*">
      </section>`);
    lanzador.querySelectorAll("input").forEach(i => (i.onchange = e => { const f = e.target.files[0]; e.target.value = ""; f && (asegurarProducto(), usarArchivo(f)); }));
    pantalla.append(lanzador);

    if (EJEMPLOS.length) {
      const ej = h(`<section class="bloque"><h3>Probar con un ejemplo</h3><div class="ejemplos-mini">${EJEMPLOS.map(e =>
        `<button data-e="${esc(e.id)}"><img src="${esc(e.imagen)}" alt="${esc(e.nombre)}" loading="lazy"><span>${esc(e.nombre)}</span></button>`).join("")}</div></section>`);
      ej.onclick = e => { const b = e.target.closest("[data-e]"); if (b) { asegurarProducto(); usarEjemplo(b.dataset.e); } };
      pantalla.append(ej);
    }

    const destacados = CATALOGO.filter(p => p.destacado).length ? CATALOGO.filter(p => p.destacado) : CATALOGO.slice(0, 6);
    const bloque = h(`<section class="bloque"><h3>Modelos <button data-todos>Ver todos</button></h3><div class="carrusel"></div></section>`);
    destacados.forEach(p => bloque.querySelector(".carrusel").append(tarjetaProducto(p)));
    bloque.querySelector("[data-todos]").onclick = () => pestana("catalogo");
    pantalla.append(bloque);

    const recientes = guardado.leer("proyectos", []).filter(pr => pr.sesion).slice(0, 2);
    if (recientes.length) {
      const rec = h(`<section class="bloque"><h3>Recientes <button data-todos>Ver todos</button></h3><div style="display:grid;gap:8px"></div></section>`);
      recientes.forEach(pr => rec.querySelector("div").append(filaProyecto(pr)));
      rec.querySelector("[data-todos]").onclick = () => pestana("proyectos");
      pantalla.append(rec);
    }
  };
  function asegurarProducto() {
    if (!E.producto && CATALOGO.length) { E.producto = CATALOGO.find(p => p.destacado) || CATALOGO[0]; E.variante = E.producto.variantes[0].id; }
  }

  // =========================================================== 2. CATALOGO
  PANTALLAS.catalogo = () => {
    pantalla.append(h(`<h1 class="titulo-pagina">Catálogo</h1>`));
    const buscador = h(`<label class="buscador">${I.buscar}<input type="search" placeholder="Buscar modelo, material o apertura" value="${esc(E.busqueda)}" aria-label="Buscar"></label>`);
    pantalla.append(buscador);
    const materiales = [...new Set(CATALOGO.map(p => p.material).filter(Boolean))];
    const filtros = ["Todas", ...materiales, "Guardadas"];
    if (!filtros.includes(E.filtro)) E.filtro = "Todas";
    const chips = h(`<div class="chips">${filtros.map(f => `<button class="chip ${E.filtro === f ? "activo" : ""}" data-f="${esc(f)}">${esc(f)}</button>`).join("")}</div>`);
    pantalla.append(chips);
    const rejilla = h(`<div class="rejilla"></div>`);
    pantalla.append(rejilla);
    function listar() {
      rejilla.innerHTML = "";
      const q = E.busqueda.trim().toLowerCase();
      const lista = CATALOGO.filter(p =>
        (E.filtro === "Todas" || p.material === E.filtro || (E.filtro === "Guardadas" && favoritos.has(p.id))) &&
        (!q || `${p.nombre} ${p.material} ${p.apertura} ${p.variantes.map(v => v.nombre).join(" ")}`.toLowerCase().includes(q)));
      if (!lista.length) {
        rejilla.style.display = "block";
        rejilla.append(h(`<div class="vacio">${I.carpeta}<b>${E.filtro === "Guardadas" ? "Aún no has guardado ninguna" : "Sin resultados"}</b>
          <span>${E.filtro === "Guardadas" ? "Toca el corazón en la ficha de un modelo para guardarlo aquí." : "Prueba con otra búsqueda."}</span></div>`));
        return;
      }
      rejilla.style.display = "";
      lista.forEach(p => rejilla.append(tarjetaProducto(p)));
    }
    chips.onclick = e => { const f = e.target.dataset.f; if (!f) return; E.filtro = f; chips.querySelectorAll(".chip").forEach(c => c.classList.toggle("activo", c.dataset.f === f)); listar(); };
    buscador.querySelector("input").oninput = e => { E.busqueda = e.target.value; listar(); };
    listar();
  };

  // =========================================================== 3. FICHA
  const CIFRAS = [["Transmitancia Uw", "Uw · W/m²K"], ["Aislamiento acústico", "dB de aislamiento"], ["Garantía", "años de garantía"]];
  PANTALLAS.ficha = ({ id }) => {
    const p = modelo(id);
    if (!p) return pestana("catalogo");
    let vid = E.producto?.id === p.id ? E.variante : p.variantes[0].id;
    const fav = () => favoritos.has(p.id);
    pantalla.append(h(cabecera("", { derecha: `<button class="redondo ${fav() ? "activo" : ""}" data-fav aria-label="Guardar modelo" aria-pressed="${fav()}">${I.corazon}</button>` })));
    const escap = h(`<div class="escaparate"></div>`);
    pantalla.append(escap);
    const pintarLamina = () => { escap.innerHTML = ""; escap.append(lamina(p, vid)); };
    pintarLamina();
    pantalla.append(h(`<div class="ficha-cab">${subtitulo(p) ? `<span class="linea">${esc(subtitulo(p))}</span>` : ""}<h1>${esc(p.nombre)}</h1>${p.lema ? `<p>${esc(p.lema)}</p>` : ""}</div>`));
    pantalla.append(selectorColor(p, vid, c => { vid = c; pintarLamina(); }));
    const f = p.ficha || {};
    const cifras = CIFRAS.filter(([k]) => f[k]);
    if (cifras.length) pantalla.append(h(`<div class="cifras" style="grid-template-columns:repeat(${cifras.length},1fr)">${cifras.map(([k, etq]) =>
      `<div><b>${esc(String(f[k]).split(" ")[0])}</b><span>${etq}</span></div>`).join("")}</div>`));
    if (Object.keys(f).length) pantalla.append(h(`<dl class="especificaciones">${Object.entries(f).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`));
    pantalla.append(h(`<div class="precio-ficha"><b>${precioDesde(p)}</b>${p.precio_m2 ? "<span>sin IVA ni colocación</span>" : ""}</div>`));
    const hayFoto = E.sesion && E.ventanas.some(v => v.sel);
    const fija = h(`<div class="accion-fija"><button class="boton">${I.camara} ${hayFoto ? "Ver en mi fachada" : "Probar en mi fachada"}</button></div>`);
    fija.querySelector("button").onclick = () => { E.producto = p; E.variante = vid; hayFoto ? ir("resultado") : ir("foto"); };
    pantalla.append(fija);
    pantalla.querySelector("[data-fav]").onclick = e => {
      const b = e.currentTarget;
      fav() ? favoritos.delete(p.id) : favoritos.add(p.id);
      guardado.escribir("favoritos", [...favoritos]);
      b.classList.toggle("activo", fav()); b.setAttribute("aria-pressed", fav());
      aviso(fav() ? "Guardada en tus ventanas" : "Quitada de guardadas");
    };
  };

  // =========================================================== 4. FOTO
  function empezarPrueba() { asegurarProducto(); ir("foto"); }
  PANTALLAS.foto = () => {
    pantalla.append(h(cabecera("Tu fachada", { paso: "1 de 3" })));
    pantalla.append(h(progreso(1)));
    const opc = h(`<div class="opciones-foto">
        <label class="opcion principal" for="f-camara">${I.camara}<div><b>Hacer foto</b><small>Cámara</small></div></label>
        <label class="opcion" for="f-galeria">${I.galeria}<div><b>Galería</b><small>Una foto tuya</small></div></label>
        <input id="f-camara" class="oculto" type="file" accept="image/*" capture="environment">
        <input id="f-galeria" class="oculto" type="file" accept="image/*">
      </div>`);
    pantalla.append(opc);
    opc.querySelectorAll("input").forEach(i => (i.onchange = e => { const f = e.target.files[0]; e.target.value = ""; f && usarArchivo(f); }));
    pantalla.append(h(`<h3 class="titulo-seccion">Consejos</h3>`));
    pantalla.append(h(`<ul class="consejos"><li>Desde la calle</li><li>De frente</li><li>Con luz de día</li><li>Ventanas enteras</li></ul>`));
    if (EJEMPLOS.length) {
      pantalla.append(h(`<h3 class="titulo-seccion">Ejemplos</h3>`));
      const ejs = h(`<div class="ejemplos">${EJEMPLOS.map(e => `<button class="ejemplo" data-e="${esc(e.id)}"><img src="${esc(e.imagen)}" alt="" loading="lazy"><div><b>${esc(e.nombre)}</b><span>${esc(e.descripcion)}</span></div></button>`).join("")}</div>`);
      ejs.onclick = e => { const b = e.target.closest("[data-e]"); b && usarEjemplo(b.dataset.e); };
      pantalla.append(ejs);
    }
  };

  function abrirSesion(res, nombre, ejemplo = null) {
    E.sesion = res.sesion; E.proyectoId = null;
    E.foto = { url: ruta(res.foto), ancho: res.ancho, alto: res.alto, nombre, ejemplo };
    E.ventanas = res.ventanas.map(v => ({ ...v, sel: false }));
    E.editando = null; E.verEntera = false;
    if (!E.ventanas.length) {                       // nada detectado: un marco para colocarlo a mano
      const w = res.ancho * 0.3, hh = w * 1.15, cx = res.ancho / 2, cy = res.alto / 2;
      E.ventanas = [{ id: "m0", origen: "manual", interior: null, sel: true, quad: [[cx - w / 2, cy - hh / 2], [cx + w / 2, cy - hh / 2], [cx + w / 2, cy + hh / 2], [cx - w / 2, cy + hh / 2]] }];
      E.editando = "m0"; E.verEntera = true;
    }
    ir("ventanas");
    const n = res.ventanas.length;
    aviso(res.aviso ? `${res.aviso} Arrastra las 4 esquinas del marco.` : `${plural(n, "ventana detectada", "ventanas detectadas")}. Toca las que quieras cambiar.`, 4200);
  }

  async function usarEjemplo(id) {
    const ej = EJEMPLOS.find(e => e.id === id);
    cargando("Detectando ventanas", ej.imagen);
    try { abrirSesion(await api("/api/sesion/ejemplo", { metodo: "POST", json: { id } }), ej.nombre, id); }
    catch (e) { aviso(e.message); }
    finally { cargando(null); }
  }

  async function usarArchivo(fichero) {
    const url = URL.createObjectURL(fichero);
    cargando("Preparando la foto", url);
    try {
      // se reduce en el movil (sube rapido y el navegador ya la endereza segun el EXIF)
      let img;
      try { img = await cargarImagen(url); } catch { throw new Error("No hemos podido abrir esa imagen. Prueba con otra foto (JPG o PNG)."); }
      // 4032 px = foto de 12 MP de un movil: antes se bajaba a 2400 y la ventana nueva
      // se pintaba con la mitad de pixeles (la deteccion ya trabaja a 1280 por su cuenta)
      const f = Math.min(1, 4032 / Math.max(img.naturalWidth, img.naturalHeight));
      const cv = document.createElement("canvas");
      cv.width = Math.round(img.naturalWidth * f); cv.height = Math.round(img.naturalHeight * f);
      const cx = cv.getContext("2d"); cx.imageSmoothingQuality = "high";
      cx.drawImage(img, 0, 0, cv.width, cv.height);
      const blob = await new Promise(ok => cv.toBlob(ok, "image/jpeg", 0.95));
      const form = new FormData(); form.append("foto", blob, "fachada.jpg");
      cargando("Detectando ventanas");
      abrirSesion(await api("/api/sesion", { metodo: "POST", form }), "Mi fachada");
    } catch (e) {
      aviso(e.message);
    } finally { cargando(null); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  }

  // =========================================================== 5. VENTANAS
  PANTALLAS.ventanas = () => {
    const F = E.foto;
    if (!F) return pestana("inicio");
    pantalla.append(h(cabecera("Elige ventanas", { paso: "2 de 3" })));
    pantalla.append(h(progreso(2)));
    const NS = "http://www.w3.org/2000/svg";
    const visor = h(`<div class="visor"><svg role="img" aria-label="Tu fachada con las ventanas encontradas"><image href="${esc(F.url)}" x="0" y="0" width="${F.ancho}" height="${F.alto}" preserveAspectRatio="none"/><g class="capa"></g></svg></div>`);
    pantalla.append(visor);
    const svg = visor.querySelector("svg"), capa = svg.querySelector(".capa");
    const barra = h(`<div class="visor-barra"><span class="num"></span><button class="enlace"></button></div>`);
    pantalla.append(barra);
    const lista = h(`<div class="lista-v"></div>`);
    pantalla.append(lista);
    const anadir = h(`<button class="boton claro ancho" style="margin-top:12px">${I.mas} Añadir otra ventana</button>`);
    pantalla.append(anadir);
    const fija = h(`<div class="accion-fija"><button class="boton"></button></div>`);
    pantalla.append(fija);
    const bVer = fija.querySelector("button");

    let escalaTrazo = 1;
    const aSvg = ev => { const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
    const extension = v => { const xs = v.quad.map(q => q[0]), ys = v.quad.map(q => q[1]); return [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)]; };

    function dibujar() {
      const vEd = E.ventanas.find(x => x.id === E.editando);
      const roi = vEd && !E.verEntera ? encuadre([vEd], F.ancho, F.alto, 0.9) : E.verEntera ? [0, 0, F.ancho, F.alto] : encuadre(E.ventanas, F.ancho, F.alto, 0.12);
      svg.setAttribute("viewBox", `${roi[0]} ${roi[1]} ${roi[2] - roi[0]} ${roi[3] - roi[1]}`);
      svg.style.aspectRatio = `${roi[2] - roi[0]} / ${roi[3] - roi[1]}`;
      escalaTrazo = Math.max(roi[2] - roi[0], roi[3] - roi[1]) / 360;
      capa.innerHTML = "";
      E.ventanas.forEach((v, i) => {
        const ed = E.editando === v.id;
        const p = document.createElementNS(NS, "polygon");
        p.setAttribute("points", v.quad.map(q => q.join(",")).join(" "));
        p.setAttribute("class", `v-forma ${ed ? "editando" : v.sel ? "sel" : "nosel"}`);
        p.setAttribute("stroke-width", escalaTrazo * (v.sel || ed ? 2.4 : 1.6));
        p.addEventListener("click", () => { if (E.editando) return; v.sel = !v.sel; refrescar(); });
        capa.append(p);
        if (v.sel && v.interior && !ed) {             // donde ira la ventana nueva: se conservan jamba y recercado
          const pi = document.createElementNS(NS, "polygon");
          pi.setAttribute("points", v.interior.map(q => q.join(",")).join(" "));
          pi.setAttribute("class", "v-interior"); pi.setAttribute("stroke-width", escalaTrazo * 1.2);
          capa.append(pi);
        }
        if (!ed) {
          const c = v.quad.reduce((a, q) => [a[0] + q[0] / 4, a[1] + q[1] / 4], [0, 0]);
          const r = Math.min(escalaTrazo * 11, extension(v)[1] * 0.22);
          const circ = document.createElementNS(NS, "circle");
          circ.setAttribute("cx", c[0]); circ.setAttribute("cy", c[1]); circ.setAttribute("r", r);
          circ.setAttribute("fill", v.sel ? "var(--luz)" : "rgba(0,0,0,.55)"); circ.style.pointerEvents = "none";
          capa.append(circ);
          const t = document.createElementNS(NS, "text");
          t.setAttribute("x", c[0]); t.setAttribute("y", c[1]); t.setAttribute("class", `v-num ${v.sel ? "sel" : ""}`);
          t.setAttribute("font-size", r * 1.15); t.setAttribute("stroke-width", 0);
          t.textContent = v.sel ? "✓" : i + 1;
          capa.append(t);
        }
      });
      if (vEd) vEd.quad.forEach((q, k) => {                  // asas para ajustar las esquinas
        const a = document.createElementNS(NS, "circle");
        a.setAttribute("cx", q[0]); a.setAttribute("cy", q[1]); a.setAttribute("r", Math.min(escalaTrazo * 9, Math.min(...extension(vEd)) * 0.14));
        a.setAttribute("class", "asa"); a.setAttribute("stroke-width", escalaTrazo * 3);
        a.addEventListener("pointerdown", ev => {
          ev.preventDefault(); a.setPointerCapture(ev.pointerId);
          // al mover esquinas a mano, el plano interior detectado ya no vale
          vEd.origen = "manual"; vEd.interior = null;
          const mover = e2 => {
            const p = aSvg(e2);
            vEd.quad[k] = [Math.max(0, Math.min(F.ancho, p.x)), Math.max(0, Math.min(F.alto, p.y))];
            a.setAttribute("cx", vEd.quad[k][0]); a.setAttribute("cy", vEd.quad[k][1]);
            capa.querySelector(".editando").setAttribute("points", vEd.quad.map(q2 => q2.join(",")).join(" "));
          };
          const soltar = () => { a.removeEventListener("pointermove", mover); a.removeEventListener("pointerup", soltar); };
          a.addEventListener("pointermove", mover); a.addEventListener("pointerup", soltar);
        });
        capa.append(a);
      });
    }

    function fila(v, i) {
      const m = medidasDe(v);
      const el = h(`<div class="fila-v ${v.sel ? "sel" : ""}">
          <button class="marcar" aria-label="${v.sel ? "Quitar" : "Elegir"} ventana ${i + 1}" aria-pressed="${v.sel}">${I.check}</button>
          <div><b>Ventana ${i + 1}</b><small>${v.ancho_mm && v.alto_mm ? `${fmt(v.ancho_mm)} × ${fmt(v.alto_mm)} mm` : v.sel ? `Unos ${fmt(m.ancho)} × ${fmt(m.alto)} mm (estimado)` : "Toca para elegirla"}</small></div>
          <div class="acciones">
            <button class="icono" data-a="ajustar" aria-label="Ajustar esquinas">${I.ajustar}</button>
            <button class="icono" data-a="medidas" aria-label="Medidas">${I.metro}</button>
            <button class="icono peligro" data-a="quitar" aria-label="Quitar de la lista">${I.papelera}</button>
          </div></div>`);
      el.querySelector(".marcar").onclick = () => { v.sel = !v.sel; refrescar(); };
      el.querySelector("div").onclick = () => { v.sel = !v.sel; refrescar(); };
      el.querySelector('[data-a="ajustar"]').onclick = () => { E.editando = v.id; v.sel = true; refrescar(); visor.scrollIntoView({ block: "center" }); };
      el.querySelector('[data-a="medidas"]').onclick = () => hojaMedidas(v, i);
      el.querySelector('[data-a="quitar"]').onclick = () => { E.ventanas = E.ventanas.filter(x => x !== v); if (E.editando === v.id) E.editando = null; refrescar(); aviso(`Ventana ${i + 1} quitada`); };
      return el;
    }

    function refrescar() {
      dibujar();
      const n = E.ventanas.filter(v => v.sel).length;
      barra.querySelector("span").textContent = E.editando ? "Arrastra las esquinas" : `${plural(E.ventanas.length, "detectada", "detectadas")} · ${plural(n, "elegida", "elegidas")}`;
      const bEnc = barra.querySelector("button");
      bEnc.textContent = E.editando ? "Listo" : E.verEntera ? "Acercar" : "Ver foto entera";
      bEnc.onclick = () => { if (E.editando) E.editando = null; else E.verEntera = !E.verEntera; refrescar(); };
      lista.innerHTML = "";
      E.ventanas.forEach((v, i) => lista.append(fila(v, i)));
      if (!E.ventanas.length) lista.append(h(`<div class="aviso-suave">No hay ventanas. Añade una y ajusta sus esquinas sobre la foto.</div>`));
      bVer.disabled = !n || !!E.editando;
      bVer.textContent = E.editando ? "Termina de ajustar la ventana" : n ? `Ver cómo queda${n > 1 ? ` en ${n} ventanas` : ""}` : "Elige al menos una ventana";
    }
    anadir.onclick = () => {
      const roi = E.verEntera ? [0, 0, F.ancho, F.alto] : encuadre(E.ventanas, F.ancho, F.alto, 0.12);
      const w = (roi[2] - roi[0]) * 0.22, hh = w * 1.2, cx = (roi[0] + roi[2]) / 2, cy = (roi[1] + roi[3]) / 2;
      const id = `m${Date.now()}`;
      E.ventanas.push({ id, origen: "manual", interior: null, sel: true, quad: [[cx - w / 2, cy - hh / 2], [cx + w / 2, cy - hh / 2], [cx + w / 2, cy + hh / 2], [cx - w / 2, cy + hh / 2]] });
      E.editando = id; refrescar(); visor.scrollIntoView({ block: "center" });
    };
    bVer.onclick = () => {
      if (!E.producto) { E.producto = CATALOGO.find(p => p.destacado) || CATALOGO[0]; E.variante = E.producto.variantes[0].id; }
      ir("resultado");
    };
    refrescar();
  };

  function hojaMedidas(v, i) {
    const otras = E.ventanas.filter(x => x.sel && x !== v).length;
    const m = medidasDe(v);
    abrirHoja(`<h3>Medidas de la ventana ${i + 1}</h3>
      <p>Mide el hueco de obra de lado a lado, sin contar el marco que hay ahora. Con tus medidas el perfil sale a escala real y el precio se afina.</p>
      <form id="f-medidas" novalidate>
        <div class="campos">
          <label class="campo">Ancho<div class="unidad"><input id="m-ancho" type="number" inputmode="numeric" min="300" max="5000" placeholder="${m.ancho}" value="${v.ancho_mm || ""}"><span>mm</span></div></label>
          <label class="campo">Alto<div class="unidad"><input id="m-alto" type="number" inputmode="numeric" min="300" max="5000" placeholder="${m.alto}" value="${v.alto_mm || ""}"><span>mm</span></div></label>
        </div>
        ${otras ? `<label class="casilla"><input id="m-todas" type="checkbox"> Usar estas medidas en las ${otras + 1} ventanas elegidas</label>` : ""}
        <p class="error" id="m-error" hidden></p>
        <div style="display:flex;gap:10px;margin-top:8px">
          <button type="button" class="boton claro" id="m-borrar" style="flex:1">Borrar</button>
          <button type="submit" class="boton" style="flex:2">Guardar medidas</button>
        </div></form>`, hoja => {
      hoja.querySelector("#m-borrar").onclick = () => { v.ancho_mm = v.alto_mm = null; cerrarHoja(); pintar(); };
      hoja.querySelector("#f-medidas").onsubmit = ev => {
        ev.preventDefault();
        const a = Number(hoja.querySelector("#m-ancho").value), b = Number(hoja.querySelector("#m-alto").value);
        const err = hoja.querySelector("#m-error");
        if (!(a >= 300 && a <= 5000 && b >= 300 && b <= 5000)) { err.textContent = "Escribe ancho y alto entre 300 y 5000 mm."; err.hidden = false; return; }
        const destino = hoja.querySelector("#m-todas")?.checked ? E.ventanas.filter(x => x.sel || x === v) : [v];
        destino.forEach(x => { x.ancho_mm = a; x.alto_mm = b; });
        cerrarHoja(); pintar(); aviso("Medidas guardadas");
      };
    });
  }

  // =========================================================== 6. RESULTADO
  const paraServidor = v => ({ id: v.id, quad: v.quad, interior: v.interior || null, origen: v.origen || "manual", ancho_mm: v.ancho_mm || null, alto_mm: v.alto_mm || null });

  PANTALLAS.resultado = () => {
    const F = E.foto, sel = E.ventanas.filter(v => v.sel);
    if (!F || !sel.length || !E.producto) return pestana("inicio");
    pantalla.append(h(cabecera("Tu fachada", { paso: "3 de 3" })));
    pantalla.append(h(progreso(3)));
    const caja = h(`<div class="caja-resultado"></div>`);
    pantalla.append(caja);
    const barra = h(`<div class="visor-barra"><span>Arrastra para comparar</span><button class="enlace"></button></div>`);
    pantalla.append(barra);
    pantalla.append(h(`<h3 class="titulo-seccion">Modelo</h3>`));
    const selProd = h(`<div class="selector-prod" role="listbox" aria-label="Modelo"></div>`);
    pantalla.append(selProd);
    pantalla.append(h(`<h3 class="titulo-seccion">Color</h3>`));
    const zonaColor = h(`<div></div>`);
    pantalla.append(zonaColor);
    const resumen = h(`<div class="resumen"></div>`);
    pantalla.append(resumen);
    const des = h(`<a class="boton claro ancho" style="margin-top:12px" target="_blank" rel="noopener" hidden>${I.descargar} Descargar imagen</a>`);
    pantalla.append(des);
    const fija = h(`<div class="accion-fija"><button class="boton claro" data-guardar>Guardar</button><button class="boton" data-pedir>Pedir presupuesto</button></div>`);
    pantalla.append(fija);
    const bGuardar = fija.querySelector("[data-guardar]"), bPedir = fija.querySelector("[data-pedir]");

    let corte = 50, turno = 0, antes = null;
    function mostrar() {
      const R = E.resultado; if (!R || !antes) return;
      const roi = E.resEntera ? [0, 0, F.ancho, F.alto] : encuadre(sel, F.ancho, F.alto, 0.18);
      const previo = caja.querySelector(".comparador");
      if (previo) corte = parseFloat(previo.style.getPropertyValue("--corte")) || corte;
      caja.innerHTML = "";
      caja.append(comparador(recortar(antes, roi, F.ancho), recortar(R.img, roi, F.ancho), { inicial: corte }));
      barra.querySelector("button").textContent = E.resEntera ? "Acercar" : "Ver foto entera";
    }
    async function componer() {
      const mio = ++turno;
      bGuardar.disabled = bPedir.disabled = true;
      cargando(sel.length > 1 ? `Colocando ${sel.length} ventanas` : "Colocando la ventana", E.foto.url);
      try {
        const r = await api("/api/render", { metodo: "POST", json: { sesion: E.sesion, variante: E.variante, ventanas: sel.map(paraServidor) } });
        // a resolucion completa: la vista de 1600 px se queda corta al acercar
        const [img, a] = await Promise.all([cargarImagen(ruta(r.descarga || r.resultado)), antes ? antes : cargarImagen(ruta(r.original_full || r.original))]);
        if (mio !== turno || !caja.isConnected) return;
        antes = a; E.resultado = { ...r, img, variante: E.variante, sesion: E.sesion, firma: firma(sel) };
        mostrar();
        des.href = ruta(r.descarga); des.setAttribute("download", `ventana-${E.variante}.jpg`); des.hidden = false;
        bGuardar.disabled = bPedir.disabled = false;
        if (r.avisos?.length) aviso(r.avisos.join(" "), 6000);
      } catch (e) {
        if (mio !== turno) return;
        if (e.estado === 404) { aviso("Esta foto ya no está en el servidor. Vuelve a subirla."); E.sesion = null; return pestana("inicio"); }
        aviso(`No se ha podido colocar la ventana. ${e.message}`, 6000);
        if (!caja.children.length) caja.append(h(`<div class="vacio">${I.nube}<b>No se ha podido generar la imagen</b><span>${esc(e.message)}</span><button class="boton claro" data-reintentar>Reintentar</button></div>`));
        const rb = caja.querySelector("[data-reintentar]"); if (rb) rb.onclick = () => { caja.innerHTML = ""; componer(); };
      } finally {
        if (mio === turno) cargando(null);
      }
    }
    function pintarResumen() {
      const est = estimacion(E.producto, sel), v = variante(E.producto, E.variante);
      resumen.innerHTML = `<small>Precio orientativo · ${plural(sel.length, "ventana", "ventanas")} · ${est.m2.toLocaleString("es-ES", { maximumFractionDigits: 1 })} m²</small>
        <span class="estimacion">${rango(est)}</span>
        <div class="detalle"><span>${esc(E.producto.nombre)} · ${esc(v.nombre)}</span><span>${est.min ? "sin IVA ni colocación" : "te lo damos en el presupuesto"}</span></div>
        ${est.reales ? "" : `<small>Calculado con medidas estimadas por la foto. <button class="enlace" data-medidas>Añade tus medidas</button> para afinarlo.</small>`}`;
      const bm = resumen.querySelector("[data-medidas]"); if (bm) bm.onclick = atras;
    }
    function pintarSelectores() {
      selProd.innerHTML = "";
      CATALOGO.forEach(p => {
        const activo = p.id === E.producto.id;
        const b = h(`<button class="mini-prod ${activo ? "activo" : ""}" role="option" aria-selected="${activo}"><span>${esc(p.nombre)}</span></button>`);
        b.prepend(lamina(p, activo ? E.variante : null));
        b.onclick = () => {
          if (activo) return;
          E.producto = p; E.variante = p.variantes[0].id; E.proyectoId = null;
          pintarSelectores(); pintarResumen(); componer();
        };
        selProd.append(b);
      });
      zonaColor.innerHTML = "";
      zonaColor.append(selectorColor(E.producto, E.variante, c => { E.variante = c; E.proyectoId = null; pintarResumen(); componer(); }));
    }
    barra.querySelector("button").onclick = () => { E.resEntera = !E.resEntera; mostrar(); };
    bGuardar.onclick = () => { guardarProyecto("guardado"); aviso("Guardado en Proyectos"); };
    bPedir.onclick = () => ir("presupuesto");
    pintarSelectores(); pintarResumen();
    if (E.resultado && E.resultado.variante === E.variante && E.resultado.sesion === E.sesion && E.resultado.firma === firma(sel)) {
      cargarImagen(ruta(E.resultado.original_full || E.resultado.original)).then(a => { antes = a; mostrar(); des.href = ruta(E.resultado.descarga); des.hidden = false; });
    } else componer();
  };
  // el resultado recuerda para que ventanas se hizo: al volver atras no se repite el render
  const firma = sel => JSON.stringify(sel.map(paraServidor));

  function miniaturaResultado() {
    const R = E.resultado; if (!R?.img) return "";
    try {
      const sel = E.ventanas.filter(v => v.sel);
      const cv = recortar(R.img, encuadre(sel, E.foto.ancho, E.foto.alto, 0.3), E.foto.ancho, 360);
      return cv.toDataURL("image/jpeg", 0.8);
    } catch { return ""; }            // imagen de otro dominio sin CORS
  }
  function guardarProyecto(estado, extra = {}) {
    const sel = E.ventanas.filter(v => v.sel), est = estimacion(E.producto, sel);
    const proyectos = guardado.leer("proyectos", []).filter(x => x.id !== E.proyectoId);
    E.proyectoId = E.proyectoId || Date.now();
    proyectos.unshift({
      id: E.proyectoId, fecha: new Date().toISOString(), modelo: E.producto.id, variante: E.variante,
      ventanas: sel.length, estimacion: [est.min, est.max], estado, imagen: miniaturaResultado(),
      sesion: E.sesion, foto: { ...E.foto }, seleccion: sel.map(paraServidor), ...extra,
    });
    if (!guardado.escribir("proyectos", proyectos.slice(0, 30))) aviso("No se ha podido guardar en este dispositivo");
  }

  // =========================================================== 7. PRESUPUESTO
  PANTALLAS.presupuesto = () => {
    const sel = E.ventanas.filter(v => v.sel), est = estimacion(E.producto, sel), v = variante(E.producto, E.variante);
    const imagen = miniaturaResultado();
    pantalla.append(h(cabecera("Pedir presupuesto")));
    pantalla.append(h(`<div class="proyecto" style="margin-top:6px">${imagen ? `<img src="${imagen}" alt="">` : "<span></span>"}
        <div><b>${esc(E.producto.nombre)}</b><small>${esc(v.nombre)} · ${plural(sel.length, "ventana", "ventanas")}</small>
        <small class="num">${rango(est)}${est.min ? " orientativo" : ""}</small></div></div>`));
    const form = h(`<form novalidate style="margin-top:18px">
        <div class="campos">
          <label class="campo entero">Nombre<input id="p-nombre" autocomplete="name" required placeholder="Nombre y apellidos"></label>
          <label class="campo">Teléfono<input id="p-tel" type="tel" autocomplete="tel" inputmode="tel" required placeholder="600 000 000"></label>
          <label class="campo">Código postal<input id="p-cp" inputmode="numeric" autocomplete="postal-code" maxlength="5" required placeholder="28001"></label>
          <label class="campo entero">Correo electrónico<small>Opcional</small><input id="p-email" type="email" autocomplete="email" placeholder="tu@correo.es"></label>
          <div class="campo entero">¿Cuándo te llamamos?
            <div class="chips" id="p-cuando" style="margin:4px 0 0;padding:0">
              <button type="button" class="chip activo" data-v="Mañanas">Mañanas</button><button type="button" class="chip" data-v="Tardes">Tardes</button><button type="button" class="chip" data-v="Me da igual">Me da igual</button>
            </div></div>
          <label class="campo entero">Comentarios<small>Opcional: persianas, accesos, plazos…</small><textarea id="p-com" rows="3"></textarea></label>
        </div>
        <label class="casilla"><input id="p-priv" type="checkbox" required> Acepto que usen mis datos y la foto para preparar el presupuesto.</label>
        <p class="error" id="p-error" hidden></p>
        <div class="accion-fija"><button type="submit" class="boton">Enviar solicitud</button></div>
      </form>`);
    pantalla.append(form);
    let cuando = "Mañanas";
    form.querySelector("#p-cuando").onclick = e => { const c = e.target.dataset.v; if (!c) return; cuando = c; form.querySelectorAll("#p-cuando .chip").forEach(x => x.classList.toggle("activo", x.dataset.v === c)); };
    form.onsubmit = async ev => {
      ev.preventDefault();
      const val = id => form.querySelector(id).value.trim(), err = form.querySelector("#p-error");
      const problemas = [];
      if (val("#p-nombre").length < 2) problemas.push("tu nombre");
      if (!/^[0-9 +]{9,15}$/.test(val("#p-tel"))) problemas.push("un teléfono válido");
      if (!/^\d{5}$/.test(val("#p-cp"))) problemas.push("el código postal (5 cifras)");
      if (val("#p-email") && !/^\S+@\S+\.\S+$/.test(val("#p-email"))) problemas.push("un correo válido");
      if (!form.querySelector("#p-priv").checked) problemas.push("aceptar el uso de tus datos");
      if (problemas.length) { err.textContent = `Falta ${problemas.join(", ")}.`; err.hidden = false; err.scrollIntoView({ block: "center" }); return; }
      err.hidden = true;
      const contacto = { nombre: val("#p-nombre"), telefono: val("#p-tel"), cp: val("#p-cp"), email: val("#p-email"), cuando, comentarios: val("#p-com") };
      const boton = form.querySelector("[type=submit]"); boton.disabled = true; boton.textContent = "Enviando…";
      try {
        const r = await api("/api/presupuesto", { metodo: "POST", json: {
          sesion: E.sesion, modelo: E.producto.id, nombre_modelo: E.producto.nombre, variante: E.variante, color: v.nombre,
          ventanas: sel.map(paraServidor), resultado: E.resultado?.descarga || null,
          estimacion: { min: est.min, max: est.max, m2: Math.round(est.m2 * 100) / 100, medidas_reales: est.reales },
          contacto,
        } });
        guardarProyecto("pedido", { referencia: r.id });
        E.pila = []; ir("confirmacion", { nombre: contacto.nombre.split(" ")[0], referencia: r.id }, { apilar: false });
      } catch (e) {
        err.textContent = `No se ha podido enviar: ${e.message}`; err.hidden = false;
        boton.disabled = false; boton.textContent = "Enviar solicitud";
      }
    };
  };

  PANTALLAS.confirmacion = ({ nombre, referencia }) => {
    pantalla.append(h(`<div class="confirmacion"><div class="sello">${I.check}</div>
        <h1>Solicitud enviada</h1>
        <p>Gracias, ${esc(nombre)}. Te llamaremos para confirmar medidas y darte el precio final.</p>
        <div class="nota-demo">Ref. ${esc(referencia)}</div></div>`));
    const fija = h(`<div class="accion-fija"><button class="boton claro">Inicio</button><button class="boton">Ver mis proyectos</button></div>`);
    fija.children[0].onclick = () => pestana("inicio");
    fija.children[1].onclick = () => pestana("proyectos");
    pantalla.append(fija);
  };

  // =========================================================== 8. PROYECTOS
  PANTALLAS.proyectos = () => {
    pantalla.append(h(`<h1 class="titulo-pagina">Proyectos</h1>`));
    const proyectos = guardado.leer("proyectos", []).filter(pr => pr.sesion);   // los de la version sin servidor no se pueden abrir
    if (!proyectos.length) {
      pantalla.append(h(`<div class="vacio">${I.carpeta}<b>Aún no tienes proyectos</b><span>Cuando pruebes una ventana en tu fachada, guárdala aquí para compararla o pedir presupuesto.</span></div>`));
      const b = h(`<button class="boton ancho">${I.camara} Probar en mi fachada</button>`);
      b.onclick = () => empezarPrueba(); pantalla.append(b);
      return;
    }
    const lista = h(`<div style="display:grid;gap:12px;margin-top:4px"></div>`);
    proyectos.forEach(pr => lista.append(filaProyecto(pr)));
    pantalla.append(lista);
  };
  function filaProyecto(pr) {
    const p = modelo(pr.modelo);
    const nombre = p ? p.nombre : pr.modelo, color = p ? variante(p, pr.variante).nombre : "";
    const fecha = new Date(pr.fecha).toLocaleDateString("es-ES", { day: "numeric", month: "short" });
    const el = h(`<button class="proyecto"><img src="${pr.imagen || ""}" alt="">
        <div><b>${esc(nombre)}</b><small>${esc(color)} · ${plural(pr.ventanas, "ventana", "ventanas")} · ${fecha}</small>
        <small class="num">${rango({ min: pr.estimacion[0], max: pr.estimacion[1] })}</small>
        <span class="estado ${pr.estado === "pedido" ? "pedido" : ""}">${pr.estado === "pedido" ? "Presupuesto pedido" : "Guardado"}</span></div></button>`);
    el.onclick = () => abrirProyecto(pr, p, nombre, color);
    return el;
  }
  function abrirProyecto(pr, p, nombre, color) {
    abrirHoja(`<h3>${esc(nombre)}</h3><p>${esc(color)} · ${plural(pr.ventanas, "ventana", "ventanas")}${pr.referencia ? ` · ref. ${esc(pr.referencia)}` : ""}</p>
      ${pr.imagen ? `<img src="${pr.imagen}" alt="" style="border-radius:14px;width:100%;margin-bottom:14px">` : ""}
      <div style="display:grid;gap:10px">
        ${p ? '<button class="boton" data-abrir>Abrir y seguir probando</button>' : ""}
        <button class="boton claro" data-borrar>Eliminar proyecto</button></div>`, hoja => {
      const ab = hoja.querySelector("[data-abrir]");
      if (ab) ab.onclick = () => {
        E.sesion = pr.sesion; E.foto = pr.foto; E.resultado = null;
        E.ventanas = pr.seleccion.map(v => ({ ...v, sel: true }));
        E.producto = p; E.variante = variante(p, pr.variante).id; E.proyectoId = pr.id;
        E.pila = [{ nombre: "proyectos", datos: {} }]; E.actual = { nombre: "resultado", datos: {} };
        pintar();
      };
      hoja.querySelector("[data-borrar]").onclick = () => {
        guardado.escribir("proyectos", guardado.leer("proyectos", []).filter(x => x.id !== pr.id));
        cerrarHoja(); pintar(); aviso("Proyecto eliminado");
      };
    });
  }

  // =========================================================== sin conexion con el servidor
  PANTALLAS.error = ({ mensaje }) => {
    const el = h(`<div class="vacio" style="padding-top:80px">${I.nube}<b>No podemos conectar</b><span>${esc(mensaje)}</span><button class="boton">Reintentar</button></div>`);
    el.querySelector("button").onclick = arrancar;
    pantalla.append(el);
  };

  // =========================================================== arranque
  async function arrancar() {
    cargando("Cargando", null);
    try {
      const [cat, ejs] = await Promise.all([api("/api/catalogo"), fetch("ejemplos.json").then(r => (r.ok ? r.json() : [])).catch(() => [])]);
      CATALOGO = cat.filter(p => p.variantes?.length); EJEMPLOS = ejs;
      if (!CATALOGO.length) throw new Error("El catálogo está vacío: revisa CATALOGO_DIR en el servidor.");
      E.pila = []; E.actual = { nombre: "inicio", datos: {} };
    } catch (e) {
      E.pila = []; E.actual = { nombre: "error", datos: { mensaje: e.message } };
    } finally { cargando(null); }
    pintar();
  }

  document.addEventListener("keydown", e => { if (e.key === "Escape") cerrarHoja(); });
  const enMarco = (() => { try { return window.self !== window.top; } catch { return true; } })();
  if (!enMarco && "serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
  arrancar();
})();