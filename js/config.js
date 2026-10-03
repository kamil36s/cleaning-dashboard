// API and static config
export const API = 'https://script.google.com/macros/s/AKfycbwZXHkLhl9HlcTHHzJjcMzAzDMRYhboDs3_kR8oAq9SdeKgBOp9JbWFS6P2OaiczpmXkg/exec';
export const WRITE_TOKEN = '';
export const OPENAI_PROXY = 'https://cleaning-ai-proxy.kamil36s.workers.dev';
export const COORDS = {
  lat: Number(import.meta.env.VITE_WEATHER_LATITUDE || 50.0614),
  lon: Number(import.meta.env.VITE_WEATHER_LONGITUDE || 19.9366),
};
export const TIMEZONE = 'Europe/Warsaw';
export const REFRESH_MS = 5 * 60 * 1000; // 5 min

// Weather: temperature scale + chart colors
export const TEMP_STOPS = [
  { t: -15, c: '#2F2C7E' },
  { t: -5,  c: '#2B6CB0' },
  { t: 5,   c: '#2c9fa3' },
  { t: 12,  c: '#6dbba1' },
  { t: 20,  c: '#f0e68c' },
  { t: 27,  c: '#F6B04C' },
  { t: 35,  c: '#c94c2d' },
  { t: 35.1, c: '#B11226' }
];

export const WX_COLORS = {
  prcp: '#84baf8',
  wind: '#ffffff',
  tempFallback: '#ffffff'
};
