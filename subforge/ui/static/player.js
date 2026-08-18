(()=>{const root=document.getElementById('player');if(!root)return;const audio=document.getElementById('audio'),track=root.dataset.trackId,sourceLang=root.dataset.sourceLanguage,targetLang=root.dataset.targetLanguage;let source=[],target=[],sourceIndex=0,targetIndex=0;
const embed=root.dataset.embed==='1';
const STORAGE_KEY='sf.playback';

/* 字幕模式：双语 / 仅原文 / 仅译文 / 关闭，localStorage 记忆 */
const modeButtons=[...document.querySelectorAll('[data-subtitle-mode]')];
let subtitleMode=localStorage.getItem('sf.subtitleMode')||'both';
function applySubtitleMode(){
  const panels={source:document.querySelector('[data-subtitle-panel="source"]'),target:document.querySelector('[data-subtitle-panel="target"]')};
  if(!panels.source&&!panels.target)return;
  document.querySelectorAll('.subtitles>div').forEach(d=>{
    const kind=d.dataset.subtitlePanel;
    d.style.display=(subtitleMode==='both'||subtitleMode===kind)?'':'none';
  });
  modeButtons.forEach(b=>b.classList.toggle('active',b.dataset.subtitleMode===subtitleMode));
}
if(!embed){modeButtons.forEach(b=>b.addEventListener('click',()=>{subtitleMode=b.dataset.subtitleMode;localStorage.setItem('sf.subtitleMode',subtitleMode);applySubtitleMode()}));}

/* 播放状态 → localStorage（全局底部播放条在其他页面读取） */
function persistPlayback(){writePlayback({trackId:track,currentTime:audio.currentTime,duration:audio.duration||0,playing:!audio.paused});}
function writePlayback(patch){try{const cur=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null')||{};localStorage.setItem(STORAGE_KEY,JSON.stringify({...cur,...patch}));}catch(e){}}
audio.addEventListener('timeupdate',persistPlayback);
audio.addEventListener('play',()=>writePlayback({playing:true}));
audio.addEventListener('pause',()=>writePlayback({playing:false}));
audio.addEventListener('ended',()=>writePlayback({playing:false}));

async function load(lang,element){const r=await fetch(`/tracks/${track}/subtitles/${lang}`);if(!r.ok){element.textContent=r.status===404?'暂无字幕':'字幕无法读取';return []}return await r.json()}
function locate(entries,time,old){if(entries[old]&&time>=entries[old].start&&time<=entries[old].end)return old;let lo=0,hi=entries.length-1;while(lo<=hi){const mid=(lo+hi)>>1,e=entries[mid];if(time<e.start)hi=mid-1;else if(time>e.end)lo=mid+1;else return mid}return -1}
function fmt(t){if(t==null||!isFinite(t))return '--:--';const s=Math.max(0,Math.floor(t)),h=Math.floor(s/3600),m=Math.floor(s%3600/60),sec=s%60,p=n=>String(n).padStart(2,'0');return h?`${h}:${p(m)}:${p(sec)}`:`${m}:${p(sec)}`}
function update(){const time=audio.currentTime;sourceIndex=locate(source,time,sourceIndex);targetIndex=locate(target,time,targetIndex);const srcEl=document.getElementById('source-subtitle'),tgtEl=document.getElementById('target-subtitle');if(srcEl)srcEl.textContent=sourceIndex>=0?source[sourceIndex].text:'…';if(tgtEl)tgtEl.textContent=targetIndex>=0?target[targetIndex].text:'…';document.querySelectorAll('[data-entry]').forEach(e=>e.classList.toggle('active',Number(e.dataset.entry)===sourceIndex));const active=document.querySelector('.transcript-row.active');if(active&&'scrollIntoViewIfNeeded' in active)active.scrollIntoViewIfNeeded(false)}
if(!embed){
Promise.all([load(sourceLang,document.getElementById('source-subtitle')),load(targetLang,document.getElementById('target-subtitle'))]).then(values=>{[source,target]=values;const transcript=document.getElementById('transcript');source.forEach((entry,i)=>{const row=document.createElement('button');row.type='button';row.dataset.entry=i;row.className='transcript-row';row.innerHTML=`<span class="transcript-time">${fmt(entry.start)}<br>${fmt(entry.end)}</span><span>${entry.text}</span><span>${target[i]?.text||'（未翻译）'}</span>`;row.onclick=()=>{audio.currentTime=entry.start;audio.play()};transcript.append(row)});update()});
audio.addEventListener('timeupdate',update);audio.addEventListener('seeked',update);
applySubtitleMode();
}else{
/* embed 模式：恢复 localStorage 播放位置并同步到全局播放条 */
const st=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');
audio.addEventListener('loadedmetadata',()=>{if(st&&st.currentTime&&isFinite(st.currentTime))audio.currentTime=Math.min(st.currentTime,audio.duration||st.currentTime);audio.play().catch(()=>{});});
}
})();
