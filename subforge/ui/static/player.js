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
const selectedSegmentRows=new Set();
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
  if(!transcript.dataset.interactionBound){
    window.addEventListener('wheel',markInteract,{passive:true});
    window.addEventListener('touchmove',markInteract,{passive:true});
    transcript.addEventListener('pointerdown',markInteract,{passive:true});
    transcript.dataset.interactionBound='1';
  }
  const fragment=document.createDocumentFragment();
  source.forEach((entry,i)=>{
    const row=document.createElement('div');row.dataset.entry=i;row.className='transcript-row';
    const select=document.createElement('input');select.type='checkbox';select.className='transcript-select';select.dataset.selectSegment=String(i);select.setAttribute('aria-label',`选择第 ${i+1} 条字幕`);select.checked=selectedSegmentRows.has(i);
    select.onchange=()=>{select.checked?selectedSegmentRows.add(i):selectedSegmentRows.delete(i);updateSegmentSelection()};
    const seek=document.createElement('button');seek.type='button';seek.className='transcript-seek';
    const time=document.createElement('span');time.className='transcript-time';time.textContent=`${fmt(entry.start)}\n${fmt(entry.end)}`;
    const sourceText=document.createElement('span');sourceText.textContent=entry.text;
    const targetText=document.createElement('span');targetText.textContent=target[i]?.text||'（未翻译）';
    seek.append(time,sourceText,targetText);
    seek.onclick=()=>{lastTranscriptInteract=Date.now();player.seek(entry.start);player.play()};
    const edit=document.createElement('button');edit.type='button';edit.className='ghost small transcript-edit';edit.dataset.editSubtitle=String(i);edit.textContent='校正';
    edit.onclick=()=>openSubtitleEditor(i);
    row.append(select,seek,edit);fragment.append(row);
  });
  transcript.replaceChildren(fragment);
  transcriptRows=[...transcript.children];
  lastRenderedSourceIndex=-2;
  updateSubs();
  updateSegmentSelection();
}

const segmentToolbar=document.querySelector('[data-segment-toolbar]');
const segmentButton=document.querySelector('[data-open-segment-reprocess]');
function selectedSegmentIndices(){return [...selectedSegmentRows].sort((a,b)=>a-b)}
function updateSegmentSelection(){
  if(!segmentToolbar)return;
  const indices=selectedSegmentIndices();segmentToolbar.hidden=!transcriptsLoaded;
  const contiguous=indices.length>0&&indices.every((value,pos)=>pos===0||value===indices[pos-1]+1);
  segmentButton.disabled=!contiguous;
  const summary=segmentToolbar.querySelector('[data-segment-summary]');
  if(!indices.length){summary.textContent='勾选一条或连续多条字幕';return;}
  if(!contiguous){summary.textContent=`已选择 ${indices.length} 条，但范围不连续`;return;}
  summary.textContent=`已选择第 ${indices[0]+1}–${indices.at(-1)+1} 条 · `;
  const editTime=document.createElement('button');
  editTime.type='button';editTime.className='ghost small';editTime.dataset.editSegmentTime='';
  editTime.textContent=`${fmt(source[indices[0]].start)}–${fmt(source[indices.at(-1)].end)} ✎`;
  editTime.title='点击直接修改起止时间并配置重处理';
  editTime.onclick=()=>segmentButton.click();
  summary.append(editTime);
}
segmentToolbar?.querySelector('[data-clear-segment-selection]')?.addEventListener('click',()=>{selectedSegmentRows.clear();for(const input of document.querySelectorAll('[data-select-segment]'))input.checked=false;updateSegmentSelection()});
const segmentDialog=document.getElementById('segment-reprocess-dialog');
const segmentForm=segmentDialog?.querySelector('[data-segment-reprocess-form]');
function syncSegmentProcessorFields(){
  if(!segmentForm)return;const processor=segmentForm.elements.processor.value,mode=segmentForm.elements.processing_mode?.value||'transcribe_then_translate';
  for(const group of segmentForm.querySelectorAll('[data-processor-fields]'))group.hidden=group.dataset.processorFields!==processor;
  const llmField=segmentForm.querySelector('[data-text-llm-field]');if(llmField)llmField.hidden=processor==='gemini'&&mode==='bilingual_once';
}
segmentForm?.elements.processor?.addEventListener('change',syncSegmentProcessorFields);
segmentForm?.elements.processing_mode?.addEventListener('change',syncSegmentProcessorFields);
/* 表单级委泑：无论哪个控件以何种方式触发 change，都重新同步字段可见性 */
segmentForm?.addEventListener('change',syncSegmentProcessorFields);
segmentForm?.addEventListener('dialog-open-sync',syncSegmentProcessorFields);
segmentForm?.elements.asr_profile_id?.addEventListener('change',()=>{syncSegmentProcessorFields()});
syncSegmentProcessorFields();
function openSegmentDialogForIndices(indices){
  if(!segmentForm||!indices.length)return;
  segmentForm.elements.start_index.value=String(indices[0]+1);segmentForm.elements.end_index.value=String(indices.at(-1)+1);
  const first=source[indices[0]],last=source[indices.at(-1)];
  if(first)segmentForm.elements.start_time.value=String(Number(Number(first.start).toFixed(3)));
  if(last)segmentForm.elements.end_time.value=String(Number(Number(last.end).toFixed(3)));
  segmentForm.querySelector('[data-segment-range]').textContent=`第 ${indices[0]+1}–${indices.at(-1)+1} 条 · 可直接修改下方时间`;
  const error=segmentForm.querySelector('[data-segment-error]');error.hidden=true;error.textContent='';
  segmentForm.dispatchEvent(new Event('dialog-open-sync'));
  segmentDialog.showModal();
}
segmentButton?.addEventListener('click',()=>openSegmentDialogForIndices(selectedSegmentIndices()));
for(const button of segmentDialog?.querySelectorAll('[data-close-segment-reprocess]')||[])button.addEventListener('click',()=>segmentDialog.close());
/* 覆盖确认：开始/结束时间留空或越界时，告知将覆盖到音频开头/末尾并征询确认 */
function segmentCoverWarnings(){
  if(!segmentForm)return [];
  const startRaw=segmentForm.elements.start_time.value.trim();
  const endRaw=segmentForm.elements.end_time.value.trim();
  const startProvided=startRaw!=='',endProvided=endRaw!=='';
  if(!startProvided&&!endProvided)return []; // 两者皆空：走后端选中条目区间，不覆盖到边界
  const startVal=startProvided?parseFloat(startRaw):0;
  const endVal=endProvided?parseFloat(endRaw):0;
  const duration=audio&&Number.isFinite(audio.duration)&&audio.duration>0?audio.duration:0;
  const notes=[];
  if(!startProvided&&endProvided)notes.push('开始时间未指定，将覆盖到音频开头');
  if(!endProvided&&startProvided)notes.push('结束时间未指定，将覆盖到音频末尾');
  if(endProvided&&duration>0&&Number.isFinite(endVal)&&endVal>duration)notes.push('结束时间超过媒体时长，将覆盖到音频末尾');
  if(startProvided&&Number.isFinite(startVal)&&startVal<0)notes.push('开始时间早于 0，将覆盖到音频开头');
  return notes;
}
segmentForm?.addEventListener('submit',async event=>{
  event.preventDefault();const error=segmentForm.querySelector('[data-segment-error]');error.hidden=true;
  const notes=segmentCoverWarnings();
  if(notes.length&&!window.confirm(notes.join('；')+'。是否继续？'))return;
  const submit=segmentForm.querySelector('[type=submit]'),old=submit.textContent;submit.disabled=true;submit.textContent='处理中…';
  try{
    const response=await fetch(`/tracks/${track}/segments/reprocess`,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(segmentForm))});
    const data=await response.json().catch(()=>({}));
    if(response.status===202){
      segmentDialog.close();
      window.alert('已提交片段重处理任务，请在任务中心查看候选并接受替换。');
      return;
    }
    error.textContent=data.error||`片段重处理失败（HTTP ${response.status}）`;error.hidden=false;
  }finally{submit.disabled=false;submit.textContent=old;}
});

const editDialog=document.getElementById('subtitle-edit-dialog');
const editForm=editDialog?.querySelector('[data-subtitle-edit-form]');
function applyRevisionPayload(data){
  source=data.source||[];target=data.target||[];sourceIndex=targetIndex=0;selectedSegmentRows.clear();
  lastSourceText=lastTargetText='';
  (window.top.SubForgeFloatLyrics||window.SubForgeFloatLyrics)?.invalidate?.(track);
  if(transcriptsLoaded)renderTranscript();else updateSubs();
}
function openSubtitleEditor(index){
  if(!editDialog||!editForm)return;
  const src=source[index],tgt=target[index];
  if(!src&&!tgt)return;
  editForm.elements.index.value=String(index+1);
  editForm.elements.start.value=String((src||tgt).start);
  editForm.elements.end.value=String((src||tgt).end);
  editForm.elements.source_text.value=src?.text||'';
  editForm.elements.target_text.value=tgt?.text||'';
  const error=editForm.querySelector('[data-subtitle-edit-error]');error.hidden=true;error.textContent='';
  editDialog.showModal();
}
editDialog?.querySelector('[data-close-subtitle-edit]')?.addEventListener('click',()=>editDialog.close());
editForm?.addEventListener('submit',async event=>{
  event.preventDefault();
  const error=editForm.querySelector('[data-subtitle-edit-error]');error.hidden=true;
  const response=await fetch(`/tracks/${track}/subtitles/edit`,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(editForm))});
  const data=await response.json().catch(()=>({}));
  if(!response.ok){error.textContent=data.error||`保存失败（HTTP ${response.status}）`;error.hidden=false;return;}
  applyRevisionPayload(data);editDialog.close();
});
async function postStructure(values,error){
  const response=await fetch(`/tracks/${track}/subtitles/structure`,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(values)});
  const data=await response.json().catch(()=>({}));
  if(!response.ok){error.textContent=data.error||`操作失败（HTTP ${response.status}）`;error.hidden=false;return false;}
  applyRevisionPayload(data);return true;
}
editDialog?.querySelector('[data-subtitle-merge-next]')?.addEventListener('click',async()=>{
  const index=Number(editForm.elements.index.value),nextSource=source[index],nextTarget=target[index];
  const error=editForm.querySelector('[data-subtitle-edit-error]');error.hidden=true;
  if(!nextSource||!nextTarget){error.textContent='没有可合并的下一条字幕';error.hidden=false;return;}
  if(!confirm('确认把当前字幕与下一条合并？'))return;
  const ok=await postStructure({action:'merge',index:String(index),source_text:`${editForm.elements.source_text.value}\n${nextSource.text}`,target_text:`${editForm.elements.target_text.value}\n${nextTarget.text}`},error);
  if(ok)editDialog.close();
});
editDialog?.querySelector('[data-subtitle-delete]')?.addEventListener('click',async()=>{
  const error=editForm.querySelector('[data-subtitle-edit-error]');error.hidden=true;
  if(!confirm('确认删除这条源字幕和翻译字幕？此操作可以撤销。'))return;
  const ok=await postStructure({action:'delete',index:editForm.elements.index.value},error);
  if(ok)editDialog.close();
});
const splitDialog=document.getElementById('subtitle-split-dialog');
const splitForm=splitDialog?.querySelector('[data-subtitle-split-form]');
function splitSuggestion(text){
  const middle=Math.floor(text.length/2),marks=[...text.matchAll(/[。！？!?、，,]/g)];
  const cut=marks.length?marks.reduce((best,m)=>Math.abs((m.index||0)-middle)<Math.abs(best-middle)?(m.index||0)+1:best,(marks[0].index||0)+1):middle;
  return [text.slice(0,cut).trim(),text.slice(cut).trim()];
}
editDialog?.querySelector('[data-subtitle-split]')?.addEventListener('click',()=>{
  const index=Number(editForm.elements.index.value),entry=source[index-1]||target[index-1];
  const sourceParts=splitSuggestion(editForm.elements.source_text.value),targetParts=splitSuggestion(editForm.elements.target_text.value);
  splitForm.elements.index.value=String(index);
  splitForm.elements.split_time.value=String(Number(((entry.start+entry.end)/2).toFixed(3)));
  splitForm.elements.source_first.value=sourceParts[0];splitForm.elements.source_second.value=sourceParts[1];
  splitForm.elements.target_first.value=targetParts[0];splitForm.elements.target_second.value=targetParts[1];
  splitForm.querySelector('[data-subtitle-split-error]').hidden=true;
  editDialog.close();splitDialog.showModal();
});
for(const button of splitDialog?.querySelectorAll('[data-close-subtitle-split]')||[])button.addEventListener('click',()=>splitDialog.close());
splitForm?.addEventListener('submit',async event=>{
  event.preventDefault();const error=splitForm.querySelector('[data-subtitle-split-error]');error.hidden=true;
  const values=Object.fromEntries(new FormData(splitForm));values.action='split';
  if(await postStructure(values,error))splitDialog.close();
});
editDialog?.querySelector('[data-subtitle-reprocess]')?.addEventListener('click',()=>{
  const index=Number(editForm.elements.index.value);
  if(!index||!source[index-1]&&!target[index-1])return;
  selectedSegmentRows.clear();selectedSegmentRows.add(index-1);
  for(const input of document.querySelectorAll('[data-select-segment]'))input.checked=selectedSegmentRows.has(Number(input.dataset.selectSegment));
  updateSegmentSelection();
  editDialog.close();
  openSegmentDialogForIndices([index-1]);
});
for(const button of editDialog?.querySelectorAll('[data-restore-subtitles]')||[])button.addEventListener('click',async()=>{
  const kind=button.dataset.restoreSubtitles;
  const label=kind==='baseline'?'自动生成版本':'上次修改前版本';
  if(!confirm(`确认恢复${label}？当前字幕会先保存为可撤销快照。`))return;
  const response=await fetch(`/tracks/${track}/subtitles/restore/${kind}`,{method:'POST'});
  const data=await response.json().catch(()=>({}));
  const error=editForm.querySelector('[data-subtitle-edit-error]');
  if(!response.ok){error.textContent=data.error||`恢复失败（HTTP ${response.status}）`;error.hidden=false;return;}
  applyRevisionPayload(data);editDialog.close();
});
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
