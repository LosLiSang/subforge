(()=>{
const root=document.getElementById('player');if(!root)return;
const track=root.dataset.trackId,sourceLang=root.dataset.sourceLanguage,targetLang=root.dataset.targetLanguage,itemId=root.dataset.itemId||'',nextTrackId=root.dataset.nextTrackId||'';
const embed=root.dataset.embed==='1';
const STORAGE_KEY='sf.playback';
let source=[],target=[],sourceIndex=0,targetIndex=0;
let lastRenderedSourceIndex=-2;
let transcriptRows=[];
let lastSourceText='',lastTargetText='';
let lastTranscriptInteract=0;
let player=window.top.SubForgePlayer||window.SubForgePlayer;

/* 播放器音频源：统一用全局单例（iframe 内 audio），播放页不再自建 <audio>。 */
let audio=null;
function bindPlayerAudio(){
  if(!player)return;
  const title=root.querySelector('.work-hero-info h1')?.textContent||track;
  player.activate(track,title,itemId);
  player.ensureAudio().then(async a=>{audio=a;if(audio){wireAudio();await player.play().catch(()=>{});}});
  const toggle=document.getElementById('play-toggle');
  if(toggle)toggle.addEventListener('click',()=>player.toggle());
  const seek=document.getElementById('play-seek');
  if(seek)seek.addEventListener('input',()=>{player.seek(parseFloat(seek.value));});
  renderNow();
}
function setToggle(paused){const t=document.getElementById('play-toggle');if(t)t.classList.toggle('playing',!paused);}
function renderNow(){
  const time=player.currentTime,dur=player.duration||0;
  if(document.getElementById('play-time'))document.getElementById('play-time').textContent=`${fmt(time)} / ${fmt(dur)}`;
  setToggle(player.paused);
  if(document.getElementById('play-seek')){const s=document.getElementById('play-seek');s.max=dur||0;s.value=time||0;}
  updateSubs();
}
function wireAudio(){
  const render=()=>{
    if(document.getElementById('play-time'))document.getElementById('play-time').textContent=`${fmt(audio.currentTime)} / ${fmt(audio.duration||0)}`;
    setToggle(audio.paused);
    if(document.getElementById('play-seek')){const s=document.getElementById('play-seek');s.max=audio.duration||0;s.value=audio.currentTime||0;}
    updateSubs();
  };
  player.on('timeupdate',render,'page');player.on('play',render,'page');player.on('pause',render,'page');
  audio.addEventListener('loadedmetadata',render);
  audio.addEventListener('ended',()=>{
    if(nextTrackId) window.location.href=`/tracks/${encodeURIComponent(nextTrackId)}/play`;
  });
  // 字幕/进度逐帧对齐 audio.currentTime；不依赖稀疏的 timeupdate 事件，
  // 否则浏览器 timeupdate 频率低/不规律时字幕会滞后并随播放时长漂移。
  const loop=()=>{ if(!audio.paused) render(); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
}
function updateSubs(){
  if(!audio)return;
  const time=audio.currentTime;
  const nextSourceIndex=locate(source,time,sourceIndex);
  const nextTargetIndex=locate(target,time,targetIndex);
  const srcEl=document.getElementById('source-subtitle'),tgtEl=document.getElementById('target-subtitle');
  const sourceText=nextSourceIndex>=0?source[nextSourceIndex].text:'…';
  const targetText=nextTargetIndex>=0?target[nextTargetIndex].text:'…';
  sourceIndex=nextSourceIndex;targetIndex=nextTargetIndex;
  if(srcEl&&sourceText!==lastSourceText){srcEl.textContent=sourceText;lastSourceText=sourceText;}
  if(tgtEl&&targetText!==lastTargetText){tgtEl.textContent=targetText;lastTargetText=targetText;}

  // 只有当前字幕行变化时才更新列表 DOM；播放中的每一帧不再遍历全部字幕。
  if(sourceIndex!==lastRenderedSourceIndex){
    if(transcriptRows[lastRenderedSourceIndex])transcriptRows[lastRenderedSourceIndex].classList.remove('active');
    if(transcriptRows[sourceIndex])transcriptRows[sourceIndex].classList.add('active');
    lastRenderedSourceIndex=sourceIndex;
    const active=transcriptRows[sourceIndex];
    if(active&&'scrollIntoViewIfNeeded' in active&&Date.now()-lastTranscriptInteract>3000)active.scrollIntoViewIfNeeded(false);
  }
}

/* 字幕模式：双语 / 仅原文 / 仅译文 / 关闭，localStorage 记忆 */
const modeButtons=[...document.querySelectorAll('[data-subtitle-mode]')];
let subtitleMode=localStorage.getItem('sf.subtitleMode')||'both';
function applySubtitleMode(){
  if(!document.querySelector('[data-subtitle-panel="source"]'))return;
  document.querySelectorAll('.subtitles>div').forEach(d=>{
    const kind=d.dataset.subtitlePanel;
    d.style.display=(subtitleMode==='both'||subtitleMode===kind)?'':'none';
  });
  modeButtons.forEach(b=>b.classList.toggle('active',b.dataset.subtitleMode===subtitleMode));
}
modeButtons.forEach(btn=>btn.addEventListener('click',()=>{
  subtitleMode=btn.dataset.subtitleMode;
  localStorage.setItem('sf.subtitleMode',subtitleMode);
  applySubtitleMode();
}));

/* ===== 悬浮歌词：实现在顶层模块 float-lyrics.js（PiP 只允许顶层开窗），这里只做入口委托 ===== */
const floatBtn=document.getElementById('float-lyrics-btn');
if(floatBtn){
  const floatApi=(window.top===window?window:window.top).SubForgeFloatLyrics;
  if(!floatApi){floatBtn.disabled=true;floatBtn.title='悬浮歌词模块未加载';}
  else{
    const syncFloat=()=>floatBtn.classList.toggle('active',floatApi.isActive());
    floatApi.onChange(syncFloat,'page');syncFloat();
    floatBtn.addEventListener('click',()=>floatApi.toggle(track));
  }
}

async function load(lang,element,missingText){const r=await fetch(`/tracks/${track}/subtitles/${lang}`);if(!r.ok){element.textContent=r.status===404?missingText:'字幕无法读取';return []}return await r.json()}
function locate(entries,time,old){if(entries[old]&&time>=entries[old].start&&time<=entries[old].end)return old;let lo=0,hi=entries.length-1;while(lo<=hi){const mid=(lo+hi)>>1,e=entries[mid];if(time<e.start)hi=mid-1;else if(time>e.end)lo=mid+1;else return mid}return -1}
function fmt(t){if(t==null||!isFinite(t))return '--:--';const s=Math.max(0,Math.floor(t)),h=Math.floor(s/3600),m=Math.floor(s%3600/60),sec=s%60,p=n=>String(n).padStart(2,'0');return h?`${h}:${p(m)}:${p(sec)}`:`${m}:${p(sec)}`}

/* ===== 字幕加载 =====
 * 双轨字幕数据（source/target）在播放页初始化时即加载，供字幕条即时显示；
 * 完整 transcript（全部字幕 <details>）懒加载——点开才构建 DOM，折叠时跳过，
 * 避免几千条字幕一次性挤进 DOM 造成卡顿。 */
let transcriptsLoaded=false;

/* 双轨数据：初始化即加载，供字幕条/逐帧定位使用。 */
function loadSubtitleData(){
  Promise.all([
    load(sourceLang,document.getElementById('source-subtitle'),'暂无源语言字幕'),
    load(targetLang,document.getElementById('target-subtitle'),'暂无翻译字幕'),
  ]).then(values=>{
    [source,target]=values;
    updateSubs();
    if(transcriptsLoaded){renderTranscript();}
  });
}

/* 全部字幕列表：仅当 <details> 展开后调用。 */
function renderTranscript(){
  const transcript=document.getElementById('transcript');
  if(!transcript)return;
  const markInteract=()=>{lastTranscriptInteract=Date.now()};
  window.addEventListener('wheel',markInteract,{passive:true});
  window.addEventListener('touchmove',markInteract,{passive:true});
  transcript.addEventListener('pointerdown',markInteract,{passive:true});
  const fragment=document.createDocumentFragment();
  source.forEach((entry,i)=>{
    const row=document.createElement('button');row.type='button';row.dataset.entry=i;row.className='transcript-row';
    row.innerHTML=`<span class="transcript-time">${fmt(entry.start)}<br>${fmt(entry.end)}</span><span>${entry.text}</span><span>${target[i]?.text||'（未翻译）'}</span>`;
    row.onclick=()=>{lastTranscriptInteract=Date.now();player.seek(entry.start);player.play()};
    fragment.append(row);
  });
  transcript.append(fragment);
  transcriptRows=[...transcript.children];
  lastRenderedSourceIndex=-2;
  updateSubs();
}
function armTranscriptToggle(){
  const details=document.getElementById('player')?.querySelector('.track-actions');
  if(!details)return;
  details.addEventListener('toggle',()=>{
    if(details.open&&!transcriptsLoaded){transcriptsLoaded=true;renderTranscript();}
  });
}

if(!embed){
  /* 等待全局播放器（global-player.js，base.html 末尾加载）就绪后初始化 */
  const init=()=>{player=window.top.SubForgePlayer||window.SubForgePlayer;bindPlayerAudio();};
  if(window.top.SubForgePlayer||window.SubForgePlayer){init();}else{
    let tries=0;
    const iv=setInterval(()=>{tries++;if(window.top.SubForgePlayer||window.SubForgePlayer||tries>50){clearInterval(iv);if(window.top.SubForgePlayer||window.SubForgePlayer)init();}},100);
  }
  loadSubtitleData();
  armTranscriptToggle();
  applySubtitleMode();
}else{
  /* embed 模式：全局播放器 iframe 内。不自动播放——由父页面播放栏控制。
   * 只恢复保存的位置，播放由父页面的 toggle/play 触发。 */
  const st=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');
  audio=document.getElementById('audio');
  if(st&&st.currentTime&&isFinite(st.currentTime))audio.currentTime=Math.min(st.currentTime,audio.duration||st.currentTime);
}
})();
