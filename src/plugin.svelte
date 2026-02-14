<script lang="ts">
  import bcast from '@windy/broadcast';
  import { onDestroy, onMount } from 'svelte';
  import { map } from "@windy/map";
  import store from "@windy/store";
  import { getLatLonInterpolator } from '@windy/interpolator';
  import { wind2obj } from '@windy/utils';  // ou '@windy/wind2obj' selon la version
  import metrics from '@windy/metrics';

  export let title = 'Ship Data';
  let minimized = false;
  let comPort: SerialPort | null = null;
  let tcpInterval: number | null = null;
  let comRunning = false;
  let tcpRunning = false;
  let comReader: ReadableStreamDefaultReader<string> | null = null;
  let comLineBuffer = '';
  let weather: WeatherAtBoat | null = null;
  let markerLayer = L.layerGroup().addTo(map);
  let lastLatitude = '';
  let lastLongitude = '';
  let courseOverGround = 0;
  let boatMarker: L.Marker | null = null;
  let boatPath: L.Polyline | null = null;
  let pathLatLngs: L.LatLng[] = [];
  let expandedTile = '';
  let modelPoints = '';
  let sensorPoints = '';
  let error = '';
  let gpsData = '';
  let followShip = true;
  let showAIS = true;
  let latitude = null;
  let longitude = null;
  let cloudsInfo = '---';
  let visibility = '-';
  let badVisAzimuth = '-';
  let currentDir = '-';
  let currentSpeed = '-';
  let currentDirModel = '-';
  let currentSpeedModel = '-';
  let wavesDir = '-';
  let wavesHeight = '-';
  let swellDir = '-';
  let swellHeight = '-';
  let windDir = '-';
  let windSpeed = '-';
  let beaufort = '-';
  let windSpeedmodele = '-';
  let beaufortmodele = '-';
  let gustsDir = '-';
  let gustsSpeed = '-';
  let gustsDirmodele = '-';
  let gustsSpeedmodele = '-';
  let airTemp = '-';
  let seaTemp = '-';
  let pressure = '-';
  let airTempmodele = '-';
  let seaTempmodele = '-';
  let pressuremodele = '-';
  let ownShipMMSI: number | null = null;
  let aisLayer = L.layerGroup().addTo(map);
  let speedThroughWind = '-';
  let boatHeading = 0;
  let sogValue = 0;
  let cogValue = 0;
  let gustWindow: { t: number; speed: number }[] = [];
  let connectionType = localStorage.getItem('shipPlugin_connType') ?? 'TCP';
  let baudRate = parseInt(localStorage.getItem('shipPlugin_baudRate') ?? '9600');
  
  const GUST_WINDOW_MS = 3600_000; // 1h


  let sensor = {
    current: 'ADCP',
    waves: 'Model',
    swell: 'Model',
    wind: 'Anemometer',
    gusts: 'Anemometer',
    air: 'Thermometer',
    sea: 'Thermometer',
    pressure: 'Barom.',
    model: 'Model'
  };
  let history = {
    air: [],
    sea: [],
    wind: [],
    gusts: [],
    current: [],
    pressure: []
  };
let gpsSource: 'RMC' | 'GLL' | 'AIS' | null = null;
let lastGPSTimestamp = 0;


function updateGust(speedKnots: number) {
  const now = Date.now();
  
  // Ajoute la mesure
  gustWindow.push({ t: now, speed: speedKnots });
  
  // Nettoie les mesures > 1h
  gustWindow = gustWindow.filter(p => now - p.t < GUST_WINDOW_MS);
  
  // Max de la fenêtre = rafale
  const max = Math.max(...gustWindow.map(p => p.speed));
  gustsSpeed = max.toFixed(1);
  gustsDir   = windDir; // direction au moment du max — approximation
  
  history.gusts.push({ t: now, sensor: max, model: null });
  updateStatusDots();
}




function updatePosition(lat: number, lon: number, source: 'RMC' | 'GLL' | 'AIS') {

  const now = Date.now();

  // Si c'est AIS, on ne l'utilise que si aucun GPS récent
  if (source === 'AIS') {
    if (gpsSource && gpsSource !== 'AIS' && now - lastGPSTimestamp < 5000) {
      return; // un vrai GPS est actif → on ignore AIS
    }
  }

  latitude = lat;
  longitude = lon;
  gpsSource = source;
  lastGPSTimestamp = now;

  addBoatMarker(lat, lon, courseOverGround);
  fetchAllModelData(lat, lon);
}

//-----------------------pushHistory
//pushHistory('air', airTemp, airTemp /* futur modèle */);
//-----------------------pushHistory
  function pushHistory(key, sensorValue, modelValue) {
  const now = Date.now();

  history[key].push({
    t: now,
    sensor: sensorValue,
    model: modelValue
  });
  

//ettoyage > 24h
  const limit = now - HISTORY_DURATION_HOURS * 3600 * 1000;
  history[key] = history[key].filter(p => p.t >= limit);
}




//-----------------------pushHistory
async function connectCOM() {
  if (comRunning) return;

  stopTCP();
  comRunning = true;

  try {
    comPort = await navigator.serial.requestPort();
    await comPort.open({ baudRate });

    const decoder = new TextDecoderStream();
    comPort.readable?.pipeTo(decoder.writable);
    comReader = decoder.readable.getReader();

    comLineBuffer = '';

    while (comRunning) {
      const { value, done } = await comReader.read();
      if (done) break;

      comLineBuffer += value;
      let i;
      while ((i = comLineBuffer.indexOf('\n')) >= 0) {
        const line = comLineBuffer.slice(0, i).trim();
        comLineBuffer = comLineBuffer.slice(i + 1);
        if (line) parseNMEA(line);
      }
    }
  } catch (err) {
    error = `COM Error: ${err}`;
    console.error(err);
  }
}



async function stopCOM() {
  comRunning = false;

  if (comReader) {
    try { await comReader.cancel(); } catch {}
    comReader = null;
  }

  if (comPort) {
    try { await comPort.close(); } catch {}
    comPort = null;
  }
}
$: {
  localStorage.setItem('shipPlugin_connType', connectionType);
  if (connectionType === 'TCP') {
    startTCP();
  } else if (connectionType === 'COM') {
    stopTCP();
  }
}
$: localStorage.setItem('shipPlugin_baudRate', String(baudRate));


//-----------------------export CSV
function exportCSV() {
  if (!expandedTile) return;

  const rows = history[expandedTile];
  let csv = 'timestamp,sensor,model\n';

  rows.forEach(r => {
    csv += `${new Date(r.t).toISOString()},${r.sensor ?? ''},${r.model ?? ''}\n`;
  });

  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = `${expandedTile}_24h.csv`;
  a.click();

  URL.revokeObjectURL(url);
}
//-----------------------export CSV

  
  function toggleFollowShip() { followShip = !followShip; }
  function openTutorial() {
    window.open('https://yannkerherve.github.io/position-plugin/', '_blank');
  }
 
  
  
$: activeHistory = (expandedTile && history[expandedTile]) ? history[expandedTile] : [];


$: if (activeHistory.length >= 2) {
  modelPoints = buildCurve(activeHistory, 'model');
  sensorPoints = buildCurve(activeHistory, 'sensor');
} else {
  modelPoints = '';
  sensorPoints = '';
}

function buildCurve(data, key) {
  // ── FILTRE les null/undefined avant tout ──
  const values = data
    .map(d => d[key])
    .filter(v => v != null && !isNaN(v));

  // Pas assez de points valides → courbe vide
  if (values.length < 2) return '';

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1; // ← évite division par zéro si tous égaux

  // Reconstruction en ignorant les points null
  const validData = data.filter(d => d[key] != null && !isNaN(d[key]));

  return validData.map((d, i) => {
    const x = (i / (validData.length - 1)) * 100;
    const y = 40 - ((d[key] - min) / range) * 40;
    return `${x},${y}`;
  }).join(' ');
}





let nmeaBuffer = '';

async function fetchTCPData() {
  try {
    const response = await fetch('http://localhost:5000/gps-data');
    const raw = await response.text();

    gpsData = raw;

    // 🔹 On découpe dès qu'on voit un $ ou !AI
    const sentences = raw.split(/\r?\n/);
    console.log("recu :",sentences);
    if (!sentences) return;

    for (const sentence of sentences) {
      const trimmed = sentence.trim();
      if (!trimmed) continue;

      parseNMEA(trimmed);
    }

  } catch (err) {
    error = 'TCP server unreachable';
    console.error(err);
  }
}


function parseNMEA(sentence: string) {
  if (sentence.startsWith('!AI')) {
    parseAIS(sentence);
    return;
  }

  // --- NMEA classiques ---
  if (!sentence.startsWith('$')) return;

  const type = sentence.substring(3, 6);

switch (type) {
  case 'RMC':
    parseRMC(sentence);
 
    break;
  case 'GLL':
    parseGLL(sentence);

    break;
  case 'VTG':
    parseVTG(sentence);

    break;
  case 'VHW':
    parseVHW(sentence);
    break;
  case 'MWD':
    parseMWD(sentence);

    break;
  case 'MWV':
    parseMWV(sentence);

    break;
  case 'MDA':
    parseMDA(sentence);

    break;
  case 'XDR':
    parseXDR(sentence);
    
  case 'HDG':
  case 'HDT':
      parseHeading(sentence);
      break;

    case 'VPW':
      parseVPW(sentence);
      break;
    
  default:
      console.debug('Unhandled NMEA:', sentence);
  }
}

function parseMWD(sentence: string) {
  const p = sentence.split(',');

  const dirTrue = parseFloat(p[1]);
  const speedKnots = parseFloat(p[5]);

  if (!isNaN(dirTrue))
    windDir = dirTrue;
    

  if (!isNaN(speedKnots))
    windSpeed = speedKnots;
    beaufort = knotsToBeaufort(windSpeed);
    history.wind.push({ t: Date.now(), sensor: speedKnots, model: null });
    updateStatusDots();
    updateGust(speedKnots);
}

function parseHeading(sentence: string) {
  const p = sentence.split(',');

  const heading = parseFloat(p[1]);

  if (!isNaN(heading))
    boatHeading = heading;
    computeCurrent();
}
function parseVPW(sentence: string) {
  const p = sentence.split(',');

  const speed = parseFloat(p[1]);

  if (!isNaN(speed))
    speedThroughWind = speed;
}

function knotsToBeaufort(knots) {
  if (knots < 1) return 0;
  if (knots <= 3) return 1;
  if (knots <= 6) return 2;
  if (knots <= 10) return 3;
  if (knots <= 16) return 4;
  if (knots <= 21) return 5;
  if (knots <= 27) return 6;
  if (knots <= 33) return 7;
  if (knots <= 40) return 8;
  if (knots <= 47) return 9;
  if (knots <= 55) return 10;
  if (knots <= 63) return 11;
  return 12;
}



// ── VARIABLES SÉPARÉES ──
let stw = 0;           // vitesse surface (loch) — ne jamais écraser

// ── parseVHW — stocke dans stw, PAS currentSpeed ──


// ── computeCurrent — lit stw, écrit currentSpeed/currentDir ──
function computeCurrent() {
  console.log('[CURRENT DEBUG]', { sogValue, cogValue, stw, boatHeading });

  if (stw === 0 || sogValue === 0) {
    currentSpeed = '-';
    currentDir = '-';
    return;
  }

  const hdg = (boatHeading !== 0) ? boatHeading : cogValue;

  const cogRad = cogValue * Math.PI / 180;
  const hdgRad = hdg       * Math.PI / 180;

  const cu = sogValue * Math.sin(cogRad) - stw * Math.sin(hdgRad);
  const cv = sogValue * Math.cos(cogRad) - stw * Math.cos(hdgRad);

  const speed = Math.sqrt(cu * cu + cv * cv);
  const dir   = (Math.atan2(cu, cv) * 180 / Math.PI + 360) % 360;

  console.log('[CURRENT RESULT]', { speed, dir });

  currentSpeed = speed.toFixed(2);   // ← courant calculé
  currentDir   = dir.toFixed(0);

  history.current.push({ t: Date.now(), sensor: speed, model: null });
  updateStatusDots();
}








function parseRMC(sentence) {
  const p = sentence.split(',');

  if (p[2] !== 'A') return; // invalid fix

  const lat = parseCoord(p[3], p[4]);
  const lon = parseCoord(p[5], p[6]);

  const newLat = lat;
  const newLon = lon;
  courseOverGround = parseFloat(p[8]) || 0;
  cogValue = courseOverGround; //← stocke COG
  sogValue = parseFloat(p[7]) || 0;


  if (lastLatitude !== null && lastLongitude !== null) {
    courseOverGround = calculateBearing(
      lastLatitude,
      lastLongitude,
      newLat,
      newLon
    );
  }


  lastLatitude = newLat;
  lastLongitude = newLon;

  latitude = newLat;
  longitude = newLon;
  //updateWeather(latitude, longitude);
  courseOverGround = parseFloat(p[8]) || 0;
  const sog = parseFloat(p[7]) || 0;

  updatePosition(newLat, newLon, 'RMC');
  computeCurrent();

  if (!isNaN(sog)) {
    history.current.push({ t: Date.now(), sensor: sog, model: null });
  } 
  //addBoatMarker(newLat, newLon, courseOverGround);
  console.log('added boat');
  
}

function parseVTG(sentence: string) {
  const p = sentence.split(',');
  courseOverGround = parseFloat(p[1]) || 0;
  const sog = parseFloat(p[5]) || 0;

  if (!isNaN(sog)) {
    history.current.push({ t: Date.now(), sensor: sog, model: null });
  }
}
function parseVHW(sentence: string) {
  const p = sentence.split(',');
  const val = parseFloat(p[5]); // nœuds
  if (!isNaN(val)) {
    stw = val;          // ← variable dédiée, jamais touchée ailleurs
    computeCurrent();
  }
}
function parseMWV(sentence: string) {
  const p = sentence.split(',');

  const angle = parseFloat(p[1]);
  const ref = p[2]; // T ou R
  const speed = parseFloat(p[3]);
  const valid = p[5] === 'A';

  if (!valid) return;

  if (ref === 'T') {
    windDir = angle;
    windSpeed = speed;
    updateStatusDots();
  }
}
function parseMDA(sentence: string) {
  const p = sentence.split(',');

  const pressureBar = parseFloat(p[3]);
  const air = parseFloat(p[5]);
  const water = parseFloat(p[9]);

  if (!isNaN(pressureBar)) {
    pressure = (pressureBar * 1000).toFixed(0);
    updateStatusDots();
  }

  if (!isNaN(air)) {
    airTemp = air.toFixed(1);
    updateStatusDots();
  }

  if (!isNaN(water)) {
    seaTemp = water.toFixed(1);
    updateStatusDots();
  }
}

function parseXDR(sentence: string) {
  const p = sentence.split(',');

  for (let i = 0; i < p.length; i += 4) {
    const type = p[i];
    const value = parseFloat(p[i + 1]);
    const unit = p[i + 2];
    const name = p[i + 3];

    if (type === 'C' && name?.includes('Air')) {
      airTemp = value.toFixed(1);
    }

    if (type === 'C' && name?.includes('Sea')) {
      seaTemp = value.toFixed(1);
    }

    if (type === 'P') {
      pressure = value.toFixed(0);
    }
  }
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////////////
// ============================================================
// MÉTÉO MODÈLE — lecture via interpolator natif Windy
// ============================================================

let lastModelFetch = 0;
let isFetchingModel = false;

interface ModelWeather {
  windSpeed:    number | null;
  windDir:      number | null;
  gustSpeed:    number | null;
  gustDir:      number | null;
  airTemp:      number | null;
  seaTempModel: number | null;
  pressure:     number | null;
  wavesHeight:  number | null;
  wavesDir:     number | null;
  swellHeight:  number | null;
  swellDir:     number | null;
  currentSpeed: number | null;
  currentDir:   number | null;
  clouds:       number | null;   // ← nouveau
  cloudsLabel:  string | null;   // ← nouveau
  visibility:   number | null;   // ← nouveau
}

let modelWeather: ModelWeather = {
  windSpeed: null, windDir: null,
  gustSpeed: null, gustDir: null,
  airTemp: null, seaTempModel: null, pressure: null,
  wavesHeight: null, wavesDir: null,
  swellHeight: null, swellDir: null,
  currentSpeed: null, currentDir: null,
  clouds: null, cloudsLabel: null, visibility: null,
};




// ============================================================
// POINT D'ENTRÉE
// ============================================================
// ============================================================
// FETCH COMPLET — approche interpolator direct
// ============================================================

// Remplace fetchOneOverlay ET fetchAllModelData par ceci

async function fetchAllModelData(lat: number, lon: number) {
  if (!autoFetchEnabled) return;           // ← bouton désactivé
  if (!expanded) return;
  if (isFetchingModel) return;
  if (Date.now() - lastModelFetch < 30_000) return;
  if (!isUserIdle()) {
    // Pas encore idle — replanifier dans 60s
    setTimeout(() => fetchAllModelData(lat, lon), 60_000);
    return;
  }

  isFetchingModel = true;
  abortFetch = false;
  lastModelFetch = Date.now();
  console.log('%c[WINDY MODEL] Starting fetch (user idle)...', 'color:cyan');

  const userOverlay = store.get('overlay');
  const overlays = ['wind', 'gust', 'temp', 'pressure', 'waves', 'swell', 'currents', 'sst', 'clouds', 'fog', 'visibility'];
  const raw: Record<string, any> = {};

  for (const overlay of overlays) {
    // ← Interruption si l'utilisateur reprend la main
    if (abortFetch) {
      console.log('%c[WINDY MODEL] Aborted — user activity detected', 'color:orange');
      try { store.set('overlay', userOverlay); } catch(e) {}
      isFetchingModel = false;
      // Replanifier après 60s d'inactivité
      setTimeout(() => fetchAllModelData(lat, lon), 60_000);
      return;
    }

    store.set('overlay', overlay);
    await waitForRedraw(6000);
    await sleep(300);

    if (abortFetch) continue; // sortir proprement

    try {
      const interpolateLatLon = await getLatLonInterpolator();
      if (!interpolateLatLon) {
        raw[overlay] = null;
        continue;
      }
      const result = await Promise.resolve(interpolateLatLon({ lat, lon }));
      raw[overlay] = Array.isArray(result) ? result : null;
    } catch(e) {
      raw[overlay] = null;
    }
  }

  try { store.set('overlay', userOverlay); } catch(e) {}

  if (!abortFetch) {
    parseModelResults(raw);
    logModelWeather(lat, lon);
  }

  isFetchingModel = false;
}







function waitForRedraw(timeout: number): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, timeout);
    bcast.once('redrawFinished', () => {
      clearTimeout(t);
      resolve();
    });
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}



// Variable globale pour suivre l'état de la progress-bar
let progressBarOpen = false;
// Dans onMount :
bcast.on('pluginOpened', (name: string) => { if (name === 'progress-bar') progressBarOpen = true; });
bcast.on('pluginClosed', (name: string) => { if (name === 'progress-bar') progressBarOpen = false; });


// ============================================================
// PARSE DES RÉSULTATS BRUTS
// ============================================================

function parseModelResults(results: Record<string, any>) {

  // VENT — [u, v, 0] m/s
  const w = results['wind'];
  if (Array.isArray(w) && w.length >= 2) {
    const u = w[0], v = w[1];
    modelWeather.windSpeed = Math.sqrt(u*u + v*v) * 1.94384;
    modelWeather.windDir   = (270 - Math.atan2(v, u) * 180 / Math.PI + 360) % 360;
  }

  // RAFALES — [speed_ms, 0, 0]
  const g = results['gust'];
  if (Array.isArray(g) && g[0] > 0) {
    modelWeather.gustSpeed = g[0] * 1.94384;
    // Direction des rafales = même que le vent
    modelWeather.gustDir = modelWeather.windDir;
  }

  // TEMP AIR — [kelvin, 0, 0]
  const t = results['temp'];
  if (Array.isArray(t) && t[0] > 0) {
    modelWeather.airTemp = t[0] - 273.15;
  }

  // PRESSION — [pascal, 0, 0]
  const p = results['pressure'];
  if (Array.isArray(p) && p[0] > 0) {
    modelWeather.pressure = p[0] / 100;
  }

  // VAGUES — [u, v, hauteur_m]
  const wv = results['waves'];
  if (Array.isArray(wv) && wv.length >= 3) {
    modelWeather.wavesHeight = wv[2];
    modelWeather.wavesDir    = (270 - Math.atan2(wv[1], wv[0]) * 180 / Math.PI + 360) % 360;
  }

  // HOULE — [u, v, hauteur_m]
  const sw = results['swell'];
  if (Array.isArray(sw) && sw.length >= 3) {
    modelWeather.swellHeight = sw[2];
    modelWeather.swellDir    = (270 - Math.atan2(sw[1], sw[0]) * 180 / Math.PI + 360) % 360;
  }

  // COURANTS — [u, v, 0] m/s
  const c = results['currents'];
  if (Array.isArray(c) && c.length >= 2) {
    const u = c[0], v = c[1];
    modelWeather.currentSpeed = Math.sqrt(u*u + v*v) * 1.94384;
    modelWeather.currentDir   = (270 - Math.atan2(v, u) * 180 / Math.PI + 360) % 360;
  }

  // SST — [kelvin, 0, 0]
  const sst = results['sst'];
  if (Array.isArray(sst) && sst[0] > 0) {
    modelWeather.seaTempModel = sst[0] - 273.15;
  }

  // NUAGES — [fraction 0-1, 0, 0] ou [oktas 0-8]
  const cl = results['clouds'];
  if (Array.isArray(cl) && cl[0] != null) {
    console.log('[FORMAT] clouds raw:', cl);
    const fraction = cl[0]; // à confirmer selon l'unité
    modelWeather.clouds = fraction;
    modelWeather.cloudsLabel = cloudsToLabel(fraction);
  }

  // VISIBILITÉ — log brut pour confirmer l'unité
  const fog = results['fog'];
  const vis = results['visibility'];
  if (Array.isArray(fog)) console.log('[FORMAT] fog raw:', fog);
  if (Array.isArray(vis)) console.log('[FORMAT] visibility raw:', vis);

  // On prend le meilleur disponible
  const visRaw = vis ?? fog;
  if (Array.isArray(visRaw) && visRaw[0] != null) {
    modelWeather.visibility = visRaw[0]/1852; // unité : Miles Nautiques
  }
  
    // ============================================================
  // MISE À JOUR DES VARIABLES UI — uniquement données modèle
  // ============================================================

  const m = modelWeather;
  const fmtVal = (v: number | null, dec = 1) =>
    v != null && !isNaN(v) ? v.toFixed(dec) : '-';
  console.log('MISE A JOUR GRILLE');
  // Vent modèle
  windSpeedmodele = fmtVal(m.windSpeed);
  beaufortmodele  = m.windSpeed != null ? String(knotsToBeaufort(m.windSpeed)) : '-';

  // Rafales modèle
  gustsSpeedmodele = fmtVal(m.gustSpeed);
  gustsDirmodele   = fmtVal(m.gustDir, 0);

  // Vagues modèle (waves et swell n'ont pas de ligne capteur → on écrase directement)
  wavesHeight = fmtVal(m.wavesHeight, 2);
  wavesDir    = fmtVal(m.wavesDir, 0);
  swellHeight = fmtVal(m.swellHeight, 2);
  swellDir    = fmtVal(m.swellDir, 0);

  // Courants modèle
  currentSpeedModel = fmtVal(m.currentSpeed);
  currentDirModel = fmtVal(m.currentDir);
  // currentDir reste le cap calculé depuis les capteurs

  // Températures modèle
  airTempmodele  = fmtVal(m.airTemp);
  seaTempmodele  = fmtVal(m.seaTempModel);

  // Pression modèle
  pressuremodele = fmtVal(m.pressure, 0);

  // Ciel & visibilité (modèle uniquement, pas de capteur)
  cloudsInfo  = m.cloudsLabel ?? '-';
  visibility  = fmtVal(m.visibility, 1); // en Nm

  // Historique — on injecte la valeur modèle dans les series existantes
  const now = Date.now();
  if (m.windSpeed != null)  history.wind.push({ t: now, sensor: null, model: m.windSpeed });
  if (m.gustSpeed != null)  history.gusts.push({ t: now, sensor: null, model: m.gustSpeed });
  if (m.airTemp != null)    history.air.push({ t: now, sensor: null, model: m.airTemp });
  if (m.seaTempModel != null) history.sea.push({ t: now, sensor: null, model: m.seaTempModel });
  if (m.pressure != null)   history.pressure.push({ t: now, sensor: null, model: m.pressure });
  if (m.currentSpeed != null) history.current.push({ t: now, sensor: null, model: m.currentSpeed });
updateStatusDots();
}




// Conversion fraction nuageuse → label météo standard
function cloudsToLabel(fraction: number): string {
  // Windy retourne probablement 0-1
  const oktas = fraction <= 1 ? fraction * 8 : fraction; // si déjà en oktas

  if (oktas <= 1)  return 'Clear ☀️';
  if (oktas <= 2)  return 'Few clouds 🌤️';
  if (oktas <= 4)  return 'Partly cloudy ⛅';
  if (oktas <= 6)  return 'Mostly cloudy 🌥️';
  if (oktas <= 7)  return 'Overcast 🌫️';
  return 'Overcast ☁️';
}









// ============================================================
// LOG CONSOLE FORMATÉ
// ============================================================
function logModelWeather(lat: number, lon: number) {
  const m = modelWeather;
  const model = store.get('product') ?? 'unknown';
  const ts = new Date(store.get('timestamp') ?? Date.now()).toUTCString();

  console.group(
    `%c🌍 MODEL WEATHER @ [${lat.toFixed(4)}, ${lon.toFixed(4)}]`,
    'color:#e5533d; font-weight:bold; font-size:13px'
  );
  console.log(`%cModel: ${model}  |  Time: ${ts}`, 'color:#aaa; font-size:11px');

  console.groupCollapsed('%c💨 WIND & GUSTS', 'color:#3ecf8e; font-weight:bold');
  console.log('Wind speed :', fmt(m.windSpeed, 'kt'));
  console.log('Wind dir   :', fmt(m.windDir,   '°'));
  console.log('Gusts      :', fmt(m.gustSpeed, 'kt'));
  console.groupEnd();

  console.groupCollapsed('%c🌊 WAVES & SWELL', 'color:#197AFF; font-weight:bold');
  console.log('Wave height:', fmt(m.wavesHeight, 'm'));
  console.log('Wave dir   :', fmt(m.wavesDir,    '°'));
  console.log('Swell Hs   :', fmt(m.swellHeight, 'm'));
  console.log('Swell dir  :', fmt(m.swellDir,    '°'));
  console.groupEnd();

  console.groupCollapsed('%c🌀 CURRENTS', 'color:#FFCE1F; font-weight:bold');
  console.log('Speed :', fmt(m.currentSpeed, 'kt'));
  console.log('Dir   :', fmt(m.currentDir,   '°'));
  console.groupEnd();

  console.groupCollapsed('%c🌡️ TEMP & PRESSURE', 'color:#F7997C; font-weight:bold');
  console.log('Air temp  :', fmt(m.airTemp,      '°C'));
  console.log('Sea temp  :', fmt(m.seaTempModel, '°C'));
  console.log('Pressure  :', fmt(m.pressure,     'hPa'));
  console.groupEnd();
  
  console.groupCollapsed('%c☁️ SKY & VISIBILITY', 'color:#F7997C; font-weight:bold');
  console.log(`☁️ Sky   : ${m.cloudsLabel ?? '⛔ unavailable'}`);
  console.log(`👁 Vis   : ${fmt(m.visibility, 'm')}`);
  console.groupEnd();
  console.groupEnd();
}

function fmt(val: number | null, unit: string): string {
  if (val == null || isNaN(val)) return '⛔ unavailable';
  return `${val.toFixed(2)} ${unit}`;
}




/////////////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////////////

// ============================================================
// DÉTECTION D'INACTIVITÉ — fetch seulement si idle 60s
// ============================================================

let lastUserActivity = Date.now();
let idleTimer: number | null = null;
let autoFetchEnabled = true; // ← bouton frontend

function resetActivityTimer() {
  lastUserActivity = Date.now();
  // Si un fetch est en cours → l'interrompre
  if (isFetchingModel) {
    abortFetch = true;
  }
}

// Variable pour interrompre le fetch en cours
let abortFetch = false;

onMount(() => {
  // Écoute toutes les interactions utilisateur avec la carte
  const events = ['mousedown', 'mousemove', 'wheel', 'touchstart', 'keydown'];
  events.forEach(e => window.addEventListener(e, resetActivityTimer, { passive: true }));

  // Écoute aussi les interactions Windy (déplacement carte, changement overlay)
  bcast.on('map:movestart', resetActivityTimer);
  bcast.on('rqstOpen', resetActivityTimer);
});

onDestroy(() => {
  stopCOM();
  stopTCP();

  const events = ['mousedown', 'mousemove', 'wheel', 'touchstart', 'keydown'];
  events.forEach(e => window.removeEventListener(e, resetActivityTimer));

  bcast.off('map:movestart', resetActivityTimer);
  bcast.off('rqstOpen', resetActivityTimer);
});

function isUserIdle(): boolean {
  return Date.now() - lastUserActivity > 60_000; // 60 secondes
}








function updateWeather(lat, lon){
console.log('updating weather');
weather = getAllWeatherAtBoat(lat, lon);
console.log('weather updated');
logWeatherToConsole(weather);
console.log('weather shown');
}

function logWeatherToConsole(weather) {
  if (!weather) return;

  console.group(
    `%c🌬️ Weather @ boat (${weather.wind.model})`,
    'color:#e5533d;font-weight:bold'
  );

  console.log('☁️ Clouds:', weather.clouds);
  console.log('👁 Visibility:', weather.visibility);

  console.log('🌊 Currents:', weather.currents);
  console.log('🌊 Waves:', weather.waves);
  console.log('🌊 Swell:', weather.swell);

  console.log('💨 Wind:', weather.wind);
  console.log('💨 Gusts:', weather.gusts);

  console.log('🌡 Air temp:', weather.airTemp);
  console.log('🌡 Sea temp:', weather.waterTemp);
  console.log('⏲ Pressure:', weather.pressure);

  console.groupEnd();
}

function parseGLL(sentence) {
  const p = sentence.split(',');

  // p[6] === 'A' → valid data
  if (p.length < 7 || p[6] !== 'A') return;

  const lat = parseCoord(p[1], p[2]);
  const lon = parseCoord(p[3], p[4]);

  if (isNaN(lat) || isNaN(lon)) return;

  const newLat = lat;
  const newLon = lon;

  if (lastLatitude !== null && lastLongitude !== null) {
    courseOverGround = calculateBearing(
      lastLatitude,
      lastLongitude,
      newLat,
      newLon
    );
  }

  lastLatitude = newLat;
  lastLongitude = newLon;

  latitude = newLat;
  longitude = newLon;
  updatePosition(newLat, newLon, 'GLL');
  //addBoatMarker(newLat, newLon, courseOverGround);
  //updateWeather(latitude, longitude);
}





function parseCoord(value, hemi) {
  const v = parseFloat(value);
  const deg = Math.floor(v / 100);
  const min = v - deg * 100;

  let res = deg + min / 60;
  if (hemi === 'S' || hemi === 'W') res = -res;
  return res;
}



function calculateBearing(lat1, lon1, lat2, lon2) {
  const φ1 = toRadians(lat1);
  const φ2 = toRadians(lat2);
  const Δλ = toRadians(lon2 - lon1);

  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x =
    Math.cos(φ1) * Math.sin(φ2) -
    Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);

  let θ = Math.atan2(y, x); // radians
  θ = toDegrees(θ);

  return (θ + 360) % 360; // normalisé 0–360°
}

function toRadians(deg) {
  return deg * Math.PI / 180;
}

function toDegrees(rad) {
  return rad * 180 / Math.PI;
}



function addBoatMarker(
  lat: number,
  lon: number,
  cog: number
) {
  if (!map || lat == null || lon == null) return;

  const pos = L.latLng(lat, lon);

  /* =========================
     TRACE (PATH)
  ========================= */
  pathLatLngs.push(pos);

  if (!boatPath) {
    boatPath = L.polyline(pathLatLngs, {
      color: '#e5533d',
      weight: 3,
      opacity: 0.8
    }).addTo(markerLayer);
  } else {
    boatPath.setLatLngs(pathLatLngs);
  }

  /* =========================
     BOAT ICON (ARROW)
  ========================= */
  const boatIcon = L.divIcon({
    className: 'boat-arrow',
    html: `
      <svg viewBox="0 0 100 100"
           width="40"
           height="40"
           style="transform: rotate(${cog}deg)">
        <polygon
          points="50,0 90,100 50,80 10,100"
          fill="#e5533d"
          stroke="black"
          stroke-width="3"
        />
      </svg>
    `,
    iconSize: [40, 40],
    iconAnchor: [20, 20]
  });

  /* =========================
     MARKER UPDATE
  ========================= */
  if (!boatMarker) {
    boatMarker = L.marker(pos, { icon: boatIcon }).addTo(markerLayer);
  } else {
    boatMarker.setLatLng(pos);
    boatMarker.setIcon(boatIcon);
  }

  /* =========================
     FOLLOW SHIP
  ========================= */
  if (followShip) {
    map.setView(pos, map.getZoom(), { animate: false });
  }
}

interface WindyValue {
  value?: number;
  speed?: number;
  direction?: number;
  unit: string;
  model: string;
  available: boolean;
}

interface WeatherAtBoat {
  clouds: WindyValue;
  visibility: WindyValue;
  currents: WindyValue;
  waves: WindyValue;
  swell: WindyValue;
  wind: WindyValue;
  gusts: WindyValue;
  airTemp: WindyValue;
  waterTemp: WindyValue;
  pressure: WindyValue;
}

function interpolatePoint({
  lat,
  lon,
  product,
  overlay,
  level = 'surface'
}: {
  lat: number;
  lon: number;
  product: string;
  overlay: string;
  level?: string;
}) {
  const model = store.get('model');
  const timestamp = store.get('timestamp');

  const res = interpolator.interpolate({
    lat,
    lon,
    model,
    product,
    overlay,
    level,
    timestamp
  });

  if (!res) {
    return { available: false, model };
  }

  return { ...res, available: true, model };
}

function setupWindyPicker() {
  // Place le picker sur la position du bateau
  if (latitude == null || longitude == null) return;

  bcast.fire('rqstOpen', 'picker', { lat: latitude, lon: longitude });
}

function safeInterpolate(
  layer: string,
  lat: number,
  lon: number
): number | null {
  try {
    const overlays = store.get('overlays');

    if (!overlays || !overlays[layer]) {
      console.warn(`⛔ Layer not available: ${layer}`);
      return null;
    }

    const value = interpolator.interpolate(layer, lat, lon);

    if (value == null || Number.isNaN(value)) {
      return null;
    }

    return value;
  } catch (err) {
    console.warn(`⚠️ Interpolation failed for ${layer}`, err);
    return null;
  }
}

function centerShip() {
  if (latitude != null && longitude != null) {
    map.setView([latitude, longitude], map.getZoom(), { animate: true });
  }
}



$: {
  if (showAIS) {
    if (!map.hasLayer(aisLayer)) map.addLayer(aisLayer);
  } else {
    if (map.hasLayer(aisLayer)) map.removeLayer(aisLayer);
  }
}



interface AISTarget {
    mmsi: number;

    lat?: number;
    lon?: number;
    cog?: number;
    sog?: number;
    heading?: number | null;

    shipType?: number;
    name?: string;

    lastUpdate: number;

    marker?: L.Marker;
    vector?: L.Polyline;
}

const aisTargets = new Map<number, AISTarget>();
const aisFragments = new Map<string, string[]>();


/* ===================== PARSEUR PRINCIPAL ===================== */

function parseAIS(nmea: string) {
    if (!nmea.startsWith('!AI')) return;

    const parts = nmea.split(',');
    const total = Number(parts[1]);
    const num = Number(parts[2]);
    const seq = parts[3] || '0';
    const channel = parts[4] || 'A';
    const payload = parts[5];
    const fillBits = Number(parts[6]?.split('*')[0] ?? 0);

    const fragmentKey = `${seq}-${channel}`;

    if (total > 1) {
        if (!aisFragments.has(fragmentKey)) {
            aisFragments.set(fragmentKey, { payloads: [], fillBits: 0 });
        }

        const entry = aisFragments.get(fragmentKey)!;
        entry.payloads[num - 1] = payload;

        if (num === total) {
            entry.fillBits = fillBits;
        }

        if (entry.payloads.filter(Boolean).length !== total) return;

        const fullPayload = entry.payloads.join('');
        const finalFillBits = entry.fillBits;

        aisFragments.delete(fragmentKey);

        // 🔹 Seul !AIVDO déclenche updatePosition
        if (nmea.startsWith('!AIVDO')) {
            decodeAISPayload(fullPayload, finalFillBits, true);
        } else {
            decodeAISPayload(fullPayload, finalFillBits, false);
        }
    } else {
        decodeAISPayload(payload, fillBits, nmea.startsWith('!AIVDO'));
    }
}

// Ajout d’un paramètre “ownShip” pour savoir si c’est la position du bateau
function decodeAISPayload(payload: string, fillBits: number, ownShip = false) {
    const bits = aisPayloadToBits(payload, fillBits);
    const type = getInt(bits, 0, 6);

    switch (type) {
        case 1:
        case 2:
        case 3:
        case 18:
            parseAISPosition(bits, ownShip);
            break;

        case 5:
            parseAISStatic(bits);
            break;

        case 21:
            parseAtoN(bits);
            break;
    }
}



/* ===================== DÉCODAGE ===================== */




function aisPayloadToBits(payload: string, fillBits: number): string {
    let bits = '';

    for (const char of payload) {
        let value = char.charCodeAt(0) - 48;
        if (value > 40) value -= 8;
        bits += value.toString(2).padStart(6, '0');
    }

    if (fillBits > 0) {
        bits = bits.slice(0, bits.length - fillBits);
    }

    return bits;
}


function getInt(bits: string, start: number, length: number, signed = false): number {
    const slice = bits.slice(start, start + length);
    let val = parseInt(slice, 2);
    if (signed && slice[0] === '1') val -= 1 << length;
    return val;
}

/* ===================== DYNAMIQUE ===================== */

function parseAISPosition(bits: string, ownShip = false) {
    const lat = getInt(bits, 89, 27, true) / 600000;
    const lon = getInt(bits, 61, 28, true) / 600000;
    const cog = getInt(bits, 116, 12) / 10;
    const sog = getInt(bits, 50, 10) / 10;
    const headingRaw = getInt(bits, 128, 9);
    const mmsi = getInt(bits, 8, 30);
    const now = Date.now();

    let t = aisTargets.get(mmsi);
    if (!t) {
        t = { mmsi, lastUpdate: now };
        aisTargets.set(mmsi, t);
    }

    t.lat = lat;
    t.lon = lon;
    t.cog = cog;
    t.sog = sog;
    t.heading = headingRaw !== 511 ? headingRaw : null;
    t.lastUpdate = now;

    updateAISTarget(t);

    // 🔹 Si c’est une trame !AIVDO, c’est la position du bateau
    if (ownShip) {
        updatePosition(lat, lon, 'AIS');
        courseOverGround = cog;

        if (!isNaN(sog) && sog >= 0) {
            history.current.push({ t: now, sensor: sog, model: null });
        }
    }
}



/* ===================== STATIQUE ===================== */

function parseAISStatic(bits: string) {
    console.log("Parse AIS STATIC");
    const mmsi = getInt(bits, 8, 30);
    const shipType = getInt(bits, 232, 8);
    const nameBits = bits.slice(112, 232);
    const name = aisBitsToText(nameBits).trim();

    let t = aisTargets.get(mmsi);
    if (!t) {
        t = { mmsi, lastUpdate: Date.now() };
        aisTargets.set(mmsi, t);
    }

    t.shipType = shipType;
    t.name = name;
    console.log("shipType= ",t.shipType," name= ",t.name);
    updateAISTarget(t);
}

/* ===================== AtoN ===================== */

function parseAtoN(bits: string) {
    const mmsi = getInt(bits, 8, 30);
    const lon = getInt(bits, 61, 28, true) / 600000;
    const lat = getInt(bits, 89, 27, true) / 600000;

    let t = aisTargets.get(mmsi);
    if (!t) {
        t = { mmsi, lastUpdate: Date.now() };
        aisTargets.set(mmsi, t);
    }

    t.lat = lat;
    t.lon = lon;
    t.shipType = 21;

    updateAISTarget(t);
}

/* ===================== UPDATE GLOBAL ===================== */

function updateAISTarget(t: AISTarget) {
    if (t.lat == null || t.lon == null) return;

    updateAISMarker(t);
    updateAISVector(t);
}

/* ===================== MARKER ===================== */

function updateAISMarker(t: AISTarget) {
    const style = getAISStyle(t.shipType ?? 0);

    const shape =
        t.shipType === 21
            ? `<rect x="4" y="4" width="12" height="12"
                transform="rotate(45 10 10)" fill="${style.color}" />`
            : `<polygon points="10,0 18,20 10,15 2,20" fill="${style.color}" />`;

    const icon = L.divIcon({
        html: `
            <svg width="20" height="20" style="transform: rotate(${t.cog ?? 0}deg)">
                ${shape}
            </svg>
            <div style="font-size:10px;color:white;white-space:nowrap">
                ${t.name || t.mmsi}
            </div>
        `,
        iconSize: [20, 20],
        iconAnchor: [10, 10]
    });

    if (!t.marker) {
        t.marker = L.marker([t.lat!, t.lon!], { icon }).addTo(aisLayer);
    } else {
        t.marker.setLatLng([t.lat!, t.lon!]);
        t.marker.setIcon(icon);
    }
}

/* ===================== VECTEUR ===================== */

function updateAISVector(t: AISTarget) {
    if (t.vector && aisLayer.hasLayer(t.vector)) {
        aisLayer.removeLayer(t.vector);
    }
    t.vector = undefined;

    if (!t.sog || !t.cog || t.sog < 0.2) return;

    const distNm = t.sog * 0.1;
    const future = projectPoint(t.lat!, t.lon!, t.cog, distNm);
    const style = getAISStyle(t.shipType ?? 0);

    t.vector = L.polyline(
        [[t.lat!, t.lon!], future],
        { color: style.color, weight: 1, dashArray: '4,4' }
    );

    t.vector.addTo(aisLayer);
}

/* ===================== STYLES ===================== */

function getAISStyle(shipType: number) {
    if (shipType >= 70 && shipType <= 79) return { color: '#90EE90' }; // cargo
    if (shipType >= 80 && shipType <= 89) return { color: '#FF3125' }; // tanker
    if (shipType >= 60 && shipType <= 69) return { color: '#197AFF' }; // pax
    if (shipType >= 40 && shipType <= 49) return { color: '#FFCE1F' }; // HSC
    if (shipType >= 50 && shipType <= 59) return { color: '#26F5F5' }; // tug
    if (shipType >= 30 && shipType <= 39) return { color: '#F7997C' }; // fishing
    if (shipType === 21) return { color: '#FFFFFF' };                  // AtoN
    return { color: '#FFFFFF' };                                       // unspecified
}

/* ===================== UTILS ===================== */

function aisBitsToText(bits: string): string {
    let text = '';
    for (let i = 0; i < bits.length; i += 6) {
        let v = parseInt(bits.slice(i, i + 6), 2);
        if (v < 32) v += 64;
        text += String.fromCharCode(v);
    }
    return text.replace(/@/g, '');
}

function projectPoint(lat: number, lon: number, cog: number, distNm: number): [number, number] {
    const R = 6371;
    const d = distNm * 1.852 / R;
    const brng = cog * Math.PI / 180;

    const φ1 = lat * Math.PI / 180;
    const λ1 = lon * Math.PI / 180;

    const φ2 = Math.asin(
        Math.sin(φ1) * Math.cos(d) +
        Math.cos(φ1) * Math.sin(d) * Math.cos(brng)
    );

    const λ2 = λ1 + Math.atan2(
        Math.sin(brng) * Math.sin(d) * Math.cos(φ1),
        Math.cos(d) - Math.sin(φ1) * Math.sin(φ2)
    );

    return [φ2 * 180 / Math.PI, λ2 * 180 / Math.PI];
}

/* ===================== NETTOYAGE ===================== */

setInterval(() => {
    const now = Date.now();
    for (const [mmsi, t] of aisTargets) {
        if (now - t.lastUpdate > 120_000) {
            if (t.marker) aisLayer.removeLayer(t.marker);
            if (t.vector) aisLayer.removeLayer(t.vector);
            aisTargets.delete(mmsi);
        }
    }
}, 30_000);

/*------------------------------------- AIS ------------------------------------------*/











let interval;





onDestroy(() => { stopCOM(); stopTCP(); });



function startTCP() {
  stopCOM();
  if (tcpRunning) return;

  tcpRunning = true;
  tcpInterval = setInterval(fetchTCPData, 500);
  fetchTCPData();
}

function stopTCP() {
  if (tcpInterval) {
    clearInterval(tcpInterval);
    tcpInterval = null;
  }
  tcpRunning = false;
}

function hidePlugin() {
  // Ouvre le menu Windy (ferme visuellement le plugin)
  minimized = false;
  
}
 let expanded = false;
  function toggle() {
    expanded = !expanded;
  }
  function formatCoord(value: number | null) {
  if (value == null || isNaN(value)) return '--';
  return value.toFixed(3);
}




// ============================================================
// REMPLACE les deux lignes orphelines à la racine du script :
//   bcast.on('pluginOpened', ...)
//   bcast.on('pluginClosed', ...)
// ET ajoute onMount juste avant onDestroy
// ============================================================

onMount(() => {
  setTimeout(() => {
    console.log('%c[PROBE] interpolator:', 'color:cyan', interpolator);
    console.log('%c[PROBE] keys:', 'color:cyan', Object.keys(interpolator ?? {}));

    // Test direct avec position actuelle
    if (latitude != null) {
      try {
        const r = (interpolator as any).interpolate(latitude, longitude);
        console.log('%c[PROBE] result:', 'color:lime', r);
      } catch(e) {
        console.warn('[PROBE] failed:', e);
      }
    }
  }, 5000);
});





// ============================================================
// STATUS DOTS — logique correcte
// 🟢 ok    : capteur dispo ET écart < 20% avec modèle
// 🟡 warn  : capteur absent (affiche "-")
// 🔴 bad   : capteur dispo MAIS écart > 20% avec modèle
// ============================================================
type TileStatus = 'ok' | 'warn' | 'bad';

let statusWind:     TileStatus = 'warn';
let statusGusts:    TileStatus = 'warn';
let statusAir:      TileStatus = 'warn';
let statusSea:      TileStatus = 'warn';
let statusPressure: TileStatus = 'warn';
let statusCurrent:  TileStatus = 'warn';

function pct(sensor: number, model: number): number {
  if (model === 0) return sensor === 0 ? 0 : 100;
  return Math.abs(sensor - model) / Math.abs(model);
}

function updateStatusDots() {
  const m = modelWeather;

  // ── VENT ──
  const ws = parseFloat(windSpeed as string);
  if (isNaN(ws) || windSpeed === '-') {
    statusWind = 'warn'; // capteur absent
  } else if (m.windSpeed != null) {
    statusWind = pct(ws, m.windSpeed) <= 0.20 ? 'ok' : 'bad';
  } else {
    statusWind = 'warn'; // pas encore de modèle
  }

  // ── RAFALES ──
  const gs = parseFloat(gustsSpeed as string);
  if (isNaN(gs) || gustsSpeed === '-') {
    statusGusts = 'warn';
  } else if (m.gustSpeed != null) {
    statusGusts = pct(gs, m.gustSpeed) <= 0.20 ? 'ok' : 'bad';
  } else {
    statusGusts = 'warn';
  }

  // ── AIR TEMP ──
  const at = parseFloat(airTemp as string);
  if (isNaN(at) || airTemp === '-') {
    statusAir = 'warn';
  } else if (m.airTemp != null) {
    statusAir = Math.abs(at - m.airTemp) <= 2 ? 'ok' : 'bad'; // °C absolu
  } else {
    statusAir = 'warn';
  }

  // ── SEA TEMP ──
  const st = parseFloat(seaTemp as string);
  if (isNaN(st) || seaTemp === '-') {
    statusSea = 'warn';
  } else if (m.seaTempModel != null) {
    statusSea = Math.abs(st - m.seaTempModel) <= 2 ? 'ok' : 'bad';
  } else {
    statusSea = 'warn';
  }

  // ── PRESSION ──
  const pr = parseFloat(pressure as string);
  if (isNaN(pr) || pressure === '-') {
    statusPressure = 'warn';
  } else if (m.pressure != null) {
    statusPressure = Math.abs(pr - m.pressure) <= 2 ? 'ok' : 'bad'; // hPa absolu
  } else {
    statusPressure = 'warn';
  }

  // ── COURANT ──
  const cs = parseFloat(currentSpeed as string);
  if (isNaN(cs) || currentSpeed === '-') {
    statusCurrent = 'warn';
  } else if (m.currentSpeed != null) {
    statusCurrent = pct(cs, m.currentSpeed) <= 0.20 ? 'ok' : 'bad';
  } else {
    statusCurrent = 'warn';
  }
}











</script>
<!-- WIDGET EMBEDDED (droite) -->
<div class="plugin-mini">
  <div class="plugin-mini-content">
    🛳️ <strong>LAT</strong> {formatCoord(latitude)}° ·
    <strong>LON</strong> {formatCoord(longitude)}°
  </div>
 
        <div class="button size-s" on:click={toggle}>
        {expanded ? 'Hide' : 'Show'}
      </div>
</div>




{#if expanded}
  <div class="left-panel">
    <div class="left-header">
      <strong>{title}</strong>
      <button on:click={toggle}>✕</button>
    </div>


<section class="plugin__content">
  <div class="content">
    <!-- CONNECTION -->
    <div class="tile full">
      <div class="tile__title">Connection</div>

      <nav class="switch switch--variant-red-light size-s">
        <a class="switch__item {connectionType === 'TCP' ? 'selected' : ''}"
           on:click={() => connectionType = 'TCP'}>TCP</a>
        <a class="switch__item {connectionType === 'COM' ? 'selected' : ''}"
           on:click={() => connectionType = 'COM'}>COM</a>
      </nav>
      <!--{error ?? '--'}-->

      {#if connectionType === 'COM'}
        <select class="select" bind:value={baudRate}>
          <option value={4800}>4800 Bauds</option>
          <option value={9600}>9600 Bauds</option>
          <option value={38400}>38400 Bauds</option>
          <option value={115200}>115200 Bauds</option>
        </select>
      {/if}
      {#if connectionType === 'COM'}
          <div class="button size-s" on:click={connectCOM}>Connect COM</div>
          <div class="button size-s" on:click={stopCOM}>Disconnect COM</div>
      {/if}

    </div>

    <!-- ACTIONS -->
    <div class="tile full actions">
      <div class="button size-s" on:click={centerShip}>Center ship</div>

      <div
        class="button size-s {followShip ? 'button--variant-red' : ''}"
        on:click={toggleFollowShip}>
        {followShip ? 'Stop follow' : 'Follow ship'}
      </div>

      <div class="button size-s" on:click={() => showAIS = !showAIS}>
        {showAIS ? 'Hide AIS' : 'Show AIS'}
      </div>
    </div>

    <!-- POSITION -->
    <div class="tile full center">
      <strong>LAT</strong> {latitude ?? '--'}° &nbsp;|&nbsp;
      <strong>LON</strong> {longitude ?? '--'}°
    </div>
<!-- AUTO FETCH CONTROL -->
<div class="tile full">
  <div class="tile__title">Model data</div>
  <div class="tile__row" style="justify-content: space-between; align-items: center;">
    <span style="font-size:12px; opacity:0.8">
      {#if !autoFetchEnabled}
        ⏸ Auto-fetch disabled
      {:else if isFetchingModel}
        ⏳ Fetching...
      {:else if isUserIdle()}
        ✅ Ready — fetches when idle
      {:else}
        💤 Waiting for idle (60s)
      {/if}
    </span>
    <div
      class="button size-s {autoFetchEnabled ? 'button--variant-red' : ''}"
      on:click={() => {
        autoFetchEnabled = !autoFetchEnabled;
        if (!autoFetchEnabled && isFetchingModel) abortFetch = true;
      }}
    >
      {autoFetchEnabled ? '⏹ Stop auto' : '▶ Start auto'}
    </div>
  </div>

  <!-- Timestamp dernier fetch -->
  {#if lastModelFetch > 0}
    <div class="sub" style="margin-top:6px; opacity:0.5; font-size:10px;">
      Last update: {new Date(lastModelFetch).toLocaleTimeString()}
    </div>
  {/if}
</div>

    <!-- SKY -->
    <div class="tile full">
      <div class="tile__title">Sky & visibility</div>
      <div class="tile__row">
        <span class="icon">☁️</span>
        <div>
          <div>{cloudsInfo}</div>
          <div class="sub">Visibility: {visibility} Nm</div>
          <!--<div class="sub alert">Worst azimuth: {badVisAzimuth}°</div>-->
        </div>
      </div>
    </div>

    <!-- CURRENT ---------------------------------------------------------------------->
<div class="tile half clickable"
  class:status-ok={statusCurrent === 'ok'}
  class:status-warn={statusCurrent === 'warn'}
  class:status-bad={statusCurrent === 'bad'}
  class:active={expandedTile === 'current'}
  on:click={() => expandedTile = expandedTile === 'current' ? '' : 'current'}
>

  <span class="status-dot" title="Sensor matches the model"></span>
      <div class="tile__title">Current</div>
      <div class="tile__row">
        <span class="arrow" style="transform:rotate({currentDir}deg)">↑</span>
        <div class="value">{currentSpeed} kt</div>
        <span class="sensor">Calculated</span>
      </div>
      <div class="tile__row">
        <span class="arrow" style="transform:rotate({currentDirModel}deg)">↑</span>
        <div class="value">{currentSpeedModel} kt</div>
        <span class="sensor">Model</span>
      </div>
    </div>

    <!-- WAVES ---------------------------------------------------------------------->
    <div class="tile half clickable" 
  class:active={expandedTile === 'waves'}
  on:click={() => expandedTile = expandedTile === 'waves' ? '' : 'waves'}
>
      <div class="tile__title">Waves</div>
      <div class="tile__row">
        <span class="arrow" style="transform:rotate({wavesDir}deg)">↑</span>
        <div class="value">{wavesHeight} m</div>
        <span class="sensor">{sensor.waves}</span>
      </div>
    </div>

    <!-- SWELL ---------------------------------------------------------------------->
    <div class="tile half clickable" 
  class:active={expandedTile === 'swell'}
  on:click={() => expandedTile = expandedTile === 'swell' ? '' : 'swell'}
>
      <div class="tile__title">Swell</div>
      <div class="tile__row">
        <span class="arrow" style="transform:rotate({swellDir}deg)">↑</span>
        <div class="value">{swellHeight} m</div>
        <span class="sensor">{sensor.swell}</span>
      </div>
    </div>

    <!-- WIND ---------------------------------------------------------------------->
<div class="tile half clickable"
  class:status-ok={statusWind === 'ok'}
  class:status-warn={statusWind === 'warn'}
  class:status-bad={statusWind === 'bad'}
  class:active={expandedTile === 'wind'}
  on:click={() => expandedTile = expandedTile === 'wind' ? '' : 'wind'}
>

  <span class="status-dot" title="Sensor matches the model"></span>
      <div class="tile__title">Wind</div>
      <div class="tile__row">
        <span class="arrow" style="transform:rotate({windDir}deg)">↑</span>
        <div>
          <div class="value">{windSpeed} kt</div>
          <div class="sub">Beaufort {beaufort}</div>
        </div>
        <span class="sensor">{sensor.wind}</span>
      </div>
      <div class="tile__row">
        <span class="arrow" style="transform:rotate({windDir}deg)">↑</span>
        <div>
          <div class="value">{windSpeedmodele} kt</div>
          <div class="sub">Beaufort {beaufortmodele}</div>
        </div>
        <span class="sensor">Model</span>
      </div>
    </div>

    <!-- GUSTS ---------------------------------------------------------------------->
<div class="tile half clickable"
  class:status-ok={statusGusts === 'ok'}
  class:status-warn={statusGusts === 'warn'}
  class:status-bad={statusGusts === 'bad'}
  class:active={expandedTile === 'gust'}
  on:click={() => expandedTile = expandedTile === 'gust' ? '' : 'gust'}
>
  <span class="status-dot" title="Sensor matches the model"></span>
      <div class="tile__title">Gusts</div>
      <div class="tile__row">
        <span class="arrow" style="transform:rotate({gustsDir}deg)">↑</span>
        <div class="value">{gustsSpeed} kt</div>
        <span class="sensor">{sensor.gusts}</span>
      </div>
      <div class="tile__row">
        <span class="arrow" style="transform:rotate({gustsDirmodele}deg)">↑</span>
        <div class="value">{gustsSpeedmodele} kt</div>
        <span class="sensor">Model</span>
      </div>
    </div>

<!-- AIR TEMPERATURE ---------------------------------------------------------------------->
<div class="tile half clickable"
  class:status-ok={statusAir === 'ok'}
  class:status-warn={statusAir === 'warn'}
  class:status-bad={statusAir === 'bad'}
  class:active={expandedTile === 'air'}
  on:click={() => expandedTile = expandedTile === 'air' ? '' : 'air'}
>

  <span class="status-dot" title="Sensor matches the model"></span>

  <div class="tile__title">Air</div>

  <div class="tile__row">
    <span class="icon">🌡️</span>
    <div class="value">{airTemp} °C</div>
    <span class="sensor">{sensor.air}</span>
  </div>

  <div class="tile__row">
    <span class="icon opacity">🌡️</span>
    <div class="value opacity">{airTempmodele} °C</div>
    <span class="sensor">Model</span>
  </div>
</div>

<!-- SEA ---------------------------------------------------------------------->
<div class="tile half clickable"
  class:status-ok={statusSea === 'ok'}
  class:status-warn={statusSea === 'warn'}
  class:status-bad={statusSea === 'bad'}
  class:active={expandedTile === 'sea'}
  on:click={() => expandedTile = expandedTile === 'sea' ? '' : 'sea'}
>

  <span class="status-dot" title="Sensor matches the model"></span>
      <div class="tile__title">Sea</div>
      <div class="tile__row">
        <span class="icon">💧</span>
        <div class="value">{seaTemp} °C</div>
        <span class="sensor">{sensor.sea}</span>
      </div>
      <div class="tile__row">
        <span class="icon">💧</span>
        <div class="value">{seaTempmodele} °C</div>
        <span class="sensor">Model</span>
      </div>      
    </div>
    
<!-- PRESSURE ---------------------------------------------------------------------->    
<div class="tile half clickable"
  class:status-ok={statusPressure === 'ok'}
  class:status-warn={statusPressure === 'warn'}
  class:status-bad={statusPressure === 'bad'}
  class:active={expandedTile === 'pressure'}
  on:click={() => expandedTile = expandedTile === 'pressure' ? '' : 'pressure'}
>

  <span class="status-dot" title="Sensor matches the model"></span>
      <div class="tile__title">Pressure</div>
      <div class="tile__row">
        <span class="icon">🌀</span>
        <div class="value">{pressure} hPa</div>
        <span class="sensor">{sensor.pressure}</span>
      </div>
      <div class="tile__row">
        <span class="icon">🌀</span>
        <div class="value">{pressuremodele} hPa</div>
        <span class="sensor">Model</span>
      </div>
    </div>
    
    
<!-- GRAPHIQUE EVOLUTION DES DONEES ------------------------------------------------->   
{#if expandedTile}
<div class="history-panel">
  <div class="history-header">
    <strong>24h history</strong>
	<button class="button button--variant-gray size-xs"
        	on:click|stopPropagation={exportCSV}>
  		Export CSV
	</button>

  </div>

<div class="history-chart">
  {#if activeHistory.length === 0}
    <div class="empty-chart">
      No data yet
    </div>
  {:else}
  <svg viewBox="0 0 100 40" preserveAspectRatio="none">
    <!-- grid -->
    <line x1="0" y1="20" x2="100" y2="20" class="grid" />

    <!-- model curve -->
    <polyline
      class="curve model"
      points={modelPoints}
    />

    <!-- sensor curve -->
    <polyline
      class="curve sensor"
      points={sensorPoints}
    />
  </svg>
  {/if}
</div>


  <div class="history-legend">
    <span class="legend sensor">● Sensor</span>
    <span class="legend model">● Model</span>
  </div>
</div>
{/if}
    

    
    
    <!-- FOOTER -->
    <div class="button button--variant-red size-m full center"
         on:click={openTutorial}>
      🚀 Get started tutorial
    </div>

    <p class="footer">
      A plugin by <a href="https://yannkerherve.github.io/position-plugin/contact.html"><strong>Yann Kerhervé</strong></a> <a href="https://supmaritime.fr">(ENSM)</a>
    </p>
  </div>
</section>
</div>
{/if}

<style>
.plugin-mini {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: white;
  padding: 0px 0px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.2;
  margin: 2px 0;
  width: 100%; /* reste dans l'encart Windy */
  box-sizing: border-box;
}

.plugin-mini-content {
  flex: 1;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}


.left-plugin-root {
  padding: 12px;
  color: white;
  font-family: system-ui, sans-serif;
}
.left-panel {
  position: fixed;
  top: 60px;       
  left: 12px;      
  width: 360px;
  height: calc(100vh - 100px); 
  background: #0b1c48;
  color: white;
  z-index: 999;
  box-shadow: 3px 0 15px rgba(0,0,0,0.4);
  border-radius: 8px;
  padding: 10px;    
  box-sizing: border-box;
  overflow: hidden;   /* assure que les coins arrondis restent visibles */
}



.left-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  background: rgba(0,0,0,0.2);
  font-size: 14px;
}

  .content {
    padding: 10px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }

  .tile {
    background: rgba(255,255,255,0.05);
    border-radius: 8px;
    padding: 10px;
    position: relative;
  }

  .tile.full {
    grid-column: span 2;
  }
  .button.full {
    grid-column: span 2;
  }

  .tile.half {
    grid-column: span 1;
  }

  .tile__title {
    font-size: 12px;
    opacity: 0.6;
    margin-bottom: 6px;
  }

  .tile__row {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .tile__row .value {
  font-weight: 600;
}

.tile.clickable {
  cursor: pointer;
}

.tile.active {
  outline: 1px solid rgba(255,255,255,0.15);
}


.status-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-ok .status-dot {
  background: #3ecf8e; /* green */
}

.status-warn .status-dot {
  background: #f7b955; /* orange */
}

.status-bad .status-dot {
  background: #e5533d; /* red */
}

  .actions {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .center {
    text-align: center;
  }

  .value {
    font-weight: 600;
  }

  .sub {
    font-size: 11px;
    opacity: 0.7;
  }

  .alert {
    color: #e5533d;
  }

  .sensor {
    margin-left: auto;
    font-size: 10px;
    opacity: 0.4;
  }

  .arrow {
    font-size: 16px;
  }

  .icon {
    font-size: 18px;
  }

  .select {
    margin-top: 8px;
    width: 100%;
  }

  .footer {
    grid-column: span 2;
    text-align: center;
    font-size: 11px;
    opacity: 0.6;
  }
  
  .history-panel {
  grid-column: span 2;
  margin-top: 14px;
  padding: 12px;
  background: rgba(255,255,255,0.05);
  border-radius: 6px;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  margin-bottom: 8px;
}

.history-chart {
  height: 140px;
  background: rgba(255,255,255,0.08);
  border-radius: 4px;
}

.history-legend {
  display: flex;
  gap: 14px;
  font-size: 11px;
  opacity: 0.7;
  margin-top: 6px;
}

.legend.sensor { color: #3ecf8e; }
.legend.model  { color: #f7b955; }

.empty-chart {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  opacity: 0.5;
}
.history-chart svg {
  width: 100%;
  height: 140px;
}

.grid {
  stroke: rgba(255,255,255,0.15);
  stroke-width: 0.5;
}

.curve {
  fill: none;
  stroke-width: 1.5;
}

.curve.sensor {
  stroke: #3ecf8e;
}

.curve.model {
  stroke: #f7b955;
  stroke-dasharray: 4 3;
}

.boat-arrow svg {
  transition: transform 0.2s linear;
}


</style>




