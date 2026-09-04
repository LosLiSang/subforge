/* 主题：黑色/白色两套玻璃拟态配色，主页面与 iframe 共享选择。 */
(()=>{
  const key='subforge.theme';
  const apply=theme=>{
    const value=theme==='light'?'light':'dark';
    document.documentElement.dataset.theme=value;
    const toggle=document.querySelector('[data-theme-toggle]');
    if(toggle){
      toggle.classList.toggle('is-light',value==='light');
      const label=toggle.querySelector('[data-theme-label]');
      if(label)label.textContent=value==='light'?'黑色主题':'白色主题';
      toggle.title=value==='light'?'切换到黑色主题':'切换到白色主题';
    }
  };
  apply(localStorage.getItem(key)||'dark');
  document.querySelector('[data-theme-toggle]')?.addEventListener('click',()=>{
    const next=document.documentElement.dataset.theme==='light'?'dark':'light';
    localStorage.setItem(key,next);apply(next);
  });
  window.addEventListener('storage',event=>{if(event.key===key)apply(event.newValue||'dark');});
})();
for(const form of document.querySelectorAll('form[data-secure]')){form.addEventListener('submit',e=>{if(form.dataset.confirm&&!confirm(form.dataset.confirm)){e.preventDefault();return}let input=form.querySelector('input[name=csrf_token]');if(!input){input=document.createElement('input');input.type='hidden';input.name='csrf_token';form.append(input)}input.value=window.SUBFORGE_CSRF||'';});}
const originalFetch=window.fetch;window.fetch=(input,init={})=>{init.headers=new Headers(init.headers||{});if(init.method&&init.method.toUpperCase()!=='GET'){init.headers.set('X-CSRF-Token',window.SUBFORGE_CSRF||'');}return originalFetch(input,init)};
const picker=document.getElementById('pick-audio');if(picker)picker.addEventListener('click',async()=>{const dialog=document.getElementById('import-dialog');if(!dialog)return;dialog.showModal();});
/* 导入弹窗：本地 tab 内点按钮才触发文件选择 */
const pickImportFile=document.querySelector('[data-pick-import-file]');if(pickImportFile)pickImportFile.addEventListener('click',async()=>{const response=await fetch('/picker/audio',{method:'POST'});if(!response.ok)return;const data=await response.json();if(data.cancelled)return;document.getElementById('selection-id').value=data.selection_id;document.getElementById('selected-name').textContent=data.filename;});
/* 导入 Dialog：本地文件 / 链接下载 / RJ 文件夹，无动画切换并分别保留输入。 */
for(const tab of document.querySelectorAll('[data-import-tab]'))tab.addEventListener('click',()=>{const dialog=tab.closest('#import-dialog');for(const other of dialog.querySelectorAll('[data-import-tab]')){const active=other===tab;other.classList.toggle('active',active);other.setAttribute('aria-selected',active?'true':'false')}for(const panel of dialog.querySelectorAll('[data-import-panel]'))panel.hidden=panel.dataset.importPanel!==tab.dataset.importTab});
/* 导入弹窗：类型切换控制 RJ 号字段显隐（仅 RJ 作品有 RJ 号） */
function syncKindFields(){for(const sel of document.querySelectorAll('[data-kind-select]')){const scope=sel.closest('[data-import-panel], [data-work-edit-form]')||sel.closest('form');const rjField=scope?.querySelector('[data-rj-field]');if(rjField)rjField.style.display=sel.value==='rj_work'?'':'none';const creatorPicker=scope?.querySelector('[data-creator-picker]');if(creatorPicker){creatorPicker.dataset.contextKind=sel.value;creatorPicker.dispatchEvent(new CustomEvent('creator-context-change'));}}}
for(const sel of document.querySelectorAll('[data-kind-select]')){sel.addEventListener('change',syncKindFields);}syncKindFields();

/* 可复用创作者 Tag 输入：点击显示全部、忽略大小写/空格的前缀匹配、逗号/Enter 添加。 */
const normalizeCreatorName=value=>(value||'').toLocaleLowerCase().replace(/\s+/g,'');
function creatorTagElement(picker,creator){const tag=document.createElement('span');tag.className=`creator-tag creator-tag-${creator.kind}`;tag.dataset.selectedId=creator.creator_id;tag.textContent=creator.name;const remove=document.createElement('button');remove.type='button';remove.dataset.removeTag='';remove.setAttribute('aria-label',`移除 ${creator.name}`);remove.textContent='×';const hidden=document.createElement('input');hidden.type='hidden';hidden.name=picker.dataset.fieldName;hidden.value=creator.creator_id;tag.append(remove,hidden);return tag}
function creatorFromOption(option){return{creator_id:option.dataset.creatorId,name:option.dataset.creatorName,kind:option.dataset.creatorKind}}
function setupCreatorPicker(picker){const input=picker.querySelector('[data-creator-search]'),suggestions=picker.querySelector('[data-creator-suggestions]'),tags=picker.querySelector('[data-selected-tags]'),create=picker.querySelector('[data-create-from-picker]'),empty=picker.querySelector('[data-suggestion-empty]');if(!input||!suggestions)return;
 const selected=()=>new Set([...picker.querySelectorAll('[data-selected-id]')].map(x=>x.dataset.selectedId));
 const allowed=option=>(!picker.dataset.excludeId||option.dataset.creatorId!==picker.dataset.excludeId)&&(!picker.dataset.allowedKind||option.dataset.creatorKind===picker.dataset.allowedKind)&&(picker.dataset.contextKind!=='stream_archive'||option.dataset.creatorKind==='voice_actor');
 const refresh=(open=true)=>{const q=normalizeCreatorName(input.value),chosen=selected();let visible=0;for(const option of picker.querySelectorAll('[data-creator-option]')){const show=allowed(option)&&!chosen.has(option.dataset.creatorId)&&normalizeCreatorName(option.dataset.creatorName).startsWith(q);option.hidden=!show;if(show)visible++}const canCreate=picker.dataset.allowCreate!=='false'&&!!input.value.trim()&&visible===0;if(create){create.hidden=!canCreate;create.querySelector('[data-create-name]').textContent=input.value.trim()}if(empty)empty.hidden=visible>0||canCreate;if(open){const firstOpen=suggestions.hidden;suggestions.hidden=false;const w=suggestions.ownerDocument.defaultView;let up=picker.dataset.sugUp==='1';if(firstOpen){const pr=picker.getBoundingClientRect();up=suggestions.getBoundingClientRect().bottom>w.innerHeight&&pr.top>w.innerHeight-pr.bottom;picker.dataset.sugUp=up?'1':'0'}suggestions.classList.toggle('creator-suggestions-up',up)}};
 const changed=()=>{if(picker.closest('[data-creator-filter-form]'))picker.closest('form').requestSubmit()};
 const add=creator=>{if(selected().has(creator.creator_id))return;if(Number(picker.dataset.maxItems||0)===1)for(const tag of picker.querySelectorAll('[data-selected-id]'))tag.remove();tags.insertBefore(creatorTagElement(picker,creator),input);input.value='';suggestions.hidden=true;changed()};
 picker._addCreator=add;picker._refreshCreators=refresh;
 picker.querySelector('[data-picker-control]')?.addEventListener('click',()=>{input.focus();refresh()});input.addEventListener('focus',refresh);input.addEventListener('input',refresh);input.addEventListener('keydown',event=>{if(event.key==='Backspace'&&!input.value){const last=[...picker.querySelectorAll('[data-selected-id]')].at(-1);if(last){event.preventDefault();last.remove();refresh();changed()}}if(event.key==='Enter'||event.key===','){event.preventDefault();const first=[...picker.querySelectorAll('[data-creator-option]')].find(x=>!x.hidden);if(first)add(creatorFromOption(first));else if(create&&!create.hidden)create.click()}});
 picker.addEventListener('click',event=>{const remove=event.target.closest('[data-remove-tag]');if(remove){remove.closest('[data-selected-id]').remove();refresh();changed();return}const option=event.target.closest('[data-creator-option]');if(option){add(creatorFromOption(option));return}if(event.target.closest('[data-create-from-picker]'))openCreatorCreateDialog(picker,input.value.trim())});picker.addEventListener('creator-context-change',()=>refresh(false));picker.closest('dialog')?.addEventListener('close',()=>delete picker.dataset.sugUp)}
for(const pickerElement of document.querySelectorAll('[data-creator-picker]'))setupCreatorPicker(pickerElement);
document.addEventListener('click',event=>{for(const picker of document.querySelectorAll('[data-creator-picker]'))if(!picker.contains(event.target)){const suggestions=picker.querySelector('[data-creator-suggestions]');if(suggestions){suggestions.hidden=true;delete picker.dataset.sugUp}}});
function appendCreatorOption(creator){for(const picker of document.querySelectorAll('[data-creator-picker]')){const list=picker.querySelector('[data-creator-suggestions]');if(!list||picker.querySelector(`[data-creator-option][data-creator-id="${creator.creator_id}"]`))continue;const option=document.createElement('button');option.type='button';option.className='creator-suggestion';option.dataset.creatorOption='';option.dataset.creatorId=creator.creator_id;option.dataset.creatorName=creator.name;option.dataset.creatorKind=creator.kind;option.innerHTML=`<span class="creator-tag creator-tag-${creator.kind}"></span><small>${creator.kind==='circle'?'社团':'声优'}</small>`;option.querySelector('span').textContent=creator.name;list.insertBefore(option,list.querySelector('[data-create-from-picker]'))}}
function openCreatorCreateDialog(picker,name){const dialog=document.querySelector('[data-creator-create-dialog]');if(!dialog)return;const form=dialog.querySelector('[data-creator-create-form]');form.reset();form.elements.picker_id.value=picker.dataset.pickerId;form.elements.name.value=name||'';const stream=picker.dataset.contextKind==='stream_archive';form.elements.kind.value=stream?'voice_actor':'voice_actor';for(const radio of form.elements.kind)radio.disabled=stream&&radio.value!=='voice_actor';dialog.querySelector('[data-dialog-error]').hidden=true;dialog.showModal();form.elements.name.focus()}
for(const form of document.querySelectorAll('[data-creator-create-form]'))form.addEventListener('submit',async event=>{event.preventDefault();const dialog=form.closest('dialog'),error=dialog.querySelector('[data-dialog-error]');error.hidden=true;const body=new URLSearchParams(new FormData(form)).toString();const response=await fetch('/api/creators',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});const data=await response.json().catch(()=>({}));if(!response.ok){error.textContent=data.error||`创建失败（HTTP ${response.status}）`;error.hidden=false;return}appendCreatorOption(data);document.querySelector(`[data-picker-id="${form.elements.picker_id.value}"]`)?._addCreator(data);dialog.close()});
for(const button of document.querySelectorAll('[data-test-endpoint]'))button.addEventListener('click',async()=>{const output=button.closest('.profile-row-actions')?.querySelector('.check-result')||button.parentElement.querySelector('.check-result');if(!output)return;const label=button.querySelector('span'),originalLabel=label?.textContent;button.disabled=true;if(label)label.textContent='测试中';output.textContent='检查中…';try{const response=await fetch(button.dataset.testEndpoint,{method:'POST'});const data=await response.json().catch(()=>({ok:false,message:`HTTP ${response.status}`}));output.textContent=data.ok?`✅ ${data.message}`:`❌ ${data.message||data.ok}`;}catch(e){output.textContent=`❌ ${e.message||e}`;}finally{button.disabled=false;if(label)label.textContent=originalLabel;}});
for(const button of document.querySelectorAll('[data-pick-directory]'))button.addEventListener('click',async()=>{const response=await fetch('/picker/directory',{method:'POST'});if(!response.ok)return;const data=await response.json();if(data.cancelled)return;const field=button.dataset.field,form=button.closest('form');form.elements[`${field}_selection`].value=data.selection_id;form.elements[field].value=data.name;});
for(const button of document.querySelectorAll('[data-pick-cover]'))button.addEventListener('click',async()=>{const response=await fetch('/picker/image',{method:'POST'});if(!response.ok)return;const data=await response.json();if(data.cancelled)return;const form=button.closest('form');form.elements.selection_id.value=data.selection_id;form.querySelector('[data-cover-name]').textContent=data.filename;button.textContent='应用封面';button.type='submit';});
const workEditDialog=document.getElementById('work-edit-dialog');
function resetCreatorPicker(picker){clearCreatorPicker(picker);for(const id of (picker.dataset.initialIds||'').split(',').filter(Boolean)){const option=picker.querySelector(`[data-creator-option][data-creator-id="${id}"]`);if(option)picker._addCreator(creatorFromOption(option))}}
document.querySelector('[data-open-work-edit]')?.addEventListener('click',()=>{const form=workEditDialog.querySelector('[data-work-edit-form]');form.reset();resetCreatorPicker(form.querySelector('[data-creator-picker]'));const preview=form.querySelector('[data-work-cover-preview]');preview.src=preview.dataset.originalSrc;preview.hidden=false;form.querySelector('[data-cover-filename]').textContent='当前封面';form.querySelector('[data-work-edit-error]').hidden=true;syncKindFields();workEditDialog.showModal()});
document.querySelector('[data-pick-work-cover]')?.addEventListener('click',async event=>{const response=await fetch('/picker/image',{method:'POST'});const data=await response.json().catch(()=>({}));const form=event.target.closest('form'),error=form.querySelector('[data-work-edit-error]');if(!response.ok||data.cancelled){if(!data.cancelled){error.textContent=data.error||'无法打开图片选择器';error.hidden=false}return}form.elements.selection_id.value=data.selection_id;const preview=form.querySelector('[data-work-cover-preview]');preview.src=`/api/selections/${data.selection_id}/image`;preview.hidden=false;form.querySelector('[data-cover-filename]').textContent=data.filename});
document.querySelector('[data-work-edit-form]')?.addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,error=form.querySelector('[data-work-edit-error]');error.hidden=true;const body=new URLSearchParams(new FormData(form)).toString();const response=await fetch(form.action,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body});const data=await response.json().catch(()=>({}));if(!response.ok){error.textContent=data.error||`保存失败（HTTP ${response.status}）`;error.hidden=false;return}location.reload()});
function showTaskMessage(row,message){let output=row.querySelector('.task-center-message');if(!output&&message){output=document.createElement('p');output.className='task-center-message';row.append(output)}if(!output)return;output.textContent=message||'';clearInterval(output._countdown);const match=(message||'').match(/(\d+)秒后重试/);if(!match)return;let seconds=Number(match[1]);output._countdown=setInterval(()=>{seconds=Math.max(0,seconds-1);output.textContent=message.replace(/\d+秒后重试/,`${seconds}秒后重试`);if(seconds===0)clearInterval(output._countdown)},1000)}
const taskRows=[...document.querySelectorAll('[data-task-id]')];
for(const row of taskRows)showTaskMessage(row,row.querySelector('.task-center-message')?.textContent||'');
let taskPollInFlight=false;
async function pollTaskRows(){
 if(taskPollInFlight||document.hidden)return;
 const active=taskRows.filter(row=>['queued','running'].includes(row.querySelector('.task-status')?.textContent.trim()));
 if(!active.length)return;
 taskPollInFlight=true;
 try{
  const query=new URLSearchParams();for(const row of active)query.append('task_id',row.dataset.taskId);
  const response=await fetch(`/api/tasks/status?${query}`);if(!response.ok)return;
  const byId=new Map((await response.json()).map(task=>[task.task_id,task]));let reachedTerminal=false;
  for(const row of active){const task=byId.get(row.dataset.taskId);if(!task)continue;const status=row.querySelector('.task-status'),stage=row.querySelector('.task-stage'),progress=row.querySelector('.task-progress'),batches=row.querySelector('.task-batches');if(status)status.textContent=task.status;if(stage&&task.stage)stage.textContent=task.stage;if(progress&&task.progress!=null)progress.textContent=Math.round(task.progress*100);if(batches&&task.total!=null)batches.textContent=`${task.completed||0} / ${task.total}`;if(task.message!=null)showTaskMessage(row,task.message);if(!['queued','running'].includes(task.status))reachedTerminal=true}
  if(reachedTerminal)location.reload();
 }catch(_error){}finally{taskPollInFlight=false}
}
function taskPollDelay(){const fastStage=taskRows.some(row=>{const status=row.querySelector('.task-status')?.textContent.trim(),stage=row.querySelector('.task-stage')?.textContent.trim();return['queued','running'].includes(status)&&['model','asr'].includes(stage)});return fastStage?250:1000}
async function scheduleTaskPoll(){await pollTaskRows();setTimeout(scheduleTaskPoll,taskPollDelay())}
if(taskRows.length){scheduleTaskPoll();document.addEventListener('visibilitychange',pollTaskRows)}
/* 设置页 Tab 切换：同屏只显示一个分区，表单仍是一个整体（保存语义不变） */
for(const tab of document.querySelectorAll('.tab-bar .tab')){tab.addEventListener('click',()=>{const name=tab.dataset.tab;for(const t of document.querySelectorAll('.tab-bar .tab')){t.classList.toggle('active',t===tab);t.setAttribute('aria-selected',t===tab?'true':'false')}for(const panel of document.querySelectorAll('[data-tab-panel]'))panel.classList.toggle('active',panel.dataset.tabPanel===name);});}
/* 配置弹窗：新增/复制/编辑共用一个 dialog，浏览器端始终不接触已有 Key。 */
for(const button of document.querySelectorAll('[data-open-dialog]')){button.addEventListener('click',()=>{const dialog=document.getElementById(button.dataset.openDialog);if(!dialog)return;const form=dialog.querySelector('form'),title=dialog.querySelector('[data-dialog-title]'),submit=dialog.querySelector('[data-dialog-submit]');form.reset();form.elements.profile_id.value='';form.elements.copy_from_profile_id.value='';form.elements.api_key.placeholder='可选';const raw=button.dataset.copyProfile||button.dataset.editProfile;if(raw){const p=JSON.parse(raw);form.elements.name.value=p.name||'';form.elements.base_url.value=p.base_url||'';form.elements.model.value=p.model||'';form.elements.api_key.value='';form.elements.proxy_url.value=p.proxy_url||'';form.elements.ca_bundle.value=p.ca_bundle||'';form.elements.verify_tls.checked=p.verify_tls!==false;if(button.dataset.copyProfile){form.elements.copy_from_profile_id.value=p.profile_id||'';form.elements.name.value=`${p.name||'未命名配置'} 副本`;form.elements.api_key.placeholder='留空复制原配置凭据';title.textContent='复制配置';submit.textContent='创建副本';}else{form.elements.profile_id.value=p.profile_id||'';form.elements.api_key.placeholder='留空保持不变';title.textContent='编辑配置';submit.textContent='保存';}}else{title.textContent='新增配置';submit.textContent='创建配置';}dialog.showModal();form.elements.name.focus();if(button.dataset.copyProfile)form.elements.name.select();});}
for(const button of document.querySelectorAll('[data-close-dialog]'))button.addEventListener('click',()=>button.closest('dialog')?.close());

/* 创作者管理：分组搜索、行菜单，以及添加/修改/合并/删除 Dialog。 */
for(const search of document.querySelectorAll('[data-creator-list-search]'))search.addEventListener('input',()=>{const q=normalizeCreatorName(search.value);for(const row of search.closest('[data-tab-panel]').querySelectorAll('[data-creator-row]'))row.hidden=!normalizeCreatorName(row.dataset.creatorName).startsWith(q)});
for(const button of document.querySelectorAll('[data-creator-menu-button]'))button.addEventListener('click',event=>{event.stopPropagation();const menu=button.parentElement.querySelector('[data-creator-menu]');for(const other of document.querySelectorAll('[data-creator-menu]'))if(other!==menu)other.hidden=true;menu.hidden=!menu.hidden});
document.addEventListener('click',()=>{for(const menu of document.querySelectorAll('[data-creator-menu]'))menu.hidden=true});
const manageCreate=document.getElementById('creator-manage-create');document.querySelector('[data-open-creator-create]')?.addEventListener('click',()=>{const active=document.querySelector('.creator-tabs .tab.active')?.dataset.tab||'circle';manageCreate.querySelector(`input[name="kind"][value="${active}"]`).checked=true;manageCreate.showModal();manageCreate.querySelector('input[name="name"]').focus()});
for(const button of document.querySelectorAll('[data-edit-creator]'))button.addEventListener('click',()=>{const dialog=document.getElementById('creator-edit-dialog'),form=dialog.querySelector('form');form.elements.creator_id.value=button.dataset.id;form.elements.name.value=button.dataset.name;dialog.querySelector('[data-edit-kind]').innerHTML=`<span class="creator-tag creator-tag-${button.dataset.kind}">${button.dataset.kind==='circle'?'社团':'声优'}</span>`;dialog.showModal();form.elements.name.focus()});
function clearCreatorPicker(picker){for(const tag of picker.querySelectorAll('[data-selected-id]'))tag.remove();const input=picker.querySelector('[data-creator-search]');if(input)input.value='';picker._refreshCreators?.(false)}
function openMergeDialog(data){const dialog=document.getElementById('creator-merge-dialog'),form=dialog.querySelector('form'),picker=dialog.querySelector('[data-creator-picker]');form.elements.source_id.value=data.id;dialog.querySelector('[data-merge-source-name]').innerHTML=`<span class="creator-tag creator-tag-${data.kind}">${data.name}</span>`;dialog.querySelector('[data-merge-source-count]').textContent=`关联 ${data.count} 部作品`;clearCreatorPicker(picker);picker.dataset.allowedKind=data.kind;picker.dataset.excludeId=data.id;picker.dispatchEvent(new CustomEvent('creator-context-change'));dialog.showModal();picker.querySelector('[data-creator-search]').focus()}
for(const button of document.querySelectorAll('[data-merge-creator]'))button.addEventListener('click',()=>openMergeDialog(button.dataset));
for(const button of document.querySelectorAll('[data-delete-creator]'))button.addEventListener('click',()=>{const dialog=document.getElementById('creator-delete-dialog'),form=dialog.querySelector('form'),count=Number(button.dataset.count);form.elements.creator_id.value=button.dataset.id;dialog.dataset.sourceId=button.dataset.id;dialog.dataset.sourceName=button.dataset.name;dialog.dataset.sourceKind=button.dataset.kind;dialog.dataset.sourceCount=button.dataset.count;dialog.querySelector('[data-delete-title]').textContent=count?'无法删除创作者':'删除创作者';dialog.querySelector('[data-delete-message]').textContent=count?`“${button.dataset.name}”仍关联 ${count} 部作品，请先合并到同身份创作者。`:`确定删除“${button.dataset.name}”吗？`;dialog.querySelector('[data-confirm-delete]').hidden=count>0;dialog.querySelector('[data-delete-to-merge]').hidden=count===0;dialog.showModal()});
document.querySelector('[data-delete-to-merge]')?.addEventListener('click',event=>{const dialog=event.target.closest('dialog');dialog.close();openMergeDialog({id:dialog.dataset.sourceId,name:dialog.dataset.sourceName,kind:dialog.dataset.sourceKind,count:dialog.dataset.sourceCount})});
/* 删除配置：二次点击确认，3 秒后自动复位 */
for(const button of document.querySelectorAll('[data-two-step]')){const confirmText='确认删除？';let armed=false,timer=null;button.addEventListener('click',e=>{if(!armed){e.preventDefault();armed=true;button.dataset.originalText=button.textContent;button.textContent=confirmText;button.classList.add('armed');timer=setTimeout(()=>{armed=false;button.textContent=button.dataset.originalText;button.classList.remove('armed')},3000);}else{clearTimeout(timer);}});}
for(const button of document.querySelectorAll('[data-delete-deepgram]')){let armed=false,timer=null;button.addEventListener('click',async()=>{if(!armed){armed=true;button.textContent='确认';button.classList.add('armed');timer=setTimeout(()=>{armed=false;button.textContent='×';button.classList.remove('armed')},3000);return}clearTimeout(timer);const response=await fetch('/settings/deepgram/delete-key',{method:'POST'});if(!response.ok){armed=false;button.textContent='×';button.classList.remove('armed');return}const status=document.querySelector('[data-deepgram-status]');status.textContent='未配置';status.classList.remove('ok');button.remove()})}

/* 作品库搜索：服务端跨分页检索，输入停顿后刷新并回到第一页。 */
const workSearch = document.getElementById('work-search');
if (workSearch) {
  let searchTimer = null;
  let composing = false;
  const applyWorkSearch = () => {
    clearTimeout(searchTimer);
    const url = new URL(window.location.href);
    const query = workSearch.value.trim();
    if (query) url.searchParams.set('q', query); else url.searchParams.delete('q');
    url.searchParams.delete('page');
    const target = `${url.pathname}${url.search}`;
    if (target !== `${window.location.pathname}${window.location.search}`) window.location.assign(target);
  };
  const scheduleWorkSearch = () => {
    if (composing) return;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyWorkSearch, 350);
  };
  workSearch.addEventListener('input', scheduleWorkSearch);
  workSearch.addEventListener('compositionstart', () => { composing = true; });
  workSearch.addEventListener('compositionend', () => { composing = false; scheduleWorkSearch(); });
  workSearch.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); applyWorkSearch(); }
  });
}

/* iframe 外壳：通知顶层当前路径（侧边栏高亮） */
if (window.parent !== window) {
  try {
    window.parent.postMessage({ __navPath: window.location.pathname }, window.location.origin);
  } catch (e) {}
}

/* 作品详情：处理设置统一在 Dialog 中编辑，单音轨与整部作品共用。 */
const processingDialog=document.getElementById('processing-dialog');
for(const button of document.querySelectorAll('[data-open-processing]'))button.addEventListener('click',()=>{if(!processingDialog)return;const form=processingDialog.querySelector('[data-processing-form]');form.action=button.dataset.action;form.elements.mode.value=button.dataset.mode||'continue';form.elements.mode.dispatchEvent(new Event('change',{bubbles:true}));processingDialog.querySelector('[data-processing-title]').textContent=button.dataset.title||'处理设置';button.closest('details')?.removeAttribute('open');processingDialog.showModal()});
const processingForm=document.querySelector('[data-processing-form]');
processingForm?.addEventListener('submit',event=>{if(processingForm.elements.mode.value!=='from_scratch')return;if(!window.confirm('从头进行 ASR 与翻译会覆盖现有源字幕、翻译字幕，并清除断点记录（原字幕会保留备份）。是否继续？'))event.preventDefault()});
const trackRenameDialog=document.getElementById('track-rename-dialog');
for(const button of document.querySelectorAll('[data-open-track-rename]'))button.addEventListener('click',()=>{if(!trackRenameDialog)return;const form=trackRenameDialog.querySelector('[data-track-rename-form]');form.action=button.dataset.action;form.elements.filename.value=button.dataset.filename||'';button.closest('details')?.removeAttribute('open');trackRenameDialog.showModal();form.elements.filename.focus();form.elements.filename.select()});
function formatTrackDuration(value){if(!Number.isFinite(value))return'--:--';const total=Math.max(0,Math.round(value)),hours=Math.floor(total/3600),minutes=Math.floor(total%3600/60),seconds=total%60;return hours?`${hours}:${String(minutes).padStart(2,'0')}:${String(seconds).padStart(2,'0')}`:`${minutes}:${String(seconds).padStart(2,'0')}`}
for(const output of document.querySelectorAll('[data-track-duration]')){if(output.textContent.trim()!=='--:--')continue;const audio=new Audio();audio.preload='metadata';audio.addEventListener('loadedmetadata',()=>{output.textContent=formatTrackDuration(audio.duration);audio.src=''});audio.addEventListener('error',()=>{output.textContent='--:--'});audio.src=output.dataset.trackDuration;}
/* 同一时间只展开一个音轨操作菜单。 */
for(const menu of document.querySelectorAll('.track-menu'))menu.addEventListener('toggle',()=>{if(!menu.open)return;for(const other of document.querySelectorAll('.track-menu[open]'))if(other!==menu)other.removeAttribute('open')});
/* 点击音轨行主体 → 打开播放器详情页；行内按钮/菜单不触发导航。 */
for(const row of document.querySelectorAll('.track-row[data-track-player]')){const navigate=()=>{if(!row.dataset.trackPlayer)return;window.location.href=row.dataset.trackPlayer};row.addEventListener('click',event=>{if(event.target.closest('a,button,form,details,.track-menu,input,select,textarea,[data-task-id]'))return;navigate()});row.addEventListener('keydown',event=>{if(event.key!=='Enter'&&event.key!==' ')return;const active=document.activeElement;if(active&&active!==row&&row.contains(active))return;event.preventDefault();navigate()})}

/* 就地播放：点击 data-play-track 时在底部条中开始播放（不跳转页面）。
 * 按钮在内容页（iframe 内），播放条在顶层——驱动 window.top 的全局播放器。 */
for (const btn of document.querySelectorAll('[data-play-track]')) {
  btn.addEventListener('click', () => {
    const url = btn.dataset.playTrack;
    const trackId = url.split('/').filter(Boolean).slice(-2)[0];
    const row = btn.closest('.track-row');
    const title = row?.querySelector('h2')?.textContent || '播放中';
    const player = window.top.SubForgePlayer || window.SubForgePlayer;
    if (!player) return;
    player.setTrack(trackId, title, row?.dataset.itemId || '');
    player.play(); // 切换音轨后直接播放（此刻有用户手势，自动播放放行）
    const topBar = window.top.document?.getElementById('player-bar');
    if (topBar) topBar.hidden = false;
  });
}

/* URL 下载导入：fetch 提交，错误在对话框内友好显示（避免裸 JSON 页面） */
const folderImportForm=document.querySelector('[data-folder-import-form]');
const folderPreviewDialog=document.getElementById('folder-import-preview');
document.querySelector('[data-pick-media-folder]')?.addEventListener('click',async()=>{const response=await fetch('/picker/media-folder',{method:'POST'});const data=await response.json().catch(()=>({}));const error=folderImportForm.querySelector('[data-folder-error]');if(!response.ok||data.cancelled){if(!data.cancelled){error.textContent=data.error||'无法打开文件夹选择器';error.hidden=false}return}folderImportForm.elements.selection_id.value=data.selection_id;folderImportForm.querySelector('[data-folder-name]').textContent=data.name;error.hidden=true});
document.querySelector('[data-preview-folder-import]')?.addEventListener('click',async()=>{const error=folderImportForm.querySelector('[data-folder-error]');error.hidden=true;if(!folderImportForm.elements.selection_id.value){error.textContent='请先选择 RJ 文件夹';error.hidden=false;return}if(!folderImportForm.elements.rj_code.value.trim()){error.textContent='请填写 RJ 号';error.hidden=false;return}const body=new URLSearchParams({selection_id:folderImportForm.elements.selection_id.value}).toString();const response=await fetch('/api/import-folders/preview',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});const data=await response.json().catch(()=>({}));if(!response.ok){error.textContent=data.error||'扫描文件夹失败';error.hidden=false;return}folderPreviewDialog.querySelector('[data-preview-audio]').textContent=data.audio_count;folderPreviewDialog.querySelector('[data-preview-video]').textContent=data.video_count;folderPreviewDialog.querySelector('[data-preview-skipped]').textContent=data.skipped_count;folderPreviewDialog.querySelector('[data-preview-folder]').textContent=`${data.folder} · 共 ${data.media_count} 个媒体文件`;const list=folderPreviewDialog.querySelector('[data-preview-files]');list.replaceChildren(...data.files.map(name=>{const li=document.createElement('li');li.textContent=name;return li}));folderPreviewDialog.showModal()});
document.querySelector('[data-confirm-folder-import]')?.addEventListener('click',async event=>{const button=event.currentTarget;button.disabled=true;button.textContent='开始中…';const body=new URLSearchParams(new FormData(folderImportForm)).toString();const response=await fetch(folderImportForm.action,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});const data=await response.json().catch(()=>({}));if(!response.ok){button.disabled=false;button.textContent='开始导入';folderPreviewDialog.close();const error=folderImportForm.querySelector('[data-folder-error]');error.textContent=data.error||'无法开始文件夹导入';error.hidden=false;return}folderPreviewDialog.close();document.getElementById('import-dialog')?.close();window.location.href='/downloads'});

const urlImportForm = document.querySelector('[data-import-url-form]');
if (urlImportForm) {
  urlImportForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = urlImportForm.querySelector('[data-import-error]');
    const btn = urlImportForm.querySelector('[data-import-submit]');
    errEl.hidden = true;
    const formData = new FormData(urlImportForm);
    formData.append('csrf_token', window.SUBFORGE_CSRF || '');
    // 服务端 _read_form 用 parse_qs 解析 urlencoded body（不支持 multipart）
    const body = new URLSearchParams(formData).toString();
    btn.disabled = true;
    btn.textContent = '下载中…';
    try {
      const resp = await fetch(urlImportForm.action, { method: 'POST', body, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
      const data = await resp.json().catch(() => ({}));
      if (resp.status === 202 && data.task_id) {
        // 异步：轮询后台下载状态，完成后跳转到作品页
        btn.textContent = '下载中…';
        for (;;) {
          await new Promise(r => setTimeout(r, 1500));
          const st = await fetch(`/api/imports/${data.task_id}`).then(r => r.json()).catch(() => null);
          if (!st) continue;
          if (st.status === 'done' && st.item_id) { window.location.href = `/items/${st.item_id}`; return; }
          if (st.status === 'error') { errEl.textContent = st.message || '下载失败'; errEl.hidden = false; break; }
          btn.textContent = st.message || '下载中…';
        }
      } else if (!resp.ok || data.error) {
        errEl.textContent = data.error || `下载失败（HTTP ${resp.status}），请稍后重试`;
        errEl.hidden = false;
      }
    } catch (err) {
      errEl.textContent = `下载失败：${err.message}`;
      errEl.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = '下载并导入';
    }
  });
}

/* ─── 自定义深色下拉：原生 <select> 的 popup 在真实浏览器无法用 option CSS 接管，改为自定义渲染 ─── */
function enhanceSelects(root = document) {
  const selects = root.querySelectorAll('select[data-custom-select]');
  for (const sel of selects) {
    if (sel.dataset.enhanced) continue;
    sel.dataset.enhanced = 'true';

    const wrap = document.createElement('div');
    wrap.className = 'custom-select-wrap';

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'custom-select-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');

    const label = document.createElement('span');
    label.className = 'custom-select-label';
    label.textContent = sel.options[sel.selectedIndex]?.textContent || '';
    trigger.append(label);

    const chev = document.createElement('span');
    chev.className = 'custom-select-chev';
    chev.setAttribute('aria-hidden', 'true');
    trigger.append(chev);

    const menu = document.createElement('div');
    menu.className = 'custom-select-menu';
    menu.setAttribute('role', 'listbox');
    menu.hidden = true;

    function renderOptions() {
      menu.innerHTML = '';
      for (const opt of sel.options) {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'custom-select-option' + (opt.value === sel.value ? ' selected' : '');
        item.setAttribute('role', 'option');
        item.dataset.value = opt.value;
        item.textContent = opt.textContent;
        item.addEventListener('click', () => {
          sel.value = item.dataset.value;
          label.textContent = item.textContent;
          for (const o of menu.querySelectorAll('.custom-select-option')) o.classList.toggle('selected', o === item);
          close();
          sel.dispatchEvent(new Event('change', { bubbles: true }));
          sel.dispatchEvent(new Event('input', { bubbles: true }));
        });
        menu.append(item);
      }
    }
    function open() {
      renderOptions();
      menu.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      trigger.classList.add('open');
    }
    function close() {
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      trigger.classList.remove('open');
    }
    trigger.addEventListener('click', () => (menu.hidden ? open() : close()));
    document.addEventListener('click', (e) => {
      if (!wrap.contains(e.target)) close();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close();
    });
    sel.addEventListener('change', () => {
      label.textContent = sel.options[sel.selectedIndex]?.textContent || '';
    });

    // 组装并替换：原 select 保留为表单字段（隐藏），仅视觉替换
    const parent = sel.parentNode;
    parent.insertBefore(wrap, sel);
    wrap.append(trigger, menu, sel);
    sel.style.display = 'none';
  }
}
enhanceSelects();
