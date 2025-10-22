import { COORDS, TIMEZONE } from '../config.js';

const HOURLY = [
  'temperature_2m',
  'relative_humidity_2m',
  'precipitation',
  'cloud_cover',
  'wind_speed_10m',
  'wind_gusts_10m'
].join(',');

const URL =
  `https://api.open-meteo.com/v1/forecast?latitude=${COORDS.lat}&longitude=${COORDS.lon}` +
  `&hourly=${HOURLY}&current_weather=true&timezone=${encodeURIComponent(TIMEZONE)}`;

function closestHourIndex(times, iso) {
  const t = new Date(iso).getTime();
  let best = 0, diff = Infinity;
  for (let i = 0; i < times.length; i++) {
    const di = Math.abs(new Date(times[i]).getTime() - t);
    if (di < diff) { diff = di; best = i; }
  }
  return best;
}

export async function fetchWeather() {
  const res = await fetch(URL, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const d = await res.json();

  const cw = d.current_weather;                 // temp, windspeed, etc.
  const i  = closestHourIndex(d.hourly.time, cw.time);  // ZAMIast indexOf

  return {
    updatedIso: cw.time,
    now: {
      temp:  cw.temperature,
      code:  cw.weathercode,
      wind:  cw.windspeed,
      gust:  d.hourly.wind_gusts_10m[i],
      hum:   d.hourly.relative_humidity_2m[i],
      prcp:  d.hourly.precipitation[i],
      cloud: d.hourly.cloud_cover[i]
    },
    nextHours: [1, 2, 3]
      .map(k => i + k)
      .filter(x => x < d.hourly.time.length)
      .map(x => ({
        timeIso: d.hourly.time[x],
        temp:    d.hourly.temperature_2m[x],
        prcp:    d.hourly.precipitation[x],
        wind:    d.hourly.wind_speed_10m[x]
      }))
  };
}
