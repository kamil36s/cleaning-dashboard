// render_weather_api.js

// helpers
const $ = s => document.querySelector(s);
const el = id => document.getElementById(id);
const fmt = v => (v == null || Number.isNaN(Number(v))) ? '—' : v;

// opisy warunków (Open-Meteo / MET Norway style)
const WX_DESC = {
  0:'Bezchmurnie',1:'Gł. słonecznie',2:'Częściowe zachmurzenie',3:'Pochmurno',
  45:'Mgła',48:'Szron/mgła',51:'Mżawka lekka',53:'Mżawka',55:'Mżawka intensywna',
  61:'Deszcz lekki',63:'Deszcz',65:'Ulewa',66:'Marznący deszcz',67:'Ulewa marznąca',
  71:'Śnieg lekki',73:'Śnieg',75:'Śnieg intensywny',77:'Ziarna lodowe',
  80:'Przelotny deszcz lekki',81:'Przelotny deszcz',82:'Ulewy przelotne',
  85:'Przelotny śnieg lekki',86:'Przelotny śnieg',95:'Burza',
  96:'Burza z gradem',99:'Silna burza z gradem'
};

// status
export function setStatus(text){
  const s = el('status') || el('wx-updated');
  if (s) s.textContent = text;
}

// skala Beauforta
const BFT = [
  { max: 1,   label: 'cisza' },
  { max: 5,   label: 'powiew' },
  { max: 11,  label: 'bardzo słaby' },
  { max: 19,  label: 'słaby' },
  { max: 28,  label: 'umiarkowany' },
  { max: 38,  label: 'dość silny' },
  { max: 49,  label: 'silny' },
  { max: 61,  label: 'bardzo silny' },
  { max: 74,  label: 'wichura' },
  { max: 88,  label: 'silna wichura' },
  { max: 102, label: 'gwałtowna wichura' },
  { max: 117, label: 'burza huraganowa' },
  { max: Infinity, label: 'huragan' },
];
const windLabel = v => BFT.find(b => (Number(v) || 0) <= b.max).label;

// TERAZ
export function renderNow(now){
  // duży wyświetlacz
  if (el('wx-temp')) el('wx-temp').textContent =
    `${fmt(Number(now.temp)?.toFixed?.(1))}°C`;
  if (el('wx-cond')) el('wx-cond').textContent = WX_DESC[now.code] ?? '—';

  // wartości
  const feels = Number(now.feels ?? now.temp);
  const hum   = Number(now.hum);
  const prcp  = Number(now.prcp);
  const cloud = Number(now.cloud);
  const wind  = Number(now.wind);
  const gust  = Number(now.gust);

  // pigułki z tooltipami + opis Beauforta przy wietrze
  const pills = [
    {
      key:'feels', icon:'🌡️', label:'Odczuwalna',
      value: isNaN(feels)? '—' : feels.toFixed(1), unit:'°C',
      tip:'Temperatura odczuwalna (uwzględnia wiatr i wilgotność)'
    },
    {
      key:'hum', icon:'💧', label:'Wilgotność',
      value: isNaN(hum)? '—' : hum, unit:'%',
      tip:'Wilgotność względna powietrza'
    },
    {
      key:'prcp', icon:'🌧️', label:'Opad',
      value: isNaN(prcp)? '—' : prcp, unit:'mm/h',
      tip:'Intensywność opadu w mm na godzinę'
    },
    {
      key:'cloud', icon:'☁️', label:'Zachmurzenie',
      value: isNaN(cloud)? '—' : cloud, unit:'%',
      tip:'Procent pokrycia nieba chmurami'
    },
    {
      key:'wind', icon:'💨', label:'Wiatr',
      value: isNaN(wind)? '—' : wind, unit:'km/h',
      extra: isNaN(wind)? '' : ` (${windLabel(wind)})`,
      tip:'Średnia prędkość wiatru (opis wg Beauforta)'
    },
    {
      key:'gust', icon:'💨💥', label:'Porywy',
      value: isNaN(gust)? '—' : gust, unit:'km/h',
      extra: isNaN(gust)? '' : ` (${windLabel(gust)})`,
      tip:'Maksymalne krótkie skoki prędkości wiatru'
    },
  ];

  const c = el('now');
  if (!c) return;

  c.innerHTML = pills.map(p => {
    const val = `${p.value}${p.unit}${p.extra ?? ''}`;
    return `
      <span class="pill" data-kind="${p.key}"
            title="${p.tip}"
            aria-label="${p.label}: ${val}"
            tabindex="0">
        <span class="pill-icon" aria-hidden="true">${p.icon}</span>
        <span class="pill-main">
          <span class="pill-value">${val}</span>
          <span class="pill-label">${p.label}</span>
        </span>
      </span>
    `;
  }).join('');
}

// NASTĘPNE GODZINY
export function renderNext(nextHours){
  const n = el('next');
  if (!n) return;
  const fmtTime = new Intl.DateTimeFormat('pl-PL',{hour:'2-digit',minute:'2-digit'});

  n.innerHTML =
    `<div class="hours-header">
       <span>Godz.</span><span>Temp</span><span>Opad</span><span>Wiatr</span>
     </div>` +
    nextHours.map(h => {
      const t    = fmtTime.format(new Date(h.timeIso));
      const temp = `${fmt(h.temp)}°C`;
      const prcp = `${fmt(h.prcp)} mm/h`;
      const wind = `${fmt(h.wind)} km/h <em>(${windLabel(+h.wind)})</em>`;
      return `<div class="hour-row">
                <span>${t}</span><span>${temp}</span><span>${prcp}</span><span>${wind}</span>
              </div>`;
    }).join('');
}
