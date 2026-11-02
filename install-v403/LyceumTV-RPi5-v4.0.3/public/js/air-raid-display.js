/* Presentation only: never polls alerts, changes their state, or plays audio. */
(() => {
  'use strict';
  const panel = document.createElement('section');
  panel.id = 'air-raid-display'; panel.hidden = true;
  panel.setAttribute('role', 'alert');
  panel.innerHTML = '<div class="raid-warning" aria-hidden="true">⚠</div><h1>ПОВІТРЯНА ТРИВОГА</h1><p class="raid-action">НЕГАЙНО ПРОЙДІТЬ В УКРИТТЯ!</p><div id="raid-schedule" hidden><h2></h2><div class="raid-classes"></div></div><p id="raid-data-status" role="status"></p>';
  document.body.append(panel);
  const notice = document.createElement('div');
  notice.id = 'alert-data-notice'; notice.hidden = true; notice.setAttribute('role', 'status');
  document.body.append(notice);
  const status = panel.querySelector('#raid-data-status');
  const timetable = panel.querySelector('#raid-schedule');
  const entries = timetable.querySelector('.raid-classes');
  const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  window.SafetyDisplay = {
    confirmedClear(s, online = false, sample = false) {
      const now = sample ? Date.parse(s?.now) : Date.now();
      const age = now - Date.parse(s?.now), checked = now - Date.parse(s?.alarm?.status?.at);
      return online && s?.alarm?.active !== true && age >= -60000 && age < 20000
        && s?.alarm?.status?.http >= 200 && s.alarm.status.http < 300
        && checked >= -60000 && checked < Math.max(60000, Number(s.config_public?.alerts_poll_seconds || 15) * 3000);
    },
    weatherText(w, now = Date.now()) {
      const age = now - Date.parse(w?.updated_at);
      if (!w?.available || !finite(w.temperature)) return 'Погода недоступна';
      if (w.stale || !Number.isFinite(age) || age > 1800000 || age < -60000) return 'Погода недоступна · дані застарілі';
      return `${w.city || 'Погода'} · ${Number(w.temperature) > 0 ? '+' : ''}${w.temperature} °C`;
    },
    render(s, {online = false, sample = false, receivedAt = Date.now()} = {}) {
      if (!s) {
        notice.hidden = !panel.hidden;
        notice.textContent = 'Статус тривоги невідомий · немає актуальних даних';
        return;
      }
      const alarm = s.mode === 'AIR_RAID' || s.alarm?.active === true;
      panel.hidden = !alarm;
      document.documentElement.classList.toggle('air-raid-active', alarm);
      const reference = sample ? Date.parse(s.now) : Date.now();
      const age = reference - Date.parse(s.now);
      const fresh = online && (sample || Date.now() - receivedAt < 20000) && Number.isFinite(age) && age >= -60000 && age < 20000;
      const checked = reference - Date.parse(s.alarm?.status?.at);
      const verified = fresh && s.alarm?.status?.http >= 200 && s.alarm?.status?.http < 300 && checked >= -60000 && checked < Math.max(60000, Number(s.config_public?.alerts_poll_seconds || 15) * 3000);
      const uncertain = !verified;
      notice.hidden = alarm || !uncertain;
      notice.textContent = 'Статус тривоги невідомий або застарілий · перевірте офіційні сповіщення';
      const messages = [];
      if (sample) messages.push('АРХІВНИЙ PREVIEW · БЕЗ ЗВУКУ');
      if (!fresh) messages.push('Немає актуальних даних · останній отриманий стан тривоги збережено');
      else if (uncertain) messages.push(s.alarm?.manual ? 'Ручна тривога · віддалений статус не підтверджено' : 'Статус джерела тривоги невідомий або застарілий');
      const sch = s.schedule;
      const elapsed = Math.max(0, (reference - Date.parse(s.now)) / 1000);
      const remaining = Number(sch?.phase === 'LESSON' ? sch?.seconds_to_lesson_end : sch?.seconds_to_next_lesson);
      const syncAge = reference - Date.parse(s.sync?.at);
      const sourceFresh = sample || (s.sync?.ok === true && syncAge >= -60000 && syncAge < Math.max(600000, Number(s.config_public?.sync_interval_seconds || 300) * 2000));
      const eligible = alarm && fresh && sourceFresh && sch?.shelter === true && sch.date === String(s.now).slice(0, 10) && ['LESSON', 'BREAK'].includes(sch.phase) && remaining > elapsed && Array.isArray(sch.rows) && sch.rows.some(r => r.entries?.length);
      timetable.hidden = !eligible;
      entries.replaceChildren();
      if (eligible) {
        timetable.querySelector('h2').textContent = `Розклад в укритті · ${sch.phase === 'BREAK' ? 'наступний' : 'поточний'} урок ${sch.lesson}`;
        for (const row of sch.rows) {
          if (!row.entries?.length) continue;
          const item = document.createElement('div');
          const cls = document.createElement('strong'); cls.textContent = row.className;
          item.append(cls);
          for (const entry of row.entries) {
            const line = document.createElement('span');
            line.textContent = [entry.subgroup, entry.subject, entry.room ? `ауд. ${entry.room}` : 'аудиторія не вказана'].filter(Boolean).join(' · ');
            item.append(line);
          }
          entries.append(item);
        }
        // An unusually long timetable must never push the safety message away.
        if (panel.scrollHeight > panel.clientHeight + 1) {
          timetable.hidden = true;
          messages.push('Розклад укриття завеликий для компактного показу');
        }
      } else if (alarm) {
        messages.push(!fresh ? 'Розклад укриття не показано: дані застарілі' : !sch ? 'Дані розкладу укриття недоступні' : ['HOLIDAY', 'NO_SCHEDULE', 'AFTER_SCHOOL', 'BEFORE_SCHOOL'].includes(sch.phase) ? (sch.message || 'Зараз немає поточних занять в укритті') : 'Актуальний розклад укриття не підтверджено');
      }
      if (alarm && !sample && !sourceFresh) messages.push('Актуальність джерела розкладу не підтверджено');
      status.textContent = messages.join(' · ');
    }
  };
})();
