/* Motor de composicion: dibuja la ventana del catalogo y la coloca en la foto.
 *
 *   Motor.miniatura(producto, color, ancho, alto)        -> canvas para catalogo/ficha
 *   Motor.componer(foto, ventanas, producto, color)      -> canvas con el resultado
 *
 * Cuando se conecte el backend, `componer` se sustituye por la imagen que devuelva
 * /api/render; el resto de la app no cambia.
 */
(function () {
  "use strict";
  const ANCHO_POR_DEFECTO = 1200;          // mm, si el cliente no da medidas

  // ------------------------------------------------------------ color
  const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const rgb = (c, a = 1) => `rgba(${c.map(v => Math.round(Math.max(0, Math.min(255, v)))).join(",")},${a})`;
  const mezcla = (a, b, t) => a.map((v, i) => v * (1 - t) + b[i] * t);
  const luma = c => (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;

  function aleatorio(semilla) {            // determinista: la veta de la madera no "baila"
    let s = semilla >>> 0;
    return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  }

  // ------------------------------------------------------------ dibujo de un perfil
  function miembro(ctx, x, y, w, h, col, vertical, pxmm, semilla) {
    const base = hex(col.hex);
    ctx.fillStyle = rgb(base);
    ctx.fillRect(x, y, w, h);
    if (col.acabado === "madera") {
      const r = aleatorio(semilla), largo = vertical ? h : w, ancho = vertical ? w : h;
      for (let i = 0; i < ancho; i += Math.max(1, pxmm * 2.2)) {
        const a = 0.05 + r() * 0.12, osc = r() < 0.5;
        ctx.fillStyle = rgb(osc ? mezcla(base, [30, 15, 5], 0.5) : mezcla(base, [255, 220, 170], 0.4), a);
        if (vertical) ctx.fillRect(x + i, y, Math.max(1, pxmm * (0.6 + r())), largo);
        else ctx.fillRect(x, y + i, largo, Math.max(1, pxmm * (0.6 + r())));
      }
    } else if (col.acabado === "metal") {
      const g = vertical ? ctx.createLinearGradient(x, 0, x + w, 0) : ctx.createLinearGradient(0, y, 0, y + h);
      g.addColorStop(0, "rgba(255,255,255,.18)"); g.addColorStop(0.5, "rgba(255,255,255,0)"); g.addColorStop(1, "rgba(0,0,0,.12)");
      ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
    }
    // bisel: luz arriba-izquierda, sombra abajo-derecha
    const b = Math.max(1, pxmm * 3.5);
    ctx.fillStyle = "rgba(255,255,255,.22)";
    ctx.fillRect(x, y, w, b); ctx.fillRect(x, y, b, h);
    ctx.fillStyle = "rgba(0,0,0,.22)";
    ctx.fillRect(x, y + h - b, w, b); ctx.fillRect(x + w - b, y, b, h);
  }

  function marcoRect(ctx, x, y, w, h, grosor, col, pxmm, semilla) {
    const g = grosor;
    miembro(ctx, x, y, w, g, col, false, pxmm, semilla);
    miembro(ctx, x, y + h - g, w, g, col, false, pxmm, semilla + 1);
    miembro(ctx, x, y + g, g, h - 2 * g, col, true, pxmm, semilla + 2);
    miembro(ctx, x + w - g, y + g, g, h - 2 * g, col, true, pxmm, semilla + 3);
  }

  function vidrio(ctx, x, y, w, h, cielo, pxmm, opciones = {}) {
    const oscuro = [24, 30, 36];
    const g = ctx.createLinearGradient(0, y, 0, y + h);
    g.addColorStop(0, rgb(mezcla(oscuro, cielo, 0.42)));
    g.addColorStop(0.45, rgb(mezcla(oscuro, cielo, 0.16)));
    g.addColorStop(1, rgb(mezcla(oscuro, cielo, 0.08)));
    ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
    // reflejo diagonal suave
    ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
    const d = ctx.createLinearGradient(x, y, x + w, y + h);
    d.addColorStop(0.18, "rgba(255,255,255,0)"); d.addColorStop(0.32, "rgba(255,255,255,.10)");
    d.addColorStop(0.42, "rgba(255,255,255,0)"); d.addColorStop(0.62, "rgba(255,255,255,.05)"); d.addColorStop(0.7, "rgba(255,255,255,0)");
    ctx.fillStyle = d; ctx.fillRect(x, y, w, h);
    // sombra del junquillo arriba e izquierda
    const s = Math.max(1, pxmm * 9);
    let sg = ctx.createLinearGradient(0, y, 0, y + s); sg.addColorStop(0, "rgba(0,0,0,.35)"); sg.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = sg; ctx.fillRect(x, y, w, s);
    sg = ctx.createLinearGradient(x, 0, x + s, 0); sg.addColorStop(0, "rgba(0,0,0,.22)"); sg.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = sg; ctx.fillRect(x, y, s, h);
    ctx.restore();
    // cuarterones
    if (opciones.cuarterones) {
      const { cols, filas, grosor, col } = opciones.cuarterones;
      for (let i = 1; i < cols; i++) miembro(ctx, x + (w * i) / cols - grosor / 2, y, grosor, h, col, true, pxmm, 50 + i);
      for (let j = 1; j < filas; j++) miembro(ctx, x, y + (h * j) / filas - grosor / 2, w, grosor, col, false, pxmm, 60 + j);
    }
  }

  function hoja(ctx, x, y, w, h, P, col, cielo, pxmm, manilla, semilla, cuart) {
    marcoRect(ctx, x, y, w, h, P.hoja * pxmm, col, pxmm, semilla);
    const g = P.hoja * pxmm;
    vidrio(ctx, x + g, y + g, w - 2 * g, h - 2 * g, cielo, pxmm,
      cuart ? { cuarterones: { ...cuart, grosor: P.cuarteron * pxmm, col } } : {});
    if (manilla) {
      const oscuro = luma(hex(col.hex)) < 0.35;
      const mw = 16 * pxmm, mh = 120 * pxmm, mx = manilla === "der" ? x + w - g / 2 - mw / 2 : x + g / 2 - mw / 2;
      ctx.fillStyle = oscuro ? "#2a2c2e" : "#c9ccce";
      ctx.fillRect(mx, y + h * 0.5 - mh * 0.15, mw, mh);
      ctx.fillStyle = "rgba(0,0,0,.25)"; ctx.fillRect(mx + mw * 0.7, y + h * 0.5 - mh * 0.15, mw * 0.3, mh);
    }
  }

  // ------------------------------------------------------------ cada tipo de ventana
  function dibujarVentana(ctx, prod, col, w, h, pxmm, cielo) {
    const P = prod.perfiles, m = P.marco * pxmm;
    marcoRect(ctx, 0, 0, w, h, m, col, pxmm, 1);
    const ix = m, iy = m, iw = w - 2 * m, ih = h - 2 * m;
    switch (prod.tipo) {
      case "una":
        hoja(ctx, ix, iy, iw, ih, P, col, cielo, pxmm, "der", 10); break;
      case "dos":
      case "cuarterones": {
        const c = prod.tipo === "cuarterones" ? { cols: 2, filas: 3 } : null;
        hoja(ctx, ix, iy, iw / 2, ih, P, col, cielo, pxmm, "der", 10, c);
        hoja(ctx, ix + iw / 2, iy, iw / 2, ih, P, col, cielo, pxmm, null, 20, c);
        break;
      }
      case "corredera": {
        const solape = 30 * pxmm, hw = iw / 2 + solape / 2;
        hoja(ctx, ix + iw - hw, iy, hw, ih, P, col, cielo, pxmm, null, 20);   // la de atras
        ctx.fillStyle = "rgba(0,0,0,.28)"; ctx.fillRect(ix + hw, iy, 10 * pxmm, ih);
        hoja(ctx, ix, iy, hw, ih, P, col, cielo, pxmm, "der", 10);            // la de delante
        break;
      }
      case "fijo_abatible": {
        const c = P.central * pxmm, fw = (iw - c) * 0.62;
        vidrio(ctx, ix, iy, fw, ih, cielo, pxmm);
        miembro(ctx, ix + fw, iy, c, ih, col, true, pxmm, 30);
        hoja(ctx, ix + fw + c, iy, iw - fw - c, ih, P, col, cielo, pxmm, "izq", 40);
        break;
      }
      case "montante_sup": {
        const c = P.central * pxmm, fh = (ih - c) * 0.28;
        vidrio(ctx, ix, iy, iw, fh, cielo, pxmm);
        miembro(ctx, ix, iy + fh, iw, c, col, false, pxmm, 30);
        hoja(ctx, ix, iy + fh + c, iw, ih - fh - c, P, col, cielo, pxmm, "der", 40);
        break;
      }
    }
  }

  function miniatura(prod, colorId, ancho = 600, alto = 720) {
    const cv = document.createElement("canvas"); cv.width = ancho; cv.height = alto;
    const ctx = cv.getContext("2d");
    const pxmm = ancho / 1100;
    dibujarVentana(ctx, prod, COLORES[colorId], ancho, alto, pxmm, [170, 196, 222]);
    return cv;
  }

  // ------------------------------------------------------------ geometria
  const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  function homografia(q) {   // cuadrado unidad -> cuadrilatero q (TL, TR, BR, BL)
    const src = [[0, 0], [1, 0], [1, 1], [0, 1]], A = [], b = [];
    for (let i = 0; i < 4; i++) {
      const [x, y] = src[i], [u, v] = q[i];
      A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
      A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
    }
    for (let c = 0; c < 8; c++) {                     // Gauss con pivote
      let p = c; for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
      [A[c], A[p]] = [A[p], A[c]]; [b[c], b[p]] = [b[p], b[c]];
      for (let r = 0; r < 8; r++) if (r !== c) {
        const f = A[r][c] / A[c][c];
        for (let k = c; k < 8; k++) A[r][k] -= f * A[c][k]; b[r] -= f * b[c];
      }
    }
    const h = b.map((v, i) => v / A[i][i]);
    return (x, y) => { const d = h[6] * x + h[7] * y + 1; return [(h[0] * x + h[1] * y + h[2]) / d, (h[3] * x + h[4] * y + h[5]) / d]; };
  }

  // Dibuja `src` deformado en perspectiva sobre el cuadrilatero q, con una malla
  // de triangulos (cada uno es una transformacion afin que canvas sabe pintar).
  function deformar(ctx, src, q, n = 14) {
    const H = homografia(q), W = src.width, Hs = src.height;
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      const u0 = i / n, u1 = (i + 1) / n, v0 = j / n, v1 = (j + 1) / n;
      const s = [[u0 * W, v0 * Hs], [u1 * W, v0 * Hs], [u1 * W, v1 * Hs], [u0 * W, v1 * Hs]];
      const d = [H(u0, v0), H(u1, v0), H(u1, v1), H(u0, v1)];
      triangulo(ctx, src, s[0], s[1], s[2], d[0], d[1], d[2]);
      triangulo(ctx, src, s[0], s[2], s[3], d[0], d[2], d[3]);
    }
  }
  function triangulo(ctx, img, s0, s1, s2, d0, d1, d2) {
    // ampliar un poco el triangulo de destino para que no se vean costuras
    const cx = (d0[0] + d1[0] + d2[0]) / 3, cy = (d0[1] + d1[1] + d2[1]) / 3, e = 0.6;
    const ex = p => { const l = Math.hypot(p[0] - cx, p[1] - cy) || 1; return [p[0] + (p[0] - cx) / l * e, p[1] + (p[1] - cy) / l * e]; };
    const D0 = ex(d0), D1 = ex(d1), D2 = ex(d2);
    ctx.save();
    ctx.beginPath(); ctx.moveTo(...D0); ctx.lineTo(...D1); ctx.lineTo(...D2); ctx.closePath(); ctx.clip();
    const den = s0[0] * (s1[1] - s2[1]) + s1[0] * (s2[1] - s0[1]) + s2[0] * (s0[1] - s1[1]);
    const a = (d0[0] * (s1[1] - s2[1]) + d1[0] * (s2[1] - s0[1]) + d2[0] * (s0[1] - s1[1])) / den;
    const b = (d0[1] * (s1[1] - s2[1]) + d1[1] * (s2[1] - s0[1]) + d2[1] * (s0[1] - s1[1])) / den;
    const c = (d0[0] * (s2[0] - s1[0]) + d1[0] * (s0[0] - s2[0]) + d2[0] * (s1[0] - s0[0])) / den;
    const d = (d0[1] * (s2[0] - s1[0]) + d1[1] * (s0[0] - s2[0]) + d2[1] * (s1[0] - s0[0])) / den;
    const e2 = (d0[0] * (s1[0] * s2[1] - s2[0] * s1[1]) + d1[0] * (s2[0] * s0[1] - s0[0] * s2[1]) + d2[0] * (s0[0] * s1[1] - s1[0] * s0[1])) / den;
    const f = (d0[1] * (s1[0] * s2[1] - s2[0] * s1[1]) + d1[1] * (s2[0] * s0[1] - s0[0] * s2[1]) + d2[1] * (s0[0] * s1[1] - s1[0] * s0[1])) / den;
    ctx.transform(a, b, c, d, e2, f);
    ctx.drawImage(img, 0, 0);
    ctx.restore();
  }

  // ------------------------------------------------------------ luz de la foto
  function muestreador(foto) {
    const lado = 420, f = Math.min(1, lado / Math.max(foto.width, foto.height));
    const cv = document.createElement("canvas"); cv.width = Math.round(foto.width * f); cv.height = Math.round(foto.height * f);
    const c = cv.getContext("2d", { willReadFrequently: true }); c.drawImage(foto, 0, 0, cv.width, cv.height);
    const px = c.getImageData(0, 0, cv.width, cv.height).data;
    return (x, y) => {
      const xi = Math.max(0, Math.min(cv.width - 1, Math.round(x * f))), yi = Math.max(0, Math.min(cv.height - 1, Math.round(y * f)));
      const i = (yi * cv.width + xi) * 4; return [px[i], px[i + 1], px[i + 2]];
    };
  }
  function percentil(arr, p) { const s = [...arr].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor(p * s.length))] || 0; }

  // Luz que recibe la ventana, banda a banda de arriba abajo: se mide en la pared
  // a izquierda y derecha a la MISMA altura (aleros y toldos dan sombras horizontales).
  function luzDeLaPared(muestra, q, bandas) {
    const w = (dist(q[0], q[1]) + dist(q[3], q[2])) / 2, sep = 0.14 * w;
    const izq = [], der = [], todos = [];
    for (let r = 0; r < bandas; r++) {
      const t = (r + 0.5) / bandas, pL = lerp(q[0], q[3], t), pR = lerp(q[1], q[2], t);
      const dx = (pR[0] - pL[0]) / (dist(pL, pR) || 1), dy = (pR[1] - pL[1]) / (dist(pL, pR) || 1);
      const L = muestra(pL[0] - dx * sep, pL[1] - dy * sep), R = muestra(pR[0] + dx * sep, pR[1] + dy * sep);
      izq.push(L); der.push(R); todos.push(L, R);
    }
    const lums = todos.map(luma), claro = percentil(lums, 0.9) || 0.5;
    const pared = todos.filter(c => luma(c) >= claro * 0.85);
    const media = pared.reduce((a, c) => a.map((v, i) => v + c[i] / pared.length), [0, 0, 0]);
    return {
      bandas: izq.map((L, r) => Math.max(0.3, Math.min(1, ((luma(L) + luma(der[r])) / 2) / claro))),
      claro, color: media,
    };
  }
  function colorDelCielo(muestra, foto) {
    const cols = [];
    for (let i = 0; i < 24; i++) cols.push(muestra((i + 0.5) / 24 * foto.width, foto.height * 0.03));
    const c = cols.reduce((a, v) => a.map((x, k) => x + v[k] / cols.length), [0, 0, 0]);
    return c[2] > c[0] + 8 && luma(c) > 0.35 ? c : [175, 198, 222];    // si arriba no hay cielo azul
  }

  function encoger(q, t) {   // hacia el centro: la ventana queda dentro del hueco (retranqueo)
    const c = [(q[0][0] + q[1][0] + q[2][0] + q[3][0]) / 4, (q[0][1] + q[1][1] + q[2][1] + q[3][1]) / 4];
    return q.map(p => lerp(p, c, t));
  }

  // ------------------------------------------------------------ composicion
  function componer(foto, ventanas, prod, colorId, opciones = {}) {
    const lado = opciones.lado || 1600, f = Math.min(1, lado / Math.max(foto.width, foto.height));
    const out = document.createElement("canvas");
    out.width = Math.round(foto.width * f); out.height = Math.round(foto.height * f);
    const ctx = out.getContext("2d");
    ctx.drawImage(foto, 0, 0, out.width, out.height);
    const muestra = muestreador(foto), cielo = colorDelCielo(muestra, foto), col = COLORES[colorId];
    const penumbra = out.width > 900;     // en pantallas pequenas basta sin filtro

    for (const v of ventanas) {
      const qFoto = v.quad, q = qFoto.map(p => [p[0] * f, p[1] * f]);
      const luz = luzDeLaPared(muestra, qFoto, 18);
      // tono de la luz: la pared clara dice de que color es la luz (atardecer, sombra...)
      const m = (luz.color[0] + luz.color[1] + luz.color[2]) / 3 || 1;
      const tinte = luz.color.map(c => 1 + (c / m - 1) * 0.55);
      const expo = Math.max(0.5, Math.min(1, luz.claro / 0.8));

      // 1) jamba: el hueco en sombra alrededor de la ventana
      const qIn = encoger(q, 0.035);
      ctx.fillStyle = rgb(luz.color.map(c => c * 0.55));
      ctx.beginPath(); q.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p))); ctx.closePath(); ctx.fill();

      // 2) la ventana enderezada, a escala real
      const wq = (dist(qIn[0], qIn[1]) + dist(qIn[3], qIn[2])) / 2, hq = (dist(qIn[0], qIn[3]) + dist(qIn[1], qIn[2])) / 2;
      const sobre = Math.min(2, 1400 / Math.max(wq, hq));
      const W = Math.max(40, Math.round(wq * sobre)), H = Math.max(40, Math.round(hq * sobre));
      const ancho_mm = v.ancho_mm || ANCHO_POR_DEFECTO;
      const pxmm = W / ancho_mm;
      const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
      const c = cv.getContext("2d");
      dibujarVentana(c, prod, col, W, H, pxmm, cielo);

      // 3) luz de la fachada: tono y sombras por bandas
      c.globalCompositeOperation = "multiply";
      const nb = luz.bandas.length, gl = c.createLinearGradient(0, 0, 0, H);
      luz.bandas.forEach((b, r) => gl.addColorStop((r + 0.5) / nb, rgb(tinte.map(t => 255 * t * b * expo))));
      c.fillStyle = gl; c.fillRect(0, 0, W, H);            // degradado continuo, sin escalones
      // sombra del dintel y de los laterales del hueco
      c.globalCompositeOperation = "source-over";
      let g = c.createLinearGradient(0, 0, 0, H * 0.12); g.addColorStop(0, "rgba(0,0,0,.32)"); g.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = g; c.fillRect(0, 0, W, H * 0.12);
      g = c.createLinearGradient(0, 0, W * 0.05, 0); g.addColorStop(0, "rgba(0,0,0,.18)"); g.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = g; c.fillRect(0, 0, W * 0.05, H);
      g = c.createLinearGradient(W, 0, W * 0.95, 0); g.addColorStop(0, "rgba(0,0,0,.18)"); g.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = g; c.fillRect(W * 0.95, 0, W * 0.05, H);
      // grano, para que no parezca demasiado limpia
      const r = aleatorio(7);
      for (let i = 0; i < (W * H) / 90; i++) { c.fillStyle = r() < 0.5 ? "rgba(0,0,0,.05)" : "rgba(255,255,255,.04)"; c.fillRect(r() * W, r() * H, 1.4, 1.4); }

      // 4) a su sitio en la foto, en perspectiva
      deformar(ctx, cv, qIn);
      if (penumbra) {           // borde de contacto suave
        ctx.save(); ctx.strokeStyle = "rgba(0,0,0,.35)"; ctx.lineWidth = Math.max(1, wq * 0.006);
        ctx.beginPath(); qIn.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p))); ctx.closePath(); ctx.stroke(); ctx.restore();
      }
    }
    return out;
  }

  window.Motor = { miniatura, componer, homografia };
})();
