/* Reuses the tested legacy slideshow player without changing alert handling. */
(() => {
  'use strict';
  if (document.documentElement.dataset.tvProduction !== 'true') return;
  const panel = document.getElementById('afterSchoolInfo');
  const player = window.afterSchoolSlideshow;
  if (!panel || !player) return;
  let lastState = null, lastReceived = 0, online = false;
  const screenId = new URLSearchParams(location.search).get('screen') ||
    (() => { try { return localStorage.getItem('lyceumtv.screenId'); } catch { return null; } })() || 'main-hall';
  function update() {
    const state = lastState;
    const now = Date.now();
    const until = Date.parse(state?.after_school_until || '');
    const valid = online && !document.hidden && now - lastReceived < 10000;
    const active = valid && Number.isFinite(until) && now < until &&
      state?.mode === 'NORMAL' && state?.schedule?.phase === 'AFTER_SCHOOL' &&
      state?.after_school_info === true;
    player.setActive(active);
    const status = player.getStatus();
    const visible = active && status.hasMedia;
    panel.classList.toggle('hidden', !visible);
    player.setPriorityPaused(!active);
    player.setAudioAllowed(visible && screenId === status.audioScreenId);
  }
  addEventListener('lyceumtv:state', event => {
    lastState = event.detail.state;
    online = event.detail.online === true;
    lastReceived = Date.now();
    update();
  });
  addEventListener('lyceumtv:slideshow-change', update);
  document.addEventListener('visibilitychange', update);
  addEventListener('pagehide', () => { online = false; update(); });
  setInterval(update, 1000);
})();
