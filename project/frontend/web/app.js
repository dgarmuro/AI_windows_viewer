/* Vano — app del cliente (sin backend: todo ocurre en el movil).
 * Puntos de conexion con el backend en el futuro, marcados con  [BACKEND] :
 *   - deteccion de ventanas en la foto del cliente
 *   - composicion realista (LaMa, luz, oclusores) en lugar de Motor.componer
 *   - envio de la solicitud de presupuesto
 */
(function () {
  "use strict";

  // =========================================================== estado
  const E = {
    pila: [], actual: null,
    producto: CATALOGO[0], color: CATALOGO[0].colores[0],
    foto: null,          // {fuente, url, ancho, alto, ejemplo, nombre}
    ventanas: [],        // {id, quad, sel, ancho_mm, alto_mm}
    editando: null, verEntera: false, resEntera: false,
    filtro: "Todas", busqueda: "",
  };
  const enMarco = (() => { try { return window.self !== window.top; } catch { return true; } })();
  const $ = (s, r = document) => r.querySelector(s);
  const pantalla = $("#pantalla");
  const fmt = n => n.toLocaleString("es-ES", { maximumFractionDigits: 0 });
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const h = html => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };

  // ---------------------------------------------------------- almacenamiento local (puede fallar: modo privado)
  const guardado = {
    leer(k, def) { try { const v = localStorage.getItem("vano." + k); return v ? JSON.parse(v) : def; } catch { return def; } },
    escribir(k, v) { try { localStorage.setItem("vano." + k, JSON.stringify(v)); return true; } catch { return false; } },
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
  };

  // ---------------------------------------------------------- utilidades de interfaz
  let _toast;
  function aviso(texto) {
    const t = $("#toast"); t.textContent = texto; t.hidden = false;
    clearTimeout(_toast); _toast = setTimeout(() => (t.hidden = true), 3200);
  }
  function cargando(texto) { $("#cargando").hidden = !texto; if (texto) $("#cargando-texto").textContent = texto; }
  const espera = ms => new Promise(r => setTimeout(r, ms));

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
  function atras() {
    const prev = E.pila.pop();
    E.actual = prev || { nombre: "inicio", datos: {} };
    pintar();
  }
  function pestana(nombre) { E.pila = []; E.actual = { nombre, datos: {} }; pintar(); }
  function pintar() {
    cerrarHoja();
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

  // ---------------------------------------------------------- piezas reutilizables
  function lamina(prod, color, w = 300, hgt = 360) {
    const cv = Motor.miniatura(prod, color, w, hgt);
    cv.setAttribute("role", "img"); cv.setAttribute("aria-label", `${prod.nombre} en ${COLORES[color].nombre}`);
    return cv;
  }
  function tarjetaProducto(p) {
    const el = h(`<button class="tarjeta">
        <div class="lamina">${p.destacado ? '<span class="etiqueta">Más pedida</span>' : ""}</div>
        <div class="info"><span class="nombre">${esc(p.nombre)}</span><span class="sub">${esc(p.material)} · ${esc(p.apertura)}</span>
          <span class="precio">desde ${fmt(p.precio_m2)} €/m²</span>
          <span class="puntos">${p.colores.map(c => `<i style="background:${COLORES[c].hex}" title="${esc(COLORES[c].nombre)}"></i>`).join("")}</span></div>
      </button>`);
    el.querySelector(".lamina").appendChild(lamina(p, p.colores[0]));
    el.onclick = () => ir("ficha", { id: p.id });
    return el;
  }

  // Comparador antes/despues con tirador que se arrastra
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
      const x = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
      el.style.setProperty("--corte", `${x * 100}%`);
    };
    el.addEventListener("pointerdown", ev => { el.setPointerCapture(ev.pointerId); mover(ev); });
    el.addEventListener("pointermove", ev => { if (el.hasPointerCapture(ev.pointerId)) mover(ev); });
    el.tabIndex = 0;
    el.addEventListener("keydown", ev => {
      const v = parseFloat(getComputedStyle(el).getPropertyValue("--corte")) || 50;
      if (ev.key === "ArrowLeft") el.style.setProperty("--corte", `${Math.max(0, v - 5)}%`);
      if (ev.key === "ArrowRight") el.style.setProperty("--corte", `${Math.min(100, v + 5)}%`);
    });
    return el;
  }

  function encuadre(ventanas, ancho, alto, margen) {
    if (!ventanas.length) return [0, 0, ancho, alto];
    const xs = ventanas.flatMap(v => v.quad.map(p => p[0])), ys = ventanas.flatMap(v => v.quad.map(p => p[1]));
    const m = margen * Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 0.22 * ancho);
    const x0 = Math.max(0, Math.min(...xs) - m), x1 = Math.min(ancho, Math.max(...xs) + m);
    const y0 = Math.max(0, Math.min(...ys) - m), y1 = Math.min(alto, Math.max(...ys) + m);
    return [x0, y0, x1, y1];
  }
  function recortar(fuente, [x0, y0, x1, y1], escala = 1, maxAncho = 1100) {
    const w = (x1 - x0) * escala, hh = (y1 - y0) * escala, f = Math.min(1, maxAncho / w) * 2 > 1 ? Math.min(2, maxAncho / w) : 1;
    const cv = document.createElement("canvas");
    cv.width = Math.round(w * f); cv.height = Math.round(hh * f);
    cv.getContext("2d").drawImage(fuente, x0 * escala, y0 * escala, w, hh, 0, 0, cv.width, cv.height);
    return cv;
  }
  async function cargarImagen(src) { const i = new Image(); i.src = src; await i.decode(); return i; }

  // ---------------------------------------------------------- calculo de presupuesto orientativo
  function medidasDe(v) {
    const [a, b, c, d] = v.quad;
    const wq = (Math.hypot(b[0] - a[0], b[1] - a[1]) + Math.hypot(c[0] - d[0], c[1] - d[1])) / 2;
    const hq = (Math.hypot(d[0] - a[0], d[1] - a[1]) + Math.hypot(c[0] - b[0], c[1] - b[1])) / 2;
    const ancho = v.ancho_mm || 1200, alto = v.alto_mm || Math.round((v.ancho_mm || 1200) * hq / wq / 10) * 10;
    return { ancho, alto, reales: !!(v.ancho_mm && v.alto_mm) };
  }
  function estimacion(prod, ventanas) {
    let m2 = 0, reales = true;
    for (const v of ventanas) { const m = medidasDe(v); m2 += (m.ancho * m.alto) / 1e6; reales = reales && m.reales; }
    const base = Math.max(1, m2) * prod.precio_m2;
    return { min: Math.round(base * 0.9 / 10) * 10, max: Math.round(base * 1.15 / 10) * 10, m2, reales };
  }

  // =========================================================== 1. INICIO
  PANTALLAS.inicio = () => {
    const ej = EJEMPLOS[0], destacada = CATALOGO.find(p => p.id === "clasica") || CATALOGO[0];
    const colorHeroe = destacada.colores.includes("verde") ? "verde" : destacada.colores[0];
    pantalla.append(h(`<div class="marca"><b>vano<i>.</i></b><span>Ventanas a medida</span></div>`));
    pantalla.append(h(`<h1 class="titular">Mira tu fachada con ventanas nuevas antes de cambiarlas.</h1>`));
    pantalla.append(h(`<p class="entradilla">Haz una foto, elige el modelo y el color, y compara al momento cómo queda.</p>`));
    const heroe = h(`<div class="heroe"><div class="heroe-pie"><span>${esc(destacada.nombre)} · ${esc(COLORES[colorHeroe].nombre)}</span><button class="enlace" data-probar>Probar en mi fachada</button></div></div>`);
    pantalla.append(heroe);
    heroe.querySelector("[data-probar]").onclick = () => empezarPrueba();
    cargarImagen(ej.imagen).then(img => {
      const ventanas = ej.ventanas.slice(0, 4).map(q => ({ quad: q }));
      const res = Motor.componer(img, ventanas, destacada, colorHeroe);
      const roi = encuadre(ventanas, ej.ancho, ej.alto, 0.12);
      const esc_ = res.width / ej.ancho;
      heroe.prepend(comparador(recortar(img, roi), recortar(res, roi, esc_), { inicial: 42 }));
    });

    pantalla.append(h(`<section class="bloque"><h3>Cómo funciona</h3><ol class="pasos">
        <li><div><b>Elige un modelo</b><span>Material, apertura y color.</span></div></li>
        <li><div><b>Haz una foto de tu fachada</b><span>Detectamos las ventanas y eliges en cuáles probar.</span></div></li>
        <li><div><b>Compara y pide presupuesto</b><span>Con tus medidas, el precio orientativo se ajusta.</span></div></li>
      </ol></section>`));
    const bloque = h(`<section class="bloque"><h3>Modelos <button data-todos>Ver todos</button></h3><div class="carrusel"></div></section>`);
    CATALOGO.filter(p => p.destacado).forEach(p => bloque.querySelector(".carrusel").append(tarjetaProducto(p)));
    bloque.querySelector("[data-todos]").onclick = () => pestana("catalogo");
    pantalla.append(bloque);
    const fija = h(`<div class="accion-fija"><button class="boton">${I.camara} Probar en mi fachada</button></div>`);
    fija.querySelector("button").onclick = () => empezarPrueba();
    pantalla.append(fija);
  };

  // =========================================================== 2. CATALOGO
  PANTALLAS.catalogo = () => {
    pantalla.append(h(cabecera("Ventanas", { atras: false })));
    const buscador = h(`<label class="buscador">${I.buscar}<input id="buscar" type="search" placeholder="Buscar modelo, material o apertura" value="${esc(E.busqueda)}" aria-label="Buscar"></label>`);
    pantalla.append(buscador);
    const filtros = ["Todas", "PVC", "Aluminio", "Madera", "Guardadas"];
    const chips = h(`<div class="chips" role="tablist">${filtros.map(f => `<button class="chip ${E.filtro === f ? "activo" : ""}" data-f="${f}">${f}</button>`).join("")}</div>`);
    pantalla.append(chips);
    const rejilla = h(`<div class="rejilla"></div>`);
    pantalla.append(rejilla);
    function listar() {
      rejilla.innerHTML = "";
      const q = E.busqueda.trim().toLowerCase();
      const lista = CATALOGO.filter(p =>
        (E.filtro === "Todas" || p.material === E.filtro || (E.filtro === "Guardadas" && favoritos.has(p.id))) &&
        (!q || `${p.nombre} ${p.material} ${p.apertura}`.toLowerCase().includes(q)));
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
  PANTALLAS.ficha = ({ id }) => {
    const p = CATALOGO.find(x => x.id === id);
    let color = E.producto.id === p.id ? E.color : p.colores[0];
    const fav = () => favoritos.has(p.id);
    pantalla.append(h(cabecera("", { derecha: `<button class="redondo ${fav() ? "activo" : ""}" data-fav aria-label="Guardar modelo" aria-pressed="${fav()}">${I.corazon}</button>` })));
    const escap = h(`<div class="escaparate"></div>`);
    pantalla.append(escap);
    const pintarLamina = () => { escap.innerHTML = ""; escap.append(lamina(p, color, 520, 620)); };
    pintarLamina();
    pantalla.append(h(`<div class="ficha-cab"><span class="linea">${esc(p.material)} · ${esc(p.apertura)}</span><h1>${esc(p.nombre)}</h1><p>${esc(p.lema)}</p></div>`));
    const colores = h(`<div><div class="colores" role="radiogroup" aria-label="Color">${p.colores.map(c =>
      `<button class="color ${c === color ? "activo" : ""}" role="radio" aria-checked="${c === color}" data-c="${c}" style="background:${COLORES[c].hex}" aria-label="${esc(COLORES[c].nombre)}"></button>`).join("")}</div>
      <p class="color-nombre"></p></div>`);
    pantalla.append(colores);
    const nombreColor = () => (colores.querySelector(".color-nombre").innerHTML = `<b>${esc(COLORES[color].nombre)}</b> · ${esc(COLORES[color].codigo)}`);
    nombreColor();
    colores.onclick = e => {
      const c = e.target.dataset.c; if (!c) return; color = c;
      colores.querySelectorAll(".color").forEach(b => { b.classList.toggle("activo", b.dataset.c === c); b.setAttribute("aria-checked", b.dataset.c === c); });
      nombreColor(); pintarLamina();
    };
    const f = p.ficha;
    pantalla.append(h(`<div class="cifras">
        <div><b>${esc(f["Transmitancia Uw"].split(" ")[0])}</b><span>Uw · W/m²K</span></div>
        <div><b>${esc(f["Aislamiento acústico"].split(" ")[0])}</b><span>dB de aislamiento</span></div>
        <div><b>${esc((f.Garantía || "").split(" ")[0])}</b><span>años de garantía</span></div></div>`));
    pantalla.append(h(`<dl class="especificaciones">${Object.entries(f).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`));
    pantalla.append(h(`<div class="precio-ficha"><b>desde ${fmt(p.precio_m2)} €/m²</b><span>sin IVA ni colocación</span></div>`));
    const fija = h(`<div class="accion-fija"><button class="boton">${I.camara} Probar en mi fachada</button></div>`);
    fija.querySelector("button").onclick = () => { E.producto = p; E.color = color; E.foto && E.ventanas.some(v => v.sel) ? ir("resultado") : empezarPrueba(false); };
    if (E.foto && E.ventanas.some(v => v.sel)) fija.querySelector("button").innerHTML = `${I.camara} Ver en mi fachada`;
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
  function empezarPrueba(desdeInicio = true) {
    if (desdeInicio && E.producto == null) E.producto = CATALOGO[0];
    ir("foto");
  }
  PANTALLAS.foto = () => {
    pantalla.append(h(cabecera("Tu fachada", { paso: "1 de 3" })));
    pantalla.append(h(progreso(1)));
    const opc = h(`<div class="opciones-foto">
        <label class="opcion principal" for="f-camara">${I.camara}<div><b>Hacer una foto</b><small>Con la cámara del móvil</small></div></label>
        <label class="opcion" for="f-galeria">${I.galeria}<div><b>Elegir de la galería</b><small>Una foto que ya tengas</small></div></label>
        <input id="f-camara" class="oculto" type="file" accept="image/*" capture="environment">
        <input id="f-galeria" class="oculto" type="file" accept="image/*">
      </div>`);
    pantalla.append(opc);
    opc.querySelectorAll("input").forEach(i => (i.onchange = e => e.target.files[0] && usarArchivo(e.target.files[0])));
    pantalla.append(h(`<h3 class="titulo-seccion">Para que salga bien</h3>`));
    pantalla.append(h(`<ul class="consejos"><li>Ponte enfrente de la ventana, lo más de frente posible.</li><li>Con luz de día y sin contraluz.</li><li>Que se vean las ventanas enteras, sin cortes.</li></ul>`));
    pantalla.append(h(`<h3 class="titulo-seccion">O prueba con un ejemplo</h3>`));
    const ejs = h(`<div class="ejemplos">${EJEMPLOS.map(e => `<button class="ejemplo" data-e="${e.id}"><img src="${e.imagen}" alt="" loading="lazy"><div><b>${esc(e.nombre)}</b><span>${esc(e.descripcion)}</span></div></button>`).join("")}</div>`);
    ejs.onclick = e => { const b = e.target.closest("[data-e]"); b && usarEjemplo(b.dataset.e); };
    pantalla.append(ejs);
  };

  async function usarEjemplo(id) {
    const ej = EJEMPLOS.find(e => e.id === id);
    cargando("Buscando las ventanas de la foto…");
    try {
      const img = await cargarImagen(ej.imagen);
      await espera(1300);                                         // [BACKEND] aqui iria la deteccion real
      E.foto = { fuente: img, url: ej.imagen, ancho: ej.ancho, alto: ej.alto, ejemplo: id, nombre: ej.nombre };
      E.ventanas = ej.ventanas.map((q, i) => ({ id: `v${i}`, quad: q, sel: false }));
      E.editando = null; E.verEntera = false; E.proyectoId = null;
      ir("ventanas");
      aviso(E.ventanas.length === 1 ? "1 ventana encontrada. Tócala para elegirla." : `${E.ventanas.length} ventanas encontradas. Toca las que quieras cambiar.`);
    } finally { cargando(null); }
  }

  async function usarArchivo(fichero) {
    cargando("Preparando tu foto…");
    try {
      const url = URL.createObjectURL(fichero);
      const img = await cargarImagen(url);
      const f = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
      const cv = document.createElement("canvas");
      cv.width = Math.round(img.naturalWidth * f); cv.height = Math.round(img.naturalHeight * f);
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
      URL.revokeObjectURL(url);
      cargando("Buscando las ventanas de la foto…");
      await espera(1100);                                         // [BACKEND] deteccion real
      E.foto = { fuente: cv, url: cv.toDataURL("image/jpeg", 0.88), ancho: cv.width, alto: cv.height, ejemplo: null, nombre: "Mi fachada" };
      // Sin backend no hay deteccion: se coloca un marco en el centro para ajustarlo
      const w = cv.width * 0.3, hh = w * 1.15, cx = cv.width / 2, cy = cv.height / 2;
      E.ventanas = [{ id: "v0", quad: [[cx - w / 2, cy - hh / 2], [cx + w / 2, cy - hh / 2], [cx + w / 2, cy + hh / 2], [cx - w / 2, cy + hh / 2]], sel: true }];
      E.editando = "v0"; E.verEntera = true; E.proyectoId = null;
      ir("ventanas");
      aviso("Arrastra las 4 esquinas del marco hasta las de tu ventana.");
    } catch {
      aviso("No hemos podido abrir esa imagen. Prueba con otra foto.");
    } finally { cargando(null); }
  }

  // =========================================================== 5. VENTANAS
  PANTALLAS.ventanas = () => {
    const F = E.foto;
    if (!F) return pestana("inicio");
    pantalla.append(h(cabecera("Elige ventanas", { paso: "2 de 3" })));
    pantalla.append(h(progreso(2)));
    const NS = "http://www.w3.org/2000/svg";
    const visor = h(`<div class="visor"><svg role="img" aria-label="Tu fachada con las ventanas encontradas"><image href="${F.url}" x="0" y="0" width="${F.ancho}" height="${F.alto}"/><g class="capa"></g></svg></div>`);
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

    const ladoMin = v => Math.min(Math.max(...v.quad.map(q => q[0])) - Math.min(...v.quad.map(q => q[0])), Math.max(...v.quad.map(q => q[1])) - Math.min(...v.quad.map(q => q[1])));
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
        const c = v.quad.reduce((a, q) => [a[0] + q[0] / 4, a[1] + q[1] / 4], [0, 0]);
        const alto = Math.max(...v.quad.map(q => q[1])) - Math.min(...v.quad.map(q => q[1]));
        const r = Math.min(escalaTrazo * 11, alto * 0.22);
        if (!ed) {
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
      // asas para ajustar las esquinas
      const v = E.ventanas.find(x => x.id === E.editando);
      if (v) v.quad.forEach((q, k) => {
        const a = document.createElementNS(NS, "circle");
        a.setAttribute("cx", q[0]); a.setAttribute("cy", q[1]); a.setAttribute("r", Math.min(escalaTrazo * 9, ladoMin(v) * 0.14));
        a.setAttribute("class", "asa"); a.setAttribute("stroke-width", escalaTrazo * 3);
        a.addEventListener("pointerdown", ev => {
          ev.preventDefault(); a.setPointerCapture(ev.pointerId);
          const mover = e2 => { const p = aSvg(e2); v.quad[k] = [Math.max(0, Math.min(F.ancho, p.x)), Math.max(0, Math.min(F.alto, p.y))];
            a.setAttribute("cx", v.quad[k][0]); a.setAttribute("cy", v.quad[k][1]);
            capa.querySelector(".editando").setAttribute("points", v.quad.map(q2 => q2.join(",")).join(" ")); };
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
      barra.querySelector("span").textContent = E.editando ? "Arrastra las esquinas blancas" : `${E.ventanas.length} ${E.ventanas.length === 1 ? "ventana" : "ventanas"} · ${n} ${n === 1 ? "elegida" : "elegidas"}`;
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
      E.ventanas.push({ id, quad: [[cx - w / 2, cy - hh / 2], [cx + w / 2, cy - hh / 2], [cx + w / 2, cy + hh / 2], [cx - w / 2, cy + hh / 2]], sel: true });
      E.editando = id; refrescar(); visor.scrollIntoView({ block: "center" });
    };
    bVer.onclick = () => ir("resultado");
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
  PANTALLAS.resultado = () => {
    const F = E.foto, sel = E.ventanas.filter(v => v.sel);
    if (!F || !sel.length) return pestana("inicio");
    pantalla.append(h(cabecera("Tu fachada", { paso: "3 de 3" })));
    pantalla.append(h(progreso(3)));
    const caja = h(`<div></div>`);
    pantalla.append(caja);
    const barra = h(`<div class="visor-barra"><span>Arrastra para comparar</span><button class="enlace"></button></div>`);
    pantalla.append(barra);
    pantalla.append(h(`<h3 class="titulo-seccion">Modelo</h3>`));
    const selProd = h(`<div class="selector-prod" role="listbox" aria-label="Modelo"></div>`);
    pantalla.append(selProd);
    pantalla.append(h(`<h3 class="titulo-seccion">Color</h3>`));
    const colores = h(`<div><div class="colores" role="radiogroup" aria-label="Color"></div><p class="color-nombre"></p></div>`);
    pantalla.append(colores);
    const resumen = h(`<div class="resumen"></div>`);
    pantalla.append(resumen);
    if (!enMarco) {
      const des = h(`<button class="boton claro ancho" style="margin-top:12px">${I.descargar} Descargar imagen</button>`);
      des.onclick = () => ultimo && ultimo.toBlob(b => { const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `vano-${E.producto.id}.jpg`; a.click(); }, "image/jpeg", 0.92);
      pantalla.append(des);
    }
    const fija = h(`<div class="accion-fija"><button class="boton claro" data-guardar>Guardar</button><button class="boton" data-pedir>Pedir presupuesto</button></div>`);
    pantalla.append(fija);

    let ultimo = null, corte = 50;
    function componer() {
      const res = Motor.componer(F.fuente, sel, E.producto, E.color);   // [BACKEND] /api/render
      ultimo = res;
      const roi = E.resEntera ? [0, 0, F.ancho, F.alto] : encuadre(sel, F.ancho, F.alto, 0.18);
      const previo = caja.querySelector(".comparador");
      if (previo) corte = parseFloat(previo.style.getPropertyValue("--corte")) || corte;
      caja.innerHTML = "";
      caja.append(comparador(recortar(F.fuente, roi), recortar(res, roi, res.width / F.ancho), { inicial: corte }));
      barra.querySelector("button").textContent = E.resEntera ? "Acercar" : "Ver foto entera";
      const est = estimacion(E.producto, sel);
      resumen.innerHTML = `<small>Precio orientativo · ${sel.length} ${sel.length === 1 ? "ventana" : "ventanas"} · ${est.m2.toLocaleString("es-ES", { maximumFractionDigits: 1 })} m²</small>
        <span class="estimacion">${fmt(est.min)} – ${fmt(est.max)} €</span>
        <div class="detalle"><span>${esc(E.producto.nombre)} · ${esc(COLORES[E.color].nombre)}</span><span>sin IVA ni colocación</span></div>
        ${est.reales ? "" : `<small>Calculado con medidas estimadas por la foto. <button class="enlace" data-medidas>Añade tus medidas</button> para afinarlo.</small>`}`;
      const bm = resumen.querySelector("[data-medidas]"); if (bm) bm.onclick = atras;
    }
    function pintarSelectores() {
      selProd.innerHTML = "";
      CATALOGO.forEach(p => {
        const b = h(`<button class="mini-prod ${p.id === E.producto.id ? "activo" : ""}" role="option" aria-selected="${p.id === E.producto.id}"><span>${esc(p.nombre)}</span></button>`);
        b.prepend(lamina(p, p.colores.includes(E.color) ? E.color : p.colores[0], 92, 112));
        b.onclick = () => { if (E.producto !== p) E.proyectoId = null; E.producto = p; if (!p.colores.includes(E.color)) E.color = p.colores[0]; pintarSelectores(); componer(); };
        selProd.append(b);
      });
      const cc = colores.querySelector(".colores");
      cc.innerHTML = E.producto.colores.map(c => `<button class="color ${c === E.color ? "activo" : ""}" role="radio" aria-checked="${c === E.color}" data-c="${c}" style="background:${COLORES[c].hex}" aria-label="${esc(COLORES[c].nombre)}"></button>`).join("");
      cc.onclick = e => { const c = e.target.dataset.c; if (!c) return; E.color = c; pintarSelectores(); componer(); };
      colores.querySelector(".color-nombre").innerHTML = `<b>${esc(COLORES[E.color].nombre)}</b> · ${esc(COLORES[E.color].codigo)}`;
    }
    barra.querySelector("button").onclick = () => { E.resEntera = !E.resEntera; componer(); };
    fija.querySelector("[data-guardar]").onclick = () => { guardarProyecto(ultimo, "guardado"); aviso("Guardado en Proyectos"); };
    fija.querySelector("[data-pedir]").onclick = () => ir("presupuesto", { imagen: miniaturaResultado(ultimo, sel) });
    pintarSelectores();
    componer();
  };

  function miniaturaResultado(res, sel) {
    if (!res) return "";
    const roi = encuadre(sel, E.foto.ancho, E.foto.alto, 0.3);
    const cv = recortar(res, roi, res.width / E.foto.ancho, 360);
    const f = Math.min(1, 360 / cv.width), t = document.createElement("canvas");
    t.width = Math.round(cv.width * f); t.height = Math.round(cv.height * f);
    t.getContext("2d").drawImage(cv, 0, 0, t.width, t.height);
    return t.toDataURL("image/jpeg", 0.8);
  }
  function guardarProyecto(res, estado, contacto = null) {
    const sel = E.ventanas.filter(v => v.sel), est = estimacion(E.producto, sel);
    const proyectos = guardado.leer("proyectos", []).filter(x => x.id !== E.proyectoId);
    E.proyectoId = E.proyectoId || Date.now();
    proyectos.unshift({
      id: E.proyectoId, fecha: new Date().toISOString(), producto: E.producto.id, color: E.color,
      ventanas: sel.length, estimacion: [est.min, est.max], estado, imagen: miniaturaResultado(res, sel),
      ejemplo: E.foto.ejemplo, quads: E.foto.ejemplo ? sel.map(v => ({ quad: v.quad, ancho_mm: v.ancho_mm, alto_mm: v.alto_mm })) : null,
      contacto,
    });
    if (!guardado.escribir("proyectos", proyectos.slice(0, 30))) aviso("No se ha podido guardar en este dispositivo");
  }

  // =========================================================== 7. PRESUPUESTO
  PANTALLAS.presupuesto = ({ imagen }) => {
    const sel = E.ventanas.filter(v => v.sel), est = estimacion(E.producto, sel);
    pantalla.append(h(cabecera("Pedir presupuesto")));
    pantalla.append(h(`<div class="proyecto" style="margin-top:6px">${imagen ? `<img src="${imagen}" alt="">` : "<span></span>"}
        <div><b>${esc(E.producto.nombre)}</b><small>${esc(COLORES[E.color].nombre)} · ${sel.length} ${sel.length === 1 ? "ventana" : "ventanas"}</small>
        <small class="num">${fmt(est.min)} – ${fmt(est.max)} € orientativo</small></div></div>`));
    const form = h(`<form id="f-presupuesto" novalidate style="margin-top:18px">
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
    form.querySelector("#p-cuando").onclick = e => { const v = e.target.dataset.v; if (!v) return; cuando = v; form.querySelectorAll("#p-cuando .chip").forEach(c => c.classList.toggle("activo", c.dataset.v === v)); };
    form.onsubmit = ev => {
      ev.preventDefault();
      const val = id => form.querySelector(id).value.trim(), err = form.querySelector("#p-error");
      const problemas = [];
      if (val("#p-nombre").length < 2) problemas.push("tu nombre");
      if (!/^[0-9 +]{9,15}$/.test(val("#p-tel"))) problemas.push("un teléfono válido");
      if (!/^\d{5}$/.test(val("#p-cp"))) problemas.push("el código postal (5 cifras)");
      if (val("#p-email") && !/^\S+@\S+\.\S+$/.test(val("#p-email"))) problemas.push("un correo válido");
      if (!form.querySelector("#p-priv").checked) problemas.push("aceptar el uso de tus datos");
      if (problemas.length) { err.textContent = `Falta ${problemas.join(", ")}.`; err.hidden = false; err.scrollIntoView({ block: "center" }); return; }
      // [BACKEND] aqui se enviaria la solicitud con la foto, las ventanas y las medidas
      const sel2 = E.ventanas.filter(v => v.sel);
      const res = Motor.componer(E.foto.fuente, sel2, E.producto, E.color, { lado: 900 });
      guardarProyecto(res, "pedido", { nombre: val("#p-nombre"), telefono: val("#p-tel"), cp: val("#p-cp"), email: val("#p-email"), cuando, comentarios: val("#p-com") });
      E.pila = []; ir("confirmacion", { nombre: val("#p-nombre").split(" ")[0] }, { apilar: false });
    };
  };

  PANTALLAS.confirmacion = ({ nombre }) => {
    pantalla.append(h(`<div class="confirmacion"><div class="sello">${I.check}</div>
        <h1>Solicitud lista, ${esc(nombre)}</h1>
        <p>Un asesor revisará tu fachada y las ventanas elegidas, y te llamará para confirmar medidas antes de darte el precio final.</p>
        <div class="nota-demo">Versión de demostración: la solicitud se guarda en este dispositivo, todavía no se envía a la empresa.</div></div>`));
    const fija = h(`<div class="accion-fija"><button class="boton claro">Inicio</button><button class="boton">Ver mis proyectos</button></div>`);
    fija.children[0].onclick = () => pestana("inicio");
    fija.children[1].onclick = () => pestana("proyectos");
    pantalla.append(fija);
  };

  // =========================================================== 8. PROYECTOS
  PANTALLAS.proyectos = () => {
    pantalla.append(h(cabecera("Mis proyectos", { atras: false })));
    const proyectos = guardado.leer("proyectos", []);
    if (!proyectos.length) {
      pantalla.append(h(`<div class="vacio">${I.carpeta}<b>Aún no tienes proyectos</b><span>Cuando pruebes una ventana en tu fachada, guárdala aquí para compararla o pedir presupuesto.</span></div>`));
      const b = h(`<button class="boton ancho">${I.camara} Probar en mi fachada</button>`);
      b.onclick = () => empezarPrueba(); pantalla.append(b);
      return;
    }
    const lista = h(`<div style="display:grid;gap:12px;margin-top:4px"></div>`);
    proyectos.forEach(pr => {
      const p = CATALOGO.find(x => x.id === pr.producto) || CATALOGO[0];
      const fecha = new Date(pr.fecha).toLocaleDateString("es-ES", { day: "numeric", month: "short" });
      const el = h(`<button class="proyecto"><img src="${pr.imagen || ""}" alt="">
          <div><b>${esc(p.nombre)}</b><small>${esc(COLORES[pr.color]?.nombre || "")} · ${pr.ventanas} ${pr.ventanas === 1 ? "ventana" : "ventanas"} · ${fecha}</small>
          <small class="num">${fmt(pr.estimacion[0])} – ${fmt(pr.estimacion[1])} €</small>
          <span class="estado ${pr.estado === "pedido" ? "pedido" : ""}">${pr.estado === "pedido" ? "Presupuesto pedido" : "Guardado"}</span></div></button>`);
      el.onclick = () => abrirProyecto(pr, p);
      lista.append(el);
    });
    pantalla.append(lista);
  };
  function abrirProyecto(pr, p) {
    abrirHoja(`<h3>${esc(p.nombre)}</h3><p>${esc(COLORES[pr.color]?.nombre || "")} · ${pr.ventanas} ${pr.ventanas === 1 ? "ventana" : "ventanas"}</p>
      ${pr.imagen ? `<img src="${pr.imagen}" alt="" style="border-radius:14px;width:100%;margin-bottom:14px">` : ""}
      <div style="display:grid;gap:10px">
        ${pr.ejemplo ? '<button class="boton" data-abrir>Abrir y seguir probando</button>' : ""}
        <button class="boton claro" data-borrar>Eliminar proyecto</button></div>`, hoja => {
      const ab = hoja.querySelector("[data-abrir]");
      if (ab) ab.onclick = async () => {
        const ej = EJEMPLOS.find(e => e.id === pr.ejemplo); const img = await cargarImagen(ej.imagen);
        E.foto = { fuente: img, url: ej.imagen, ancho: ej.ancho, alto: ej.alto, ejemplo: ej.id, nombre: ej.nombre };
        E.ventanas = pr.quads.map((q, i) => ({ id: `v${i}`, sel: true, ...q }));
        E.producto = p; E.color = pr.color; E.proyectoId = pr.id; E.pila = []; E.actual = { nombre: "proyectos", datos: {} };
        ir("resultado");
      };
      hoja.querySelector("[data-borrar]").onclick = () => {
        guardado.escribir("proyectos", guardado.leer("proyectos", []).filter(x => x.id !== pr.id));
        cerrarHoja(); pintar(); aviso("Proyecto eliminado");
      };
    });
  }

  // =========================================================== arranque
  document.addEventListener("keydown", e => { if (e.key === "Escape") cerrarHoja(); });
  if (!enMarco && "serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
  E.actual = { nombre: "inicio", datos: {} };
  pintar();
})();
