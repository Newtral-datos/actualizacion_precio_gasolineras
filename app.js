/* Configuración */
const PMTILES_URL = "https://Newtral-datos.github.io/actualizacion_precio_gasolineras/estaciones.pmtiles";
const STATS_URL   = "https://Newtral-datos.github.io/actualizacion_precio_gasolineras/stats.json";

const INITIAL_CENTER = [-3.7, 40.3];
const INITIAL_ZOOM   = 5;

const FALLBACK_MIN = 1.03;
const FALLBACK_MAX = 1.89;
const FALLBACK_BREAKS = [1.42, 1.46, 1.50, 1.54, 1.58, 1.62, 1.66];

/* Paletas */
const GAS_COLORS    = ['#b8fff1','#88ffe5','#5df7d4','#3ceec4','#22ddb1','#09c39a','#019b7a','#00745b'];
const DIESEL_COLORS = ['#fff4c2','#ffe79a','#ffd76a','#ffca3a','#f3b61f','#d79a00','#a87200','#6f4d00'];

/* Campos */
const FLD = {
  direccion: 'Dirección',
  horario: 'Horario',
  municipio: 'Municipio',
  provincia: 'Provincia',
  rotulo: 'Rótulo',
  gas95: 'Precio Gasolina 95 E5',
  diesel: 'Precio Gasoleo A',
  fechaDescarga: 'FechaDescarga'
};

/* Estado */
let DOMAIN_MIN = FALLBACK_MIN;
let DOMAIN_MAX = FALLBACK_MAX;
let BREAKS     = [...FALLBACK_BREAKS];
let currentFuel = 'g95';
const STATS_CACHE = { g95: null, diesel: null };

/* UI refs */
const tabs = document.querySelectorAll('#fuel-tabs .tab');
const swWrap = document.getElementById('legend-swatches');
const labWrap = document.getElementById('legend-labels');
const rangeEl = document.getElementById('range');
const minLabel = document.getElementById('min-label');
const maxLabel = document.getElementById('max-label');

/* Mapa */
const map = new maplibregl.Map({
  container: 'map',
  style: { version: 8, sources: {}, layers: [] },
  center: INITIAL_CENTER, zoom: INITIAL_ZOOM, antialias: true
});
map.addControl(new maplibregl.NavigationControl(), 'top-right');

/* Mapa base */
map.on('load', () => {
  map.addSource('basemap', {
    type: 'raster',
    tiles: ['https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{z}/{x}/{y}{r}.png'],
    tileSize: 256,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> © <a href="https://carto.com/">CARTO</a>'
  });
  map.addLayer({ id: 'basemap', type: 'raster', source: 'basemap' });

  /* PMTiles */
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol('pmtiles', protocol.tile);
  const p = new pmtiles.PMTiles(PMTILES_URL);
  protocol.add(p);

  map.addSource('stations', { type: 'vector', url: `pmtiles://${PMTILES_URL}` });
  map.addLayer({
    id: 'stations-circles',
    type: 'circle',
    source: 'stations',
    'source-layer': 'estaciones',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 0.6, 6, 2, 8, 3.5, 10, 5],
      'circle-color': circleColorExpr(currentFuel),
      'circle-stroke-color': circleColorExpr(currentFuel),
      'circle-stroke-width': 0.6,
      'circle-opacity': 0.95
    }
  });

  ensureGlobalStats(currentFuel).then(() => {
    updateLegendTitle();
    syncSliderLegendAndStyle();
  });

  map.on('mousemove','stations-circles', e => {
    if (!e.features?.length) return;
    map.getCanvas().style.cursor = 'pointer';
    const p = e.features[0].properties || {};
    showPopup(e.lngLat, popupHTML(p));
  });
  map.on('mouseleave','stations-circles', () => {
    map.getCanvas().style.cursor = ''; hidePopup();
  });
});

/* Leyenda */
function buildLegend(){
  const sw = document.getElementById('legend-swatches');
  const lab = document.getElementById('legend-labels');
  sw.innerHTML = ''; lab.innerHTML = '';

  const COLORS = currentFuel === 'g95' ? GAS_COLORS : DIESEL_COLORS;

  // 8 colores
  for (let i = 0; i < 8; i++) {
    const el = document.createElement('div');
    el.className = 'sw';
    el.style.background = COLORS[i];
    sw.appendChild(el);
  }

  // 8 etiquetas
  const labels = [
    DOMAIN_MIN,
    BREAKS[0], BREAKS[1], BREAKS[2],
    BREAKS[3], BREAKS[4], BREAKS[5],
    BREAKS[6],
    DOMAIN_MAX
  ].filter(v => typeof v === 'number');

  // Nos aseguramos de tener exactamente 8 labels
  const eight = (labels.length === 9) ? labels.slice(0, 8) : (
    labels.length === 8 ? labels : [DOMAIN_MIN, ...BREAKS.slice(0,6), DOMAIN_MAX].slice(0,8)
  );

  eight.forEach(v => {
    const span = document.createElement('span');
    span.textContent = fmt(v);
    lab.appendChild(span);
  });
}

function updateLegendTitle(){
  const t = document.getElementById('legend-title-text');
  if (t) t.textContent = (currentFuel === 'g95') ? 'Precio de la gasolina' : 'Precio del diésel';
}
const mid = f => DOMAIN_MIN + (DOMAIN_MAX - DOMAIN_MIN) * f;

/* Slider */
noUiSlider.create(rangeEl, {
  start: [FALLBACK_MIN, FALLBACK_MAX],
  connect: true, step: 0.01,
  range: { min: FALLBACK_MIN, max: FALLBACK_MAX }
});
rangeEl.noUiSlider.on('update', ([a,b]) => { minLabel.textContent = fmt(+a); maxLabel.textContent = fmt(+b); });
rangeEl.noUiSlider.on('change', applyFilters);

/* Tabs */
tabs.forEach(btn => {
  btn.addEventListener('click', async () => {
    if (btn.classList.contains('is-active')) return;
    tabs.forEach(b => { b.classList.remove('is-active'); b.setAttribute('aria-selected','false'); });
    btn.classList.add('is-active'); btn.setAttribute('aria-selected','true');
    currentFuel = btn.dataset.fuel;
    updateLegendTitle();
    await ensureGlobalStats(currentFuel);
    syncSliderLegendAndStyle();
  });
});

/* Expresiones */
function priceExpr(fieldName){ return ['to-number',['get',fieldName]]; }
function activePriceExpr(){ return currentFuel === 'g95' ? priceExpr(FLD.gas95) : priceExpr(FLD.diesel); }
function circleColorExpr(fuel){
  const field = (fuel === 'g95') ? priceExpr(FLD.gas95) : priceExpr(FLD.diesel);
  const COLORS = (fuel === 'g95') ? GAS_COLORS : DIESEL_COLORS;
  return ['step', field,
    COLORS[0],
    BREAKS[0], COLORS[1],
    BREAKS[1], COLORS[2],
    BREAKS[2], COLORS[3],
    BREAKS[3], COLORS[4],
    BREAKS[4], COLORS[5],
    BREAKS[5], COLORS[6],
    BREAKS[6], COLORS[7]
  ];
}

/* Popup */
let popup;
function showPopup(lngLat, html){
  if(!popup) popup = new maplibregl.Popup({closeButton:false, closeOnClick:false, offset:8});
  popup.setLngLat(lngLat).setHTML(html).addTo(map);
}
function hidePopup(){ if(popup) popup.remove(); }
function popupHTML(p){
  return `
    <div class="pp">
      <h3 class="pp-title">${p[FLD.rotulo] || '—'}</h3>
      <p class="pp-sub">${p[FLD.direccion] || '—'}</p>
      <div class="pp-row">
        <div><span class="pp-badge pp-badge--gas">Gasolina 95:</span><div class="pp-price">${fmtPrice(p[FLD.gas95])}</div></div>
        <div><span class="pp-badge pp-badge--diesel">Diésel:</span><div class="pp-price">${fmtPrice(p[FLD.diesel])}</div></div>
      </div>
      <div class="pp-footer">Fecha de actualización: ${p[FLD.fechaDescarga] || '—'}</div>
    </div>`;
}

/* Filtros */
function restyleLayer(){
  if (!map.getLayer('stations-circles')) return;
  const expr = circleColorExpr(currentFuel);
  map.setPaintProperty('stations-circles','circle-color', expr);
  map.setPaintProperty('stations-circles','circle-stroke-color', expr);
}
function applyFilters(){
  if (!map.getLayer('stations-circles')) return;
  const [minV,maxV] = rangeEl.noUiSlider.get().map(Number);
  map.setFilter('stations-circles', ['all', ['>=', activePriceExpr(), minV], ['<=', activePriceExpr(), maxV]]);
}
function syncSliderLegendAndStyle(){
  rangeEl.noUiSlider.updateOptions({ range: { min: DOMAIN_MIN, max: DOMAIN_MAX }, start: [DOMAIN_MIN, DOMAIN_MAX] }, true);
  minLabel.textContent = fmt(DOMAIN_MIN);
  maxLabel.textContent = fmt(DOMAIN_MAX);
  buildLegend(); restyleLayer(); applyFilters();
}

/* Datos desde Pages */
async function ensureGlobalStats(fuel){
  if (STATS_CACHE[fuel]) { setDomain(STATS_CACHE[fuel].min, STATS_CACHE[fuel].max, STATS_CACHE[fuel].breaks); return; }
  let min = FALLBACK_MIN, max = FALLBACK_MAX, breaks = [...FALLBACK_BREAKS];
  try{
    const res = await fetch(STATS_URL, { cache: 'no-cache' });
    if (res.ok){
      const j = await res.json();
      const fieldName = (fuel === 'g95') ? FLD.gas95 : FLD.diesel;
      if (j[fieldName]){
        min = j[fieldName].min; max = j[fieldName].max; breaks = j[fieldName].breaks;
      }
    }
  }catch(e){}
  STATS_CACHE[fuel] = {min, max, breaks};
  setDomain(min, max, breaks);
}

/* Arreglos */
function setDomain(min, max, breaks){ DOMAIN_MIN = round2(min); DOMAIN_MAX = round2(max); BREAKS = breaks.map(round2); }
function fmtPrice(v){ if (v == null || v === '') return '—'; const n = parseFloat(String(v).replace(',','.')); return Number.isFinite(n) ? n.toFixed(2).replace('.', ',') + '€/l' : '—'; }
function fmt(n){ return Number(n).toFixed(2).replace('.',',') + '€'; }
function round2(n){ return Math.round(n*100)/100; }
