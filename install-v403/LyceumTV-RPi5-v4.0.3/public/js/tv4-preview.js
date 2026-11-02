(() => {
  'use strict';
  const W=1920,H=1080, $=id=>document.getElementById(id);
  const names=['10-А','10-Б','10-В','10-Г','11-А','11-Б','11-В','11-Г'];
  const demo = new URLSearchParams(location.search).get('demo') === '1';
  let lastState = null, live = false;
  const safe = v => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = n => {n=Math.max(0,Math.floor(Number(n)||0));return `${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`};
  const fit = () => {const s=Math.min(innerWidth/W,innerHeight/H);$('tv4-screen').style.transform=`translate(${Math.round((innerWidth-W*s)/2)}px,${Math.round((innerHeight-H*s)/2)}px) scale(${s})`};
  addEventListener('resize',fit,{passive:true});fit();
  function weatherIcon(code){code=Number(code);if(code===0)return '☀';if([1,2].includes(code))return '🌤';if(code===3)return '☁';if([45,48].includes(code))return '🌫';if(code>=51&&code<=67)return '🌧';if(code>=71&&code<=86)return '🌨';if(code>=95)return '⛈';return '☁'}
  function cleanTeacher(s){return String(s||'').replace(/^(?:гр\.?|група|підгрупа)\s*\d+\s*[.:;\-]?\s*/i,'').trim()}
  function column(entries,key){
    if(!entries.length)return '<span class="tv4-empty">—</span>';
    const two=entries.length>1;
    return entries.map(e=>{
      let content=key==='subject'?e.subject:key==='teacher'?cleanTeacher(e.teacher):e.room;
      if(key==='room')content=content||'—';
      let tag=key==='subject'||key==='room'?'strong':'span';
      return `<div class="tv4-entry"><${tag}>${safe(content||'—')}</${tag}></div>`;
    }).join('');
  }
  function rowHtml(row,duty){
    const cls=String(row.className||''); const dutyOn=!!duty.enabled&&!duty.paused&&duty.class===cls;
    const entries=Array.isArray(row.entries)?row.entries.slice(0,2):[];const split=entries.length>1;
    return `<article class="tv4-row ${dutyOn?'is-duty':''}" data-class="${safe(cls)}">
      <div class="tv4-class"><strong>${safe(cls)}</strong>${dutyOn?'<span class="tv4-duty-label">★ ЧЕРГОВИЙ</span>':''}</div>
      <div class="tv4-subject ${split?'tv4-two':''}">${column(entries,'subject')}</div>
      <div class="tv4-teacher ${split?'tv4-two':''}">${column(entries,'teacher')}</div>
      <div class="tv4-room ${split?'tv4-two':''}">${column(entries,'room')}</div>
      ${row.substitution?'<span class="tv4-flag">ЗАМІНА</span>':''}
    </article>`;
  }
  function render(s){
    if(!s||!s.schedule)return;
    const sch=s.schedule,phase=String(sch.phase||''),mode=String(s.mode||'NORMAL');
    const special=$('tv4-special'),title=$('tv4-special-title'),description=$('tv4-special-description');
    const hiddenPhase=['HOLIDAY','NO_SCHEDULE','AFTER_SCHOOL'];
    const showSpecial=mode==='AIR_RAID'||mode==='SILENCE'||mode==='ALL_CLEAR'||hiddenPhase.includes(phase);
    special.hidden=!showSpecial;
    special.classList.toggle('alarm',mode==='AIR_RAID');
    if(showSpecial){
      const titleText=mode==='AIR_RAID'?'ПОВІТРЯНА ТРИВОГА':mode==='SILENCE'?'ХВИЛИНА МОВЧАННЯ':mode==='ALL_CLEAR'?'ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ':phase==='HOLIDAY'?'КАНІКУЛИ':phase==='AFTER_SCHOOL'?'УРОКИ ЗАВЕРШЕНО':'НЕМАЄ ЗАНЯТЬ';
      title.textContent=titleText;
      description.textContent=mode==='AIR_RAID'?'НЕГАЙНО ПРОЙДІТЬ В УКРИТТЯ!':sch.message||'';
      if(mode==='AIR_RAID')special.hidden=true; // Preserve the shelter timetable during an alarm.
    }
    $('tv4-clock').textContent=(s.clock||'--:--').slice(0,5);
    $('tv4-day').textContent=[sch.day_label||s.day_label,s.date].filter(Boolean).join(' · ');
    $('tv4-week').textContent=sch.week?.label||'ТИП ТИЖНЯ —';
    $('tv4-weather-icon').textContent=weatherIcon(s.weather?.code);
    const temp=s.weather?.temperature;
    $('tv4-weather-temp').textContent=temp!==undefined&&temp!==null&&temp!==''&&Number.isFinite(Number(temp))?`${Number(temp)>0?'+':''}${temp}°C`:'—°';
    const banner=$('tv4-banner'); banner.classList.toggle('is-break',phase==='BREAK');banner.classList.toggle('is-alarm',mode==='AIR_RAID');
    $('tv4-phase').textContent=mode==='AIR_RAID'?'ПОВІТРЯНА ТРИВОГА · РОЗКЛАД В УКРИТТІ':phase==='BREAK'?`ПЕРЕРВА · ДАЛІ ${sch.lesson||'—'}-Й УРОК`:phase==='LESSON'?`ТРИВАЄ ${sch.lesson||'—'}-Й УРОК`:phase==='BEFORE_SCHOOL'?'ДО ПОЧАТКУ УРОКІВ':'РОЗКЛАД УРОКІВ';
    $('tv4-countdown').textContent=phase==='LESSON'?`До кінця: ${fmt(sch.seconds_to_lesson_end)}`:['BREAK','BEFORE_SCHOOL'].includes(phase)?`До дзвінка: ${fmt(sch.seconds_to_next_lesson)}`:'';
    const mapping=new Map((sch.rows||[]).map(r=>[r.className,r])); const order=names.map(n=>mapping.get(n)||{className:n,entries:[]});
    $('tv4-left').innerHTML=order.slice(0,4).map(r=>rowHtml(r,s.duty||{})).join('');
    $('tv4-right').innerHTML=order.slice(4).map(r=>rowHtml(r,s.duty||{})).join('');
    $('tv4-duty').textContent=s.duty?.enabled&&!s.duty?.paused&&s.duty?.class?`★ ЧЕРГОВИЙ КЛАС: ${s.duty.class}`:'ЧЕРГОВИЙ КЛАС: НЕ ПРИЗНАЧЕНО';
    $('tv4-connection').textContent=demo?'ДЕМОНСТРАЦІЙНІ ДАНІ':live?'АКТУАЛЬНІ ДАНІ':'НЕМАЄ З’ЄДНАННЯ · КЕШ';
  }
  function demoState(){const demoSubjects=['Алгебра','Фізика','Історія України','Хімія','Геометрія','Біологія','Українська мова','Англійська мова'];return {mode:'NORMAL',clock:'10:15:00',date:'02.11.2026',schedule:{day_label:'ПОНЕДІЛОК',phase:'BREAK',lesson:3,seconds_to_next_lesson:300,week:{label:'ЧИСЕЛЬНИК'},rows:names.map((className,i)=>({className,entries:[{subject:demoSubjects[i],teacher:`Приклад учителя ${i+1}`,room:String(201+i)}]}))},weather:{temperature:12,code:2},duty:{enabled:true,paused:false,class:'10-В'}}}
  async function poll(){if(demo){render(demoState());return}const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),5000);try{const r=await fetch('/api/state',{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error(`HTTP ${r.status}`);const state=await r.json();live=true;lastState=state;try{localStorage.setItem('lyceumtv.tv4.lastState',JSON.stringify(state))}catch{}render(state)}catch{live=false;if(!lastState){try{lastState=JSON.parse(localStorage.getItem('lyceumtv.tv4.lastState')||'null')}catch{}}if(lastState)render(lastState);else $('tv4-connection').textContent='НЕМАЄ З’ЄДНАННЯ · ДАНІ НЕДОСТУПНІ'}finally{clearTimeout(timer)}}
  poll();if(!demo)setInterval(poll,5000);
})();
