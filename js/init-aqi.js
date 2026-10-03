import { onDomReady } from './dom-ready.js';
import { renderAqiForKrasinskiego } from './aqi.js';

function msToNextQuarterHour() {
  const now = new Date();
  const minutes = now.getMinutes();
  const remainder = minutes % 15;
  const onQuarter = remainder === 0 && now.getSeconds() === 0 && now.getMilliseconds() === 0;
  const addMinutes = onQuarter ? 0 : (15 - remainder || 15);

  const next = new Date(now);
  next.setSeconds(0, 0);
  next.setMinutes(minutes + addMinutes);
  return Math.max(0, next.getTime() - now.getTime());
}

function scheduleQuarterlyAqiRefresh() {
  const delay = msToNextQuarterHour();
  setTimeout(async () => {
    try {
      await renderAqiForKrasinskiego({ force: true });
    } catch (err) {
      console.error('[AQI] Scheduled refresh failed:', err);
    } finally {
      scheduleQuarterlyAqiRefresh();
    }
  }, delay);
}

onDomReady(() => {
  renderAqiForKrasinskiego({ force: true }).catch(console.error);
  scheduleQuarterlyAqiRefresh();
});
