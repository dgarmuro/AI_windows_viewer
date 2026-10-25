// Catalogo de demostracion. Cada modelo se dibuja en vectorial a escala real
// (perfiles en mm), asi el color se cambia al momento y el grosor del perfil
// sale correcto cuando el cliente mete las medidas del hueco.
window.COLORES = {
  blanco:    { nombre: "Blanco",         codigo: "RAL 9016", hex: "#F1F0EB", acabado: "liso" },
  crema:     { nombre: "Crema",          codigo: "RAL 9001", hex: "#E8E0CC", acabado: "liso" },
  plata:     { nombre: "Gris plata",     codigo: "RAL 9006", hex: "#A7ABAD", acabado: "metal" },
  antracita: { nombre: "Gris antracita", codigo: "RAL 7016", hex: "#3A4045", acabado: "liso" },
  negro:     { nombre: "Negro forja",    codigo: "RAL 9005", hex: "#1F2022", acabado: "liso" },
  verde:     { nombre: "Verde inglés",   codigo: "RAL 6009", hex: "#2D463A", acabado: "liso" },
  roble:     { nombre: "Roble dorado",   codigo: "Foliado",  hex: "#A86E3A", acabado: "madera" },
  nogal:     { nombre: "Nogal",          codigo: "Foliado",  hex: "#5A3923", acabado: "madera" },
};

window.CATALOGO = [
  {
    id: "aura-duo", nombre: "Aura 70 Duo", material: "PVC", apertura: "Oscilobatiente, 2 hojas",
    lema: "La ventana de dos hojas para casi cualquier fachada.",
    tipo: "dos", perfiles: { marco: 66, hoja: 74 }, colores: ["blanco", "antracita", "roble", "nogal", "crema"],
    precio_m2: 295, destacado: true,
    ficha: { Sistema: "Perfil de 70 mm, 5 cámaras", Vidrio: "4/16/4 bajo emisivo con argón", "Transmitancia Uw": "1,2 W/m²K",
             "Aislamiento acústico": "36 dB", Herrajes: "Oscilobatiente, 2 puntos de cierre", Garantía: "10 años" },
  },
  {
    id: "aura", nombre: "Aura 70", material: "PVC", apertura: "Oscilobatiente, 1 hoja",
    lema: "Una sola hoja, máxima luz en huecos estrechos.",
    tipo: "una", perfiles: { marco: 66, hoja: 74 }, colores: ["blanco", "antracita", "roble", "nogal", "crema"],
    precio_m2: 280, destacado: false,
    ficha: { Sistema: "Perfil de 70 mm, 5 cámaras", Vidrio: "4/16/4 bajo emisivo con argón", "Transmitancia Uw": "1,2 W/m²K",
             "Aislamiento acústico": "36 dB", Herrajes: "Oscilobatiente, 2 puntos de cierre", Garantía: "10 años" },
  },
  {
    id: "clasica", nombre: "Clásica Cuarterones", material: "Madera", apertura: "Abatible, 2 hojas",
    lema: "Madera laminada con cuarterones, para casas tradicionales.",
    tipo: "cuarterones", perfiles: { marco: 76, hoja: 84, cuarteron: 30 }, colores: ["roble", "nogal", "blanco", "verde"],
    precio_m2: 520, destacado: true,
    ficha: { Sistema: "Pino laminado de 68 mm", Vidrio: "4/14/4 bajo emisivo", "Transmitancia Uw": "1,3 W/m²K",
             "Aislamiento acústico": "35 dB", Cuarterones: "2 × 3 por hoja, adheridos", Garantía: "10 años" },
  },
  {
    id: "linea-s", nombre: "Línea S Corredera", material: "Aluminio", apertura: "Corredera, 2 hojas",
    lema: "Perfiles finos de aluminio con rotura de puente térmico.",
    tipo: "corredera", perfiles: { marco: 46, hoja: 56 }, colores: ["antracita", "negro", "blanco", "plata"],
    precio_m2: 340, destacado: true,
    ficha: { Sistema: "Aluminio RPT, marco de 70 mm", Vidrio: "4/12/4 bajo emisivo", "Transmitancia Uw": "1,6 W/m²K",
             "Aislamiento acústico": "32 dB", Herrajes: "Cierre embutido", Garantía: "10 años" },
  },
  {
    id: "panorama", nombre: "Panorama 82", material: "PVC", apertura: "Fijo + oscilobatiente",
    lema: "Paño fijo amplio y una hoja practicable para ventilar.",
    tipo: "fijo_abatible", perfiles: { marco: 70, hoja: 78, central: 72 }, colores: ["blanco", "antracita", "negro", "roble"],
    precio_m2: 380, destacado: false,
    ficha: { Sistema: "Perfil de 82 mm, 6 cámaras", Vidrio: "Triple 4/12/4/12/4", "Transmitancia Uw": "0,9 W/m²K",
             "Aislamiento acústico": "40 dB", Herrajes: "Oscilobatiente con microventilación", Garantía: "15 años" },
  },
  {
    id: "nordica", nombre: "Nórdica con montante", material: "Aluminio", apertura: "Abatible + fijo superior",
    lema: "Montante fijo arriba y hoja abatible, de líneas limpias.",
    tipo: "montante_sup", perfiles: { marco: 50, hoja: 60, central: 60 }, colores: ["negro", "antracita", "blanco", "plata"],
    precio_m2: 360, destacado: false,
    ficha: { Sistema: "Aluminio RPT de 75 mm", Vidrio: "4/16/4 bajo emisivo con argón", "Transmitancia Uw": "1,4 W/m²K",
             "Aislamiento acústico": "34 dB", Herrajes: "Bisagras ocultas", Garantía: "10 años" },
  },
];
