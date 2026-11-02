(() => { 'use strict';
const form=document.getElementById('mediaDashboardForm');
const status=document.getElementById('mediaDashboardStatus');
async function request(url, options={}){
 const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...options});
 const data=await r.json().catch(()=>({})); if(!r.ok||!data.ok)throw Error(data.error||`HTTP ${r.status}`);return data;
}
async function load(){try{
 const data=await request('/api/media-dashboard');
 for(const [key,value] of Object.entries(data.content)) if(form.elements.namedItem(key))form.elements.namedItem(key).value=value;
 status.textContent='Контент завантажено';
}catch(err){status.textContent='Помилка завантаження: '+err.message}}
form.addEventListener('submit',async event=>{
 event.preventDefault(); status.textContent='Збереження…';
 const content=Object.fromEntries(new FormData(form));
 try{await request('/api/admin/media-dashboard',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content})});status.textContent='Збережено. Екран оновиться автоматично.';}
 catch(err){status.textContent='Не збережено: '+err.message;}
});
document.querySelector('[data-tab="media-dashboard"]')?.addEventListener('click',load);
})();
