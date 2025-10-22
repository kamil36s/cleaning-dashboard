import { renderAqiForKrasinskiego } from './aqi.js';

document.addEventListener('DOMContentLoaded', () => {
  renderAqiForKrasinskiego().catch(console.error);
});
