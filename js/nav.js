// js/nav.js
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('back-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    if (history.length > 1) history.back();
    else location.href = './index.html';
  });
});
