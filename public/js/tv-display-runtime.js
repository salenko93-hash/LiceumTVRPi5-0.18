/* Production sound and screen registration. Separate from the silent preview. */
(() => {
  'use strict';
  if (document.documentElement.dataset.tvProduction !== 'true') return;
  const alarm = document.getElementById('tv4-alarm-audio');
  const silence = document.getElementById('tv4-silence-audio');
  const scheduled = new Audio();
  scheduled.preload = 'auto';
  const params = new URLSearchParams(location.search);
  const stored = key => { try { return localStorage.getItem(key) || ''; } catch { return ''; } };
  const save = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
  const screen = (params.get('screen') || stored('lyceumtv.screenId') || 'main-hall').replace(/[^A-Za-z0-9._-]/g, '-').slice(0, 48) || 'main-hall';
  save('lyceumtv.screenId', screen);
  const deviceKey = `lyceumtv.device.${screen}`;
  const fragment = new URLSearchParams(location.hash.slice(1));
  if (fragment.has('device')) {
    save(deviceKey, fragment.get('device'));
    history.replaceState(null, '', location.pathname + location.search);
  }
  let token = stored(deviceKey), current = null, online = false, freshAt = 0, pending = false;
  const requests = new Set(), playing = new Set(), completed = new Set();
  const fresh = () => online && !document.hidden && Date.now() - freshAt < 10000;
  const volume = (value, fallback = 0) => Number.isFinite(Number(value)) ? Math.max(0, Math.min(1, Number(value))) : fallback;
  const pauseAll = () => { alarm.pause(); silence.pause(); scheduled.pause(); };
  async function request(url, options = {}) {
    const controller = new AbortController(); requests.add(controller);
    const timeout = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch(url, {...options, signal: controller.signal, cache: 'no-store'});
      const body = await response.text();
      return {ok: response.ok, status: response.status, json: async () => JSON.parse(body)};
    }
    finally { clearTimeout(timeout); requests.delete(controller); }
  }
  async function once(audio, id, key, level, allowed) {
    if (!id || !allowed() || stored(key) === String(id) || completed.has(`${key}:${id}`) || playing.has(key)) return;
    playing.add(key);
    audio.volume = volume(level); audio.currentTime = 0;
    try {
      await audio.play();
      if (!allowed()) { audio.pause(); return; }
      save(key, String(id)); completed.add(`${key}:${id}`);
      // Keep the in-memory fallback bounded even when browser storage is disabled.
      if (completed.size > 128) completed.delete(completed.values().next().value);
    } catch { /* Retry only on a subsequent fresh server response. */ }
    finally { playing.delete(key); }
  }
  async function localToken() {
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname)) return;
    const response = await request(`/api/screen/local-token?id=${encodeURIComponent(screen)}`);
    if (response.ok) { token = (await response.json()).token || ''; save(deviceKey, token); }
  }
  async function background() {
    if (pending || !fresh()) return;
    pending = true;
    try {
      if (current.mode === 'NORMAL' && !(window.afterSchoolSlideshow?.getStatus().active && window.afterSchoolSlideshow?.getStatus().hasMedia)) {
        const response = await request('/api/audio/current');
        if (response.ok) {
          const data = await response.json();
          if (data.event && data.event_key && stored('lyceumtv.lastAudioEvent') !== String(data.event_key)
              && !completed.has(`lyceumtv.lastAudioEvent:${data.event_key}`) && !playing.has('lyceumtv.lastAudioEvent')
              && fresh() && current.mode === 'NORMAL') {
            scheduled.src = data.event.url;
            await once(scheduled, data.event_key, 'lyceumtv.lastAudioEvent', volume(data.event.volume, 0.8), () => fresh() && current.mode === 'NORMAL');
          }
        }
      }
      if (!fresh()) return;
      if (!token) await localToken();
      if (!token || !fresh()) return;
      const headers = {'Content-Type': 'application/json', 'X-Device-Token': token};
      const response = await request('/api/screen/heartbeat', {method: 'POST', headers, body: JSON.stringify({id: screen, name: screen === 'main-hall' ? 'Головний екран' : screen, profile: 'schedule', version: '4.0.3'})});
      if (response.status === 401) { token = ''; save(deviceKey, ''); return; }
      if (!response.ok) return;
      const data = await response.json();
      const command = data.screen || {};
      if (fresh() && command.command_id && ['reload', 'restart', 'wake'].includes(command.command)) {
        const ack = await request('/api/screen/ack', {method: 'POST', headers, body: JSON.stringify({id: screen, command_id: command.command_id})});
        if (ack.ok) location.reload();
      }
      // Leave unsupported legacy music commands pending, never acknowledge success.
    } catch { /* Retried by the next fresh state; there is no independent timer. */ }
    finally { pending = false; }
  }
  addEventListener('lyceumtv:state', event => {
    current = event.detail.state; online = event.detail.online === true;
    if (!online || !current) { pauseAll(); for (const c of requests) c.abort(); return; }
    freshAt = Date.now();
    if (current.mode !== 'AIR_RAID' || !current.alarm?.sound_enabled) alarm.pause();
    if (current.mode !== 'SILENCE') silence.pause();
    if (current.mode !== 'NORMAL') scheduled.pause();
    if (current.mode === 'AIR_RAID' && current.alarm?.sound_enabled)
      once(alarm, current.alarm.event_id, 'lyceumtv.lastAlarmEvent', current.alarm.volume, () => fresh() && current.mode === 'AIR_RAID' && current.alarm?.sound_enabled);
    else if (current.mode === 'SILENCE')
      once(silence, current.silence?.event_id, 'lyceumtv.lastSilenceEvent', current.silence?.volume, () => fresh() && current.mode === 'SILENCE');
    background();
  });
  const stop = () => { online = false; pauseAll(); for (const controller of requests) controller.abort(); };
  addEventListener('pagehide', stop);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
})();
