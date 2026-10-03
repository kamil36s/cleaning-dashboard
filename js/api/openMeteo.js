import { COORDS, TIMEZONE } from '../config.js';

const CURRENT = [
  'temperature_2m',
  'relative_humidity_2m',
  'apparent_temperature',
  'precipitation',
  'cloud_cover',
  'weather_code',
  'wind_speed_10m',
  'wind_gusts_10m'
].join(',');

const HOURLY = [
  'temperature_2m',
  'apparent_temperature',
  'relative_humidity_2m',
  'precipitation',
  'cloud_cover',
  'wind_speed_10m',
  'wind_gusts_10m'
].join(',');

const URL =
  `https://api.open-meteo.com/v1/forecast?latitude=${COORDS.lat}&longitude=${COORDS.lon}` +
  `&current=${CURRENT}&hourly=${HOURLY}&current_weather=true&timezone=${encodeURIComponent(TIMEZONE)}`;

function floorHourIndex(times, iso) {
  const t = new Date(iso).getTime();
  let best = -1;
  for (let i = 0; i < times.length; i++) {
    const ti = new Date(times[i]).getTime();
    if (ti <= t) best = i;
  }
  return best >= 0 ? best : 0;
}

export async function fetchWeather() {
  const res = await fetch(URL, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const d = await res.json();

  const current = d.current ?? null;
  const cw = d.current_weather ?? null;
  const currentTime = current?.time ?? cw?.time ?? d.hourly.time[0];
  const i = floorHourIndex(d.hourly.time, currentTime); // zamiast indexOf

  return {
    updatedIso: currentTime,
    now: {
      temp: current?.temperature_2m ?? cw?.temperature,
      feels: current?.apparent_temperature ?? d.hourly.apparent_temperature?.[i],
      code: current?.weather_code ?? cw?.weathercode,
      wind: current?.wind_speed_10m ?? cw?.windspeed,
      gust: current?.wind_gusts_10m ?? d.hourly.wind_gusts_10m[i],
      hum: current?.relative_humidity_2m ?? d.hourly.relative_humidity_2m[i],
      prcp: current?.precipitation ?? d.hourly.precipitation[i],
      cloud: current?.cloud_cover ?? d.hourly.cloud_cover[i]
    },
    nextHours: (() => {
      const end = new Date(currentTime);
      end.setDate(end.getDate() + 1);
      end.setHours(6, 0, 0, 0);

      const out = [];
      for (let x = i; x < d.hourly.time.length; x++) {
        const timeIso = d.hourly.time[x];
        const dt = new Date(timeIso);
        if (dt > end) break;
        out.push({
          timeIso,
          temp: d.hourly.temperature_2m[x],
          prcp: d.hourly.precipitation[x],
          wind: d.hourly.wind_speed_10m[x]
        });
      }
      return out;
    })()
  };
}
