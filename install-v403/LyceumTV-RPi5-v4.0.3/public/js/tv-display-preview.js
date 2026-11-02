(() => {
  'use strict';
  const WIDTH = 1920, HEIGHT = 1080;
  const classes = ['10-А', '10-Б', '10-В', '10-Г', '11-А', '11-Б', '11-В', '11-Г'];
  const $ = id => document.getElementById(id);
  const production = document.documentElement.dataset.tvProduction === 'true';
  // A presentation-only input, never enabled on a production TV document.
  const demo = !production && document.documentElement.dataset.tvDemo === 'true';
  const sample = production ? null : new URLSearchParams(location.search).get('sample');
  const samples = ['lesson', 'break', 'denominator', 'groups', 'substitution', 'holiday', 'weekend', 'after-school', 'shelter', 'long'];
  const cacheKey = production ? 'lyceumtv.tv-display.state.v1' : 'lyceumtv.isolated-preview.state.v1';
  let state = null, receivedAt = 0, online = false, pollTimer = null, clockTimer = null;
  let controller = null, stopped = false, signature = '', fitFrame = null;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const text = (id, value) => { $(id).textContent = value; };
  const formatSeconds = value => { const n = Math.max(0, Math.floor(value)); return `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`; };
  const dateFormat = new Intl.DateTimeFormat('uk-UA', {timeZone: 'Europe/Kyiv', weekday: 'long', day: '2-digit', month: 'long'});
  const timeFormat = new Intl.DateTimeFormat('uk-UA', {timeZone: 'Europe/Kyiv', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});

  function fitViewport() {
    const scale = Math.min(innerWidth / WIDTH, innerHeight / HEIGHT);
    $('display').style.transform = `translate(${(innerWidth - WIDTH * scale) / 2}px, ${(innerHeight - HEIGHT * scale) / 2}px) scale(${scale})`;
  }
  function fitText() {
    document.querySelectorAll('.fit-text').forEach(node => {
      node.style.fontSize = '';
      const base = parseFloat(getComputedStyle(node).fontSize);
      const cell = node.parentElement;
      const label = cell.querySelector('.group-label');
      const css = getComputedStyle(cell);
      const available = cell.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom) - (label ? label.offsetHeight + 2 : 0);
      // Fit full text without ellipses, scrolling or removing groups.
      for (let size = base; size >= 10; size -= 0.5) {
        node.style.fontSize = `${size}px`;
        if (node.scrollHeight <= available + 1 && node.scrollWidth <= node.clientWidth + 1) break;
      }
    });
  }
  function requestFit() {
    if (fitFrame !== null) cancelAnimationFrame(fitFrame);
    fitFrame = requestAnimationFrame(() => { fitFrame = null; fitText(); });
  }
  function row(rowState, duty) {
    const entries = Array.isArray(rowState.entries) ? rowState.entries.filter(e => e && typeof e === 'object') : [];
    const split = entries.length > 1;
    const items = entries.length ? entries : [{subject: 'Немає заняття', teacher: '—', room: '—'}];
    const isDuty = duty?.enabled && !duty.paused && duty.class === rowState.className;
    return `<article class="class-row ${split ? 'is-split' : ''}" data-class="${escape(rowState.className)}" aria-label="${escape(rowState.className)}">
      <div class="class-cell"><strong class="class-name">${escape(rowState.className)}</strong>${rowState.substitution ? '<span class="badge">ЗАМІНА</span>' : ''}${isDuty ? '<span class="duty-mark">★ ЧЕРГОВИЙ</span>' : ''}</div>
      <div class="lessons" style="grid-template-rows:repeat(${items.length},minmax(0,1fr))">${items.map((entry, i) => {
        const group = String(entry.subgroup || '').replace(/^(?:гр(?:упа)?\.?|підгрупа)\s*/iu, '').trim();
        const label = group ? `ГРУПА ${group}` : split ? `ГРУПА ${i + 1}` : '';
        return `<div class="lesson-group"><div class="cell subject">${label ? `<span class="group-label">${escape(label)}</span>` : ''}<span class="fit-text ${entries.length ? '' : 'empty'}">${escape(entry.subject || '—')}</span></div><div class="cell teacher"><span class="fit-text">${escape(entry.teacher || '—')}</span></div><div class="cell room"><span class="fit-text">${escape(entry.room || '—')}</span></div></div>`;
      }).join('')}</div></article>`;
  }
  function tick() {
    window.SafetyDisplay?.render(state, {online, sample: !!sample, receivedAt});
    const elapsed = Math.max(0, (Date.now() - receivedAt) / 1000);
    const serverTime = Date.parse(state?.now);
    const now = new Date(Number.isFinite(serverTime) ? serverTime + elapsed * 1000 : Date.now());
    text('clock', timeFormat.format(now));
    text('date', dateFormat.format(now));
    if (!state) return;
    if (state.mode === 'ALL_CLEAR' && !window.SafetyDisplay.confirmedClear(state, online, !!sample)) {
      text('special-title', 'СТАТУС ТРИВОГИ НЕ ПІДТВЕРДЖЕНО');
      text('special-message', 'Перевірте офіційні сповіщення');
    }
    const schedule = state.schedule || {};
    const remaining = Number(schedule.phase === 'LESSON' ? schedule.seconds_to_lesson_end : schedule.seconds_to_next_lesson);
    const timed = ['LESSON', 'BREAK', 'BEFORE_SCHOOL'].includes(schedule.phase);
    text('countdown', timed && Number.isFinite(remaining)
      ? remaining - elapsed > 0
        ? `${schedule.phase === 'LESSON' ? 'До кінця уроку' : 'До початку уроку'} · ${formatSeconds(remaining - elapsed)}`
        : 'Час минув · очікування оновлення розкладу'
      : schedule.message || 'Розклад оновлюється автоматично');
  }
  function connection() {
    window.SafetyDisplay?.render(state, {online, sample: !!sample, receivedAt});
    $('display').classList.toggle('offline', !online);
    text('connection', sample
      ? `АРХІВНИЙ ПРИКЛАД · ${sample.toUpperCase()} · ${state?.date || ''}${online ? '' : ' · НЕМАЄ З’ЄДНАННЯ'}`
      : online ? 'АКТУАЛЬНІ ДАНІ · /api/state'
        : state ? `НЕМАЄ З’ЄДНАННЯ · КЕШ СТАНОМ НА ${state.date || ''} ${state.clock || ''}`
          : 'НЕМАЄ З’ЄДНАННЯ · ДАНІ НЕДОСТУПНІ');
  }
  function render(next, at) {
    window.SafetyDisplay?.render(next, {online, sample: !!sample, receivedAt: at});
    if (production) dispatchEvent(new CustomEvent('lyceumtv:state', {detail: {state: next, online}}));
    if (!next?.schedule || !Array.isArray(next.schedule.rows)) {
      if (next?.mode === 'AIR_RAID' || next?.alarm?.active) { state = next; receivedAt = at; connection(); return; }
    }
    if (!next?.schedule || !Array.isArray(next.schedule.rows)) throw Error('Invalid state schema');
    state = next; receivedAt = at;
    const schedule = state.schedule, mode = state.mode;
    const phaseLabel = schedule.phase === 'LESSON' ? `Поточний урок · ${schedule.lesson}-й`
      : schedule.phase === 'BREAK' ? `Наступний урок · ${schedule.lesson}-й`
        : schedule.phase === 'BEFORE_SCHOOL' ? `Наступний урок · ${schedule.lesson}-й` : 'Розклад занять';
    $('display').classList.toggle('alarm', mode === 'AIR_RAID');
    text('phase', mode === 'AIR_RAID' ? 'ТРИВОГА · РОЗКЛАД В УКРИТТІ' : phaseLabel);
    text('week', schedule.week?.label || 'ТИП ТИЖНЯ НЕ ВИЗНАЧЕНО');
    text('duty', state.duty?.enabled && !state.duty.paused ? `ЧЕРГОВИЙ КЛАС · ${state.duty.class || '—'}` : '');
    const temperature = state.weather?.temperature;
    text('weather', window.SafetyDisplay.weatherText(state.weather));
    const clearConfirmed = window.SafetyDisplay.confirmedClear(state, online, !!sample);
    const specialTitle = mode === 'SILENCE' ? 'ХВИЛИНА МОВЧАННЯ' : mode === 'ALL_CLEAR' ? (clearConfirmed ? 'ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ' : 'СТАТУС ТРИВОГИ НЕ ПІДТВЕРДЖЕНО')
      : mode === 'AIR_RAID' ? (schedule.rows.some(row => row.entries?.length) ? '' : 'ПОВІТРЯНА ТРИВОГА')
      : schedule.phase === 'HOLIDAY' ? 'КАНІКУЛИ' : schedule.phase === 'AFTER_SCHOOL' ? 'УРОКИ ЗАВЕРШЕНО'
        : schedule.phase === 'NO_SCHEDULE' ? 'НЕМАЄ ЗАНЯТЬ' : '';
    $('special').hidden = !specialTitle;
    $('tables').hidden = !!specialTitle;
    text('special-title', specialTitle);
    text('special-message', mode === 'ALL_CLEAR' && !clearConfirmed ? 'Перевірте офіційні сповіщення' : mode === 'SILENCE' ? 'Вшановуємо пам’ять загиблих' : mode === 'AIR_RAID' ? 'НЕГАЙНО ПРОЙДІТЬ В УКРИТТЯ!' : schedule.message || '');
    const nextSignature = JSON.stringify([schedule.rows, state.duty]);
    if (nextSignature !== signature) {
      signature = nextSignature;
      const mapping = new Map(schedule.rows.map(r => [r.className, r]));
      const ordered = classes.map(className => mapping.get(className) || {className, entries: []});
      text('source', production ? 'LYCEUMTV 4.0 · TV DISPLAY' : 'ІЗОЛЬОВАНИЙ PREVIEW · БЕЗ ЗВУКУ');
      $('left-rows').innerHTML = ordered.slice(0, 4).map(r => row(r, state.duty)).join('');
      $('right-rows').innerHTML = ordered.slice(4).map(r => row(r, state.duty)).join('');
    }
    requestFit(); connection(); tick();
  }
  async function poll() {
    if (demo) return;
    if (stopped || document.hidden || controller) return;
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 5000);
    try {
      if (sample && !samples.includes(sample)) throw Error('Unknown sample');
      const response = await fetch(sample ? `/preview-data/${sample}.json` : '/api/state', {signal: controller.signal, cache: 'no-store'});
      if (!response.ok) throw Error(`HTTP ${response.status}`);
      const next = await response.json();
      online = true; render(next, Date.now());
      if (!sample) { try { localStorage.setItem(cacheKey, JSON.stringify({state, receivedAt})); } catch {} }
    } catch {
      online = false;
      if (!state && !sample) {
        try {
          const cached = JSON.parse(localStorage.getItem(cacheKey));
          if (cached && Number.isFinite(cached.receivedAt)) render(cached.state, cached.receivedAt);
        } catch { state = null; }
      }
      connection();
      if (production) dispatchEvent(new CustomEvent('lyceumtv:state', {detail: {state, online: false}}));
    } finally {
      clearTimeout(timeout); controller = null;
      if (!stopped && !document.hidden && !sample) pollTimer = setTimeout(poll, 5000);
    }
  }
  function visibility() {
    clearTimeout(pollTimer); pollTimer = null;
    if (document.hidden) { controller?.abort(); clearInterval(clockTimer); clockTimer = null; }
    else { tick(); if (clockTimer === null) clockTimer = setInterval(tick, 1000); poll(); }
  }
  function stop() {
    stopped = true; clearTimeout(pollTimer); clearInterval(clockTimer); controller?.abort();
    clockTimer = null; pollTimer = null;
    if (fitFrame !== null) cancelAnimationFrame(fitFrame);
  }
  addEventListener('resize', fitViewport, {passive: true});
  addEventListener('pagehide', stop);
  addEventListener('pageshow', event => { if (event.persisted) { stopped = false; visibility(); } });
  document.addEventListener('visibilitychange', visibility);
  fitViewport();
  if (demo) window.TVDisplayDemo = Object.freeze({render(next) { online = true; render(next, Date.now()); }});
  const placeholders = classes.map(className => row({className, entries: [{subject: 'Очікування даних', teacher: '—', room: '—'}]}, null));
  $('left-rows').innerHTML = placeholders.slice(0, 4).join('');
  $('right-rows').innerHTML = placeholders.slice(4).join('');
  tick(); clockTimer = setInterval(tick, 1000); poll();
})();
