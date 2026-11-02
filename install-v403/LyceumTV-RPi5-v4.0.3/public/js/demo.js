/* DEMO controller: archive fixtures → the same renderer and markup as TV Display.
   No production runtime, audio, state API, commands or persistent storage. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fixtures = Object.freeze({lesson:'lesson', break:'break', numerator:'lesson',
    denominator:'denominator', substitution:'substitution', groups:'groups', duty:'lesson',
    holiday:'holiday', shelter:'shelter'});
  const params = new URLSearchParams(location.search);
  const requested = params.get('scenario') || 'lesson';
  const scenario = Object.hasOwn(fixtures, requested) ? requested : 'lesson';
  params.set('scenario', scenario);
  // The shared preview renderer treats these explicitly labelled snapshots as archives.
  params.set('sample', fixtures[scenario]);
  history.replaceState(null, '', `${location.pathname}?${params}${location.hash}`);
  $('demoScenario').value = scenario;

  function controls(hidden) {
    $('demoControls').hidden = hidden;
    $('demoOpen').hidden = !hidden;
    const query = new URLSearchParams(location.search);
    if (hidden) query.set('controls', 'hidden'); else query.delete('controls');
    history.replaceState(null, '', `${location.pathname}?${query}${location.hash}`);
  }
  controls(params.get('controls') === 'hidden');
  $('demoHide').addEventListener('click', () => controls(true));
  $('demoOpen').addEventListener('click', () => controls(false));
  addEventListener('keydown', event => { if (event.key === 'Escape') controls(false); });
  $('demoFullscreen').addEventListener('click', async () => {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    } catch { /* Fullscreen may be disabled by the host; the layout still fits. */ }
  });
  $('demoScenario').addEventListener('change', () => {
    const query = new URLSearchParams(location.search);
    query.set('scenario', $('demoScenario').value);
    location.search = query.toString();
  });

  async function read(url, kind) {
    const response = await fetch(url, {cache:'no-store'});
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    return kind === 'text' ? response.text() : response.json();
  }
  function script(src) {
    return new Promise((resolve, reject) => {
      const node = document.createElement('script');
      node.src = src; node.onload = resolve; node.onerror = () => reject(Error('Renderer unavailable'));
      document.body.append(node);
    });
  }
  async function start() {
    const [html, fixture] = await Promise.all([
      read('/tv-display-preview.html', 'text'), read(`/preview-data/${fixtures[scenario]}.json`, 'json')
    ]);
    const template = new DOMParser().parseFromString(html, 'text/html').querySelector('#display');
    if (!template) throw Error('TV Display template unavailable');
    // Import only the display tree: never scripts, audio or production runtime.
    $('demoCanvas').append(document.importNode(template, true));
    document.querySelector('.edition b').textContent = 'DEMO';
    await script('/js/air-raid-display.js');
    // Keep DEMO controls/label visible above the isolated safety presentation.
    for (const id of ['air-raid-display', 'alert-data-notice']) $('demoCanvas').append($(id));
    await script('/js/tv-display-preview.js');
    const state = structuredClone(fixture);
    if (scenario === 'duty') state.duty = {enabled:true, paused:false, class:'10-В'};
    window.TVDisplayDemo.render(state);
    document.documentElement.dataset.demoReady = 'true';
  }
  start().catch(() => {
    $('demoError').hidden = false;
    $('demoError').textContent = 'DEMO недоступне: не вдалося завантажити тестові дані або TV-макет. Оновіть сторінку.';
  });
})();
