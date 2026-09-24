/* 外观：黑/白主题 + 有限强调色预设，主页面、iframe 与悬浮歌词共享选择。 */
if (window.__subforgeAppInitialized) {
  if (typeof window.SUBFORGE_CSRF !== 'undefined') {
    for (const input of document.querySelectorAll('input[name="csrf_token"]')) {
      input.value = window.SUBFORGE_CSRF || '';
    }
  }
  if (window.SubForgeApp?.initWidgets) window.SubForgeApp.initWidgets(document);
} else {
window.__subforgeAppInitialized = true;
(()=>{
  const themeKey='subforge.theme',accentKey='subforge.accent';
  const accents=new Set(['blue','cyan','green','violet','amber','rose']);
  const syncToIframe = (theme, accent) => {
    try {
      const ifr = document.getElementById('content-frame');
      if (ifr) {
        if (ifr.contentDocument?.documentElement) {
          if (theme) ifr.contentDocument.documentElement.dataset.theme = theme;
          if (accent) ifr.contentDocument.documentElement.dataset.accent = accent;
        }
        ifr.contentWindow?.postMessage({ __theme: theme, __accent: accent }, '*');
      }
    } catch (e) {}
  };
  const applyTheme=theme=>{
    const value=theme==='light'?'light':'dark';
    document.documentElement.dataset.theme=value;
    const toggle=document.querySelector('[data-theme-toggle]');
    if(toggle){
      toggle.classList.toggle('is-light',value==='light');
      const label=toggle.querySelector('[data-theme-label]');
      if(label)label.textContent=value==='light'?'黑色主题':'白色主题';
      toggle.title=value==='light'?'切换到黑色主题':'切换到白色主题';
    }
    syncToIframe(value, null);
  };
  const applyAccent=accent=>{
    const value=accents.has(accent)?accent:'blue';
    document.documentElement.dataset.accent=value;
    for(const button of document.querySelectorAll('[data-accent]')){
      const active=button.dataset.accent===value;
      button.classList.toggle('active',active);
      button.setAttribute('aria-pressed',active?'true':'false');
    }
    syncToIframe(null, value);
  };
  applyTheme(localStorage.getItem(themeKey)||'dark');
  applyAccent(localStorage.getItem(accentKey)||'blue');
  document.querySelector('[data-theme-toggle]')?.addEventListener('click',()=>{
    const next=document.documentElement.dataset.theme==='light'?'dark':'light';
    localStorage.setItem(themeKey,next);applyTheme(next);
  });
  for(const button of document.querySelectorAll('[data-accent]'))button.addEventListener('click',()=>{
    localStorage.setItem(accentKey,button.dataset.accent);applyAccent(button.dataset.accent);
  });
  window.addEventListener('storage',event=>{
    if(event.key===themeKey)applyTheme(event.newValue||'dark');
    if(event.key===accentKey)applyAccent(event.newValue||'blue');
  });
  // Top window: 监听 iframe 加载，确保内页立即获得当前主题和强调色
  const ifr = document.getElementById('content-frame');
  if (ifr) {
    ifr.addEventListener('load', () => {
      try {
        const theme = document.documentElement.dataset.theme || localStorage.getItem(themeKey) || 'dark';
        const accent = document.documentElement.dataset.accent || localStorage.getItem(accentKey) || 'blue';
        if (ifr.contentDocument?.documentElement) {
          ifr.contentDocument.documentElement.dataset.theme = theme;
          ifr.contentDocument.documentElement.dataset.accent = accent;
        }
      } catch (e) {}
    });
  }
  // Iframe 内页：启动时继承父窗口配置，并监听跨窗口主题消息
  if (window.parent && window.parent !== window) {
    try {
      const pTheme = window.parent.document.documentElement.dataset.theme;
      const pAccent = window.parent.document.documentElement.dataset.accent;
      if (pTheme) applyTheme(pTheme);
      if (pAccent) applyAccent(pAccent);
    } catch (e) {}
  }
  window.addEventListener('message', (e) => {
    if (e.data && typeof e.data === 'object') {
      if (e.data.__theme) applyTheme(e.data.__theme);
      if (e.data.__accent) applyAccent(e.data.__accent);
    }
  });
})();
/* 安全表单 CSRF 注入（使用捕获阶段委托，确保 HTMX 动态换页后的表单依然有效） */
document.addEventListener('submit', e => {
  const form = e.target.closest('form[data-secure]');
  if (!form) return;
  if (form.dataset.confirm && !confirm(form.dataset.confirm)) {
    e.preventDefault();
    return;
  }
  let input = form.querySelector('input[name=csrf_token]');
  if (!input) {
    input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'csrf_token';
    form.append(input);
  }
  input.value = window.SUBFORGE_CSRF || '';
}, true);

const originalFetch = window.fetch;
window.fetch = (input, init = {}) => {
  init.headers = new Headers(init.headers || {});
  if (init.method && init.method.toUpperCase() !== 'GET') {
    init.headers.set('X-CSRF-Token', window.SUBFORGE_CSRF || '');
  }
  return originalFetch(input, init);
};

/* 导入弹窗：点击工具栏导入按钮打开弹窗（事件委托，确保 HTMX 换页后依然响应） */
document.addEventListener('click', event => {
  const picker = event.target.closest('#pick-audio');
  if (!picker) return;
  const dialog = document.getElementById('import-dialog');
  if (!dialog) return;
  syncKindFields();
  dialog.showModal();
});

/* 导入弹窗：本地 tab 内点按钮触发文件选择并回填标题 */
document.addEventListener('click', async event => {
  const pickImportFile = event.target.closest('[data-pick-import-file]');
  if (!pickImportFile) return;
  const form = pickImportFile.closest('form') || document.querySelector('[data-local-import-form]');
  const error = form?.querySelector('[data-local-import-error]');
  if (error) error.hidden = true;
  pickImportFile.disabled = true;
  try {
    const response = await fetch('/picker/audio', { method: 'POST' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (error) {
        error.textContent = data.error || `打开文件选择器失败（HTTP ${response.status}）`;
        error.hidden = false;
      }
      return;
    }
    if (data.cancelled) return;
    const selInput = form?.querySelector('#selection-id') || document.getElementById('selection-id');
    if (selInput) selInput.value = data.selection_id;
    const nameEl = form?.querySelector('#selected-name') || document.getElementById('selected-name');
    if (nameEl) nameEl.textContent = data.filename;
    const titleInput = form?.querySelector('input[name="title"]');
    if (titleInput && !titleInput.value.trim() && data.filename) {
      titleInput.value = data.filename.replace(/\.[^/.]+$/, '');
    }
    if (error) error.hidden = true;
  } catch (err) {
    if (error) {
      error.textContent = `打开文件选择器失败：${err.message}`;
      error.hidden = false;
    }
  } finally {
    pickImportFile.disabled = false;
  }
});

/* 导入 Dialog：本地文件 / 链接下载 / RJ 文件夹，无动画切换并分别保留输入（事件委托） */
document.addEventListener('click', event => {
  const tab = event.target.closest('[data-import-tab]');
  if (!tab) return;
  const dialog = tab.closest('#import-dialog') || document.getElementById('import-dialog');
  if (!dialog) return;
  for (const other of dialog.querySelectorAll('[data-import-tab]')) {
    const active = other === tab;
    other.classList.toggle('active', active);
    other.setAttribute('aria-selected', active ? 'true' : 'false');
  }
  for (const panel of dialog.querySelectorAll('[data-import-panel]')) {
    panel.hidden = panel.dataset.importPanel !== tab.dataset.importTab;
  }
});

/* 导入弹窗：类型切换控制 RJ 号字段显隐（仅 RJ 作品有 RJ 号） */
function syncKindFields(root = document) {
  for (const sel of root.querySelectorAll('[data-kind-select]')) {
    const scope = sel.closest('[data-import-panel], [data-work-edit-form]') || sel.closest('form');
    const rjField = scope?.querySelector('[data-rj-field]');
    if (rjField) rjField.style.display = sel.value === 'rj_work' ? '' : 'none';
    const authorField = scope?.querySelector('[data-author-field]');
    if (authorField) authorField.style.display = sel.value === 'stream_archive' ? '' : 'none';
    const creatorPicker = scope?.querySelector('[data-creator-picker]');
    if (creatorPicker) {
      creatorPicker.dataset.contextKind = sel.value;
      creatorPicker.dispatchEvent(new CustomEvent('creator-context-change'));
    }
  }
}
document.addEventListener('change', event => {
  if (event.target.matches('[data-kind-select]')) syncKindFields();
});
syncKindFields();

/* URL 输入自动获取视频元数据（标题、创作者/UP主、封面） */
let urlInfoTimer = null;
let lastCheckedUrl = '';
async function checkAndFetchVideoInfo(input) {
  const url = input.value.trim();
  if (!url) {
    lastCheckedUrl = '';
    return;
  }
  if (!/^https?:\/\//i.test(url) || url === lastCheckedUrl) return;
  const form = input.closest('form');
  if (!form) return;
  lastCheckedUrl = url;
  const statusEl = form.querySelector('[data-url-status]');
  const titleInput = form.querySelector('[data-url-title]');
  const authorInput = form.querySelector('[data-url-author]');
  const picker = form.querySelector('[data-creator-picker]');
  if (statusEl) {
    statusEl.textContent = '正在获取视频信息…';
    statusEl.hidden = false;
  }
  try {
    const resp = await fetch(`/api/video-info?url=${encodeURIComponent(url)}`);
    const data = await resp.json().catch(() => ({}));
    if (data.ok) {
      if (titleInput && (!titleInput.value.trim() || titleInput.dataset.autofilled)) {
        titleInput.value = data.title || '';
        titleInput.dataset.autofilled = 'true';
      }
      if (authorInput && (!authorInput.value.trim() || authorInput.dataset.autofilled)) {
        authorInput.value = data.author || '';
        authorInput.dataset.autofilled = 'true';
      }
      if (data.author && picker) {
        const matchingOption = [...picker.querySelectorAll('[data-creator-option]')].find(
          opt => normalizeCreatorName(opt.dataset.creatorName) === normalizeCreatorName(data.author)
        );
        if (matchingOption && picker._addCreator) {
          picker._addCreator(creatorFromOption(matchingOption));
        }
      }
      if (statusEl) {
        const infoText = [data.title, data.author ? `UP主/作者: ${data.author}` : ''].filter(Boolean).join(' · ');
        statusEl.textContent = `已获取：${infoText}`;
        statusEl.hidden = false;
      }
    } else {
      if (statusEl) {
        statusEl.textContent = data.error ? `获取提示：${data.error}` : '';
        statusEl.hidden = !data.error;
      }
    }
  } catch {
    if (statusEl) statusEl.hidden = true;
  }
}

document.addEventListener('input', event => {
  const input = event.target.closest('[data-url-input]');
  if (input) {
    clearTimeout(urlInfoTimer);
    urlInfoTimer = setTimeout(() => checkAndFetchVideoInfo(input), 450);
  }
  if (event.target.matches('[data-url-title], [data-url-author]')) {
    delete event.target.dataset.autofilled;
  }
});
document.addEventListener('paste', event => {
  const input = event.target.closest('[data-url-input]');
  if (input) setTimeout(() => checkAndFetchVideoInfo(input), 50);
});
document.addEventListener('change', event => {
  const input = event.target.closest('[data-url-input]');
  if (input) checkAndFetchVideoInfo(input);
});

/* 本地导入：fetch 提交，转换期间禁用按钮并在对话框内显示错误（事件委托） */
document.addEventListener('submit', async event => {
  const localImportForm = event.target.closest('[data-local-import-form]');
  if (!localImportForm) return;
  event.preventDefault();
  const error = localImportForm.querySelector('[data-local-import-error]');
  const button = localImportForm.querySelector('[data-local-import-submit]');
  if (error) error.hidden = true;
  if (!localImportForm.elements.selection_id?.value) {
    if (error) {
      error.textContent = '请先选择音频或视频文件';
      error.hidden = false;
    }
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = '导入中…';
  }
  try {
    const formData = new FormData(localImportForm);
    formData.append('csrf_token', window.SUBFORGE_CSRF || '');
    const body = new URLSearchParams(formData).toString();
    const response = await fetch(localImportForm.action, {
      method: 'POST',
      body,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    if (response.ok) {
      window.location.replace(response.url);
      return;
    }
    const data = await response.json().catch(() => ({}));
    if (error) {
      error.textContent = data.error || `导入失败（HTTP ${response.status}）`;
      error.hidden = false;
    }
  } catch (err) {
    if (error) {
      error.textContent = `导入失败：${err.message}`;
      error.hidden = false;
    }
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = '导入';
    }
  }
});

/* 可复用创作者 Tag 输入：点击显示全部、忽略大小写/空格的前缀匹配、逗号/Enter 添加。 */
function normalizeCreatorName(value){return(value||'').toLocaleLowerCase().replace(/\s+/g,'');}
function creatorTagElement(picker,creator){const tag=document.createElement('span');tag.className=`creator-tag creator-tag-${creator.kind}`;tag.dataset.selectedId=creator.creator_id;tag.textContent=creator.name;const remove=document.createElement('button');remove.type='button';remove.dataset.removeTag='';remove.setAttribute('aria-label',`移除 ${creator.name}`);remove.textContent='×';const hidden=document.createElement('input');hidden.type='hidden';hidden.name=picker.dataset.fieldName;hidden.value=creator.creator_id;tag.append(remove,hidden);return tag}
function creatorFromOption(option){return{creator_id:option.dataset.creatorId,name:option.dataset.creatorName,kind:option.dataset.creatorKind}}
function setupCreatorPicker(picker){const input=picker.querySelector('[data-creator-search]'),suggestions=picker.querySelector('[data-creator-suggestions]'),tags=picker.querySelector('[data-selected-tags]'),create=picker.querySelector('[data-create-from-picker]'),empty=picker.querySelector('[data-suggestion-empty]');if(!input||!suggestions)return;
 if(picker.dataset.pickerInit)return;picker.dataset.pickerInit='true';
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
document.addEventListener('click',async event=>{
  const testBtn=event.target.closest('[data-test-endpoint]');
  if(testBtn){
    const output=testBtn.closest('.profile-row-actions')?.querySelector('.check-result')||testBtn.parentElement.querySelector('.check-result');
    if(!output)return;
    const label=testBtn.querySelector('span'),originalLabel=label?.textContent;
    testBtn.disabled=true;
    if(label)label.textContent='测试中';
    output.textContent='检查中…';
    try{
      const response=await fetch(testBtn.dataset.testEndpoint,{method:'POST'});
      const data=await response.json().catch(()=>({ok:false,message:`HTTP ${response.status}`}));
      output.textContent=data.ok?`✅ ${data.message}`:`❌ ${data.message||data.ok}`;
    }catch(e){
      output.textContent=`❌ ${e.message||e}`;
    }finally{
      testBtn.disabled=false;
      if(label)label.textContent=originalLabel;
    }
    return;
  }
  const dirBtn=event.target.closest('[data-pick-directory]');
  if(dirBtn){
    const field=dirBtn.dataset.field,form=dirBtn.closest('form');
    if(!form)return;
    dirBtn.disabled=true;
    try{
      const response=await fetch('/picker/directory',{method:'POST'});
      const data=await response.json().catch(()=>({}));
      if(data&&!data.cancelled){
        if(form.elements[`${field}_selection`])form.elements[`${field}_selection`].value=data.selection_id;
        if(form.elements[field])form.elements[field].value=data.name;
      }
    }finally{
      dirBtn.disabled=false;
    }
    return;
  }
  const pickCoverBtn=event.target.closest('[data-pick-cover]');
  if(pickCoverBtn){
    const form=pickCoverBtn.closest('form');
    pickCoverBtn.disabled=true;
    try{
      const response=await fetch('/picker/image',{method:'POST'});
      const data=await response.json().catch(()=>({}));
      if(data&&!data.cancelled&&form){
        if(form.elements.selection_id)form.elements.selection_id.value=data.selection_id;
        const nameEl=form.querySelector('[data-cover-name]');
        if(nameEl)nameEl.textContent=data.filename;
        pickCoverBtn.textContent='应用封面';
        pickCoverBtn.type='submit';
      }
    }finally{
      pickCoverBtn.disabled=false;
    }
    return;
  }
});
const workEditDialog=document.getElementById('work-edit-dialog');
function resetCreatorPicker(picker){
  if(!picker)return;
  setupCreatorPicker(picker);
  clearCreatorPicker(picker);
  for(const id of (picker.dataset.initialIds||'').split(',').filter(Boolean)){
    const option=picker.querySelector(`[data-creator-option][data-creator-id="${id}"]`);
    if(option&&typeof picker._addCreator==='function'){
      picker._addCreator(creatorFromOption(option));
    }
  }
}
document.addEventListener('click',event=>{
  const btn=event.target.closest('[data-open-work-edit]');
  if(!btn)return;
  const dialog=document.getElementById('work-edit-dialog');
  if(!dialog)return;
  try {
    const form=dialog.querySelector('[data-work-edit-form]');
    if(form){
      form.reset();
      const picker=form.querySelector('[data-creator-picker]');
      if(picker)resetCreatorPicker(picker);
      const preview=form.querySelector('[data-work-cover-preview]');
      if(preview){
        preview.src=preview.dataset.originalSrc;
        preview.hidden=false;
      }
      const filename=form.querySelector('[data-cover-filename]');
      if(filename)filename.textContent='当前封面';
      const err=form.querySelector('[data-work-edit-error]');
      if(err)err.hidden=true;
    }
    syncKindFields(dialog);
  }catch(err){
    console.error('Error preparing work edit dialog:',err);
  }
  try{
    if(dialog.open)dialog.close();
    dialog.showModal();
  }catch(e){
    dialog.setAttribute('open','');
  }
});
/* 封面上传与本地文件选择 */
document.addEventListener('click', event => {
  const trigger = event.target.closest('[data-trigger-cover-file]');
  if (trigger) {
    const form = trigger.closest('form');
    form?.querySelector('[data-work-cover-file]')?.click();
    return;
  }
  const dropzone = event.target.closest('[data-work-cover-dropzone]');
  if (dropzone && !event.target.closest('button')) {
    const form = dropzone.closest('form');
    form?.querySelector('[data-work-cover-file]')?.click();
    return;
  }
});

document.addEventListener('change', async event => {
  const fileInput = event.target.closest('[data-work-cover-file]');
  if (!fileInput || !fileInput.files?.length) return;
  const file = fileInput.files[0];
  const form = fileInput.closest('form');
  if (!form) return;
  const preview = form.querySelector('[data-work-cover-preview]');
  const filenameEl = form.querySelector('[data-cover-filename]');
  const errorEl = form.querySelector('[data-work-edit-error]');
  if (errorEl) errorEl.hidden = true;

  if (preview) {
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  }
  if (filenameEl) filenameEl.textContent = `上传中: ${file.name}`;

  try {
    const resp = await fetch('/api/upload-image', {
      method: 'POST',
      body: file,
      headers: {
        'Content-Type': file.type || 'image/jpeg',
        'X-Filename': encodeURIComponent(file.name),
        'X-CSRF-Token': window.SUBFORGE_CSRF || '',
      },
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.selection_id) {
      if (errorEl) {
        errorEl.textContent = data.error || `上传图片失败（HTTP ${resp.status}）`;
        errorEl.hidden = false;
      }
      return;
    }
    form.elements.selection_id.value = data.selection_id;
    if (filenameEl) filenameEl.textContent = `已选择: ${data.filename}`;
  } catch (err) {
    if (errorEl) {
      errorEl.textContent = `上传图片失败: ${err.message}`;
      errorEl.hidden = false;
    }
  } finally {
    fileInput.value = '';
  }
});

document.addEventListener('dragover', event => {
  if (event.target.closest('[data-work-cover-dropzone]')) {
    event.preventDefault();
  }
});
document.addEventListener('drop', event => {
  const dropzone = event.target.closest('[data-work-cover-dropzone]');
  if (!dropzone) return;
  event.preventDefault();
  const form = dropzone.closest('form');
  const fileInput = form?.querySelector('[data-work-cover-file]');
  if (event.dataTransfer?.files?.length && fileInput) {
    fileInput.files = event.dataTransfer.files;
    fileInput.dispatchEvent(new Event('change', { bubbles: true }));
  }
});

document.addEventListener('click', async event => {
  const btn = event.target.closest('[data-pick-work-cover]');
  if (!btn) return;
  const form = btn.closest('form');
  const error = form?.querySelector('[data-work-edit-error]');
  if (error) error.hidden = true;
  btn.disabled = true;
  try {
    const response = await fetch('/picker/image', { method: 'POST' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.cancelled) {
      if (!data.cancelled && error) {
        error.textContent = data.error || '无法打开图片选择器';
        error.hidden = false;
      }
      return;
    }
    form.elements.selection_id.value = data.selection_id;
    const preview = form.querySelector('[data-work-cover-preview]');
    if (preview) {
      preview.src = `/api/selections/${data.selection_id}/image`;
      preview.hidden = false;
    }
    if (form.querySelector('[data-cover-filename]')) {
      form.querySelector('[data-cover-filename]').textContent = data.filename;
    }
  } finally {
    btn.disabled = false;
  }
});

document.addEventListener('submit', async event => {
  const form = event.target.closest('[data-work-edit-form]');
  if (!form) return;
  event.preventDefault();
  const error = form.querySelector('[data-work-edit-error]');
  if (error) error.hidden = true;
  const saveBtn = form.querySelector('button:not(.ghost)');
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中…';
  }
  try {
    const body = new URLSearchParams(new FormData(form)).toString();
    const response = await fetch(form.action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' },
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (error) {
        error.textContent = data.error || `保存失败（HTTP ${response.status}）`;
        error.hidden = false;
      }
      return;
    }
    location.reload();
  } catch (err) {
    if (error) {
      error.textContent = `保存失败：${err.message}`;
      error.hidden = false;
    }
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = '保存';
    }
  }
});
function showTaskMessage(row,message){let output=row.querySelector('.task-center-message');if(!output&&message){output=document.createElement('p');output.className='task-center-message';row.append(output)}if(!output)return;output.textContent=message||'';clearInterval(output._countdown);const match=(message||'').match(/(\d+)秒后重试/);if(!match)return;let seconds=Number(match[1]);output._countdown=setInterval(()=>{seconds=Math.max(0,seconds-1);output.textContent=message.replace(/\d+秒后重试/,`${seconds}秒后重试`);if(seconds===0)clearInterval(output._countdown)},1000)}
function getTaskRows(){
 const rows=[...document.querySelectorAll('[data-task-id]')];
 for(const row of rows){
  if(!row._msgInit){
   row._msgInit=true;
   showTaskMessage(row,row.querySelector('.task-center-message')?.textContent||'');
  }
 }
 return rows;
}
let taskPollInFlight=false;
async function pollTaskRows(){
 if(taskPollInFlight||document.hidden)return;
 const rows=getTaskRows();
 const active=rows.filter(row=>['queued','running'].includes(row.querySelector('.task-status')?.textContent.trim()));
 if(!active.length)return;
 taskPollInFlight=true;
 try{
  const query=new URLSearchParams();for(const row of active)query.append('task_id',row.dataset.taskId);
  const response=await fetch(`/api/tasks/status?${query}`);if(!response.ok)return;
  const byId=new Map((await response.json()).map(task=>[task.task_id,task]));let reachedTerminal=false;
  for(const row of active){const task=byId.get(row.dataset.taskId);if(!task)continue;const status=row.querySelector('.task-status'),stage=row.querySelector('.task-stage'),progress=row.querySelector('.task-progress'),batches=row.querySelector('.task-batches'),sep=row.querySelector('.task-progress-sep'),fill=row.querySelector('.task-progress-fill');if(status){status.textContent=task.status;status.className='status-badge status-'+task.status+' task-status';}if(stage&&task.stage){stage.textContent=task.stage;stage.className='chip task-stage chip-stage-'+task.stage;}if(progress&&task.progress!=null)progress.textContent=Math.round(task.progress*100);if(fill&&task.progress!=null)fill.style.width=`${Math.round(task.progress*100)}%`;if(batches&&task.total!=null){batches.textContent=`${task.completed||0} / ${task.total}`;batches.hidden=false;if(sep)sep.hidden=false;}if(task.message!=null)showTaskMessage(row,task.message);if(!['queued','running'].includes(task.status))reachedTerminal=true}
  if(reachedTerminal&&!document.querySelector('dialog[open]'))location.reload();
 }catch(_error){}finally{taskPollInFlight=false}
}
let taskPollTimer = null;
function taskPollDelay(){const rows=getTaskRows();const fastStage=rows.some(row=>{const status=row.querySelector('.task-status')?.textContent.trim(),stage=row.querySelector('.task-stage')?.textContent.trim();return['queued','running'].includes(status)&&['model','asr'].includes(stage)});return fastStage?250:1000}
async function scheduleTaskPoll(){if(taskPollTimer)clearTimeout(taskPollTimer);await pollTaskRows();taskPollTimer=setTimeout(scheduleTaskPoll,taskPollDelay())}
scheduleTaskPoll();document.addEventListener('visibilitychange',pollTaskRows);
/* 片段重处理候选评审：从任务中心打开候选对比并接受/放弃 */
let reviewTaskId='';
function fmtCandidateTime(t){if(t==null||!isFinite(t))return'--:--';const s=Math.max(0,Math.floor(t)),m=Math.floor(s/60),sec=s%60,p=n=>String(n).padStart(2,'0');return`${m}:${p(sec)}`}
function renderCandidateEntries(entries){return(entries||[]).map(e=>`${fmtCandidateTime(e.start)}–${fmtCandidateTime(e.end)}  ${e.text}`).join('\n\n')}
document.addEventListener('click',async(event)=>{
 const button=event.target.closest('[data-review-task]');
 if(!button)return;
 const segmentCandidateDialog=document.getElementById('segment-candidate-dialog');
 if(!segmentCandidateDialog)return;
 const taskId=button.dataset.reviewTask,error=segmentCandidateDialog.querySelector('[data-candidate-error]');
 const response=await fetch(`/tasks/${taskId}/candidate`);const data=await response.json().catch(()=>({}));
 if(!response.ok){error.textContent=data.error||`候选读取失败（HTTP ${response.status}）`;error.hidden=false;segmentCandidateDialog.showModal();return;}
 reviewTaskId=taskId;
 segmentCandidateDialog.querySelector('[data-current-source]').textContent=renderCandidateEntries(data.current.source);
 segmentCandidateDialog.querySelector('[data-current-target]').textContent=renderCandidateEntries(data.current.target);
 segmentCandidateDialog.querySelector('[data-candidate-source]').textContent=renderCandidateEntries(data.candidate.source);
 segmentCandidateDialog.querySelector('[data-candidate-target]').textContent=renderCandidateEntries(data.candidate.target);
 const warnings=segmentCandidateDialog.querySelector('[data-candidate-warnings]');warnings.textContent=(data.warnings||[]).join('；');warnings.hidden=!warnings.textContent;
 error.hidden=true;segmentCandidateDialog.showModal();
});
document.addEventListener('click',(event)=>{
 if(event.target.closest('[data-close-segment-candidate]')){
  reviewTaskId='';document.getElementById('segment-candidate-dialog')?.close();
 }
});
document.addEventListener('click',async(event)=>{
 if(!event.target.closest('[data-confirm-segment-candidate]'))return;
 const segmentCandidateDialog=document.getElementById('segment-candidate-dialog');
 if(!reviewTaskId)return;const error=segmentCandidateDialog.querySelector('[data-candidate-error]');error.hidden=true;
 const response=await fetch(`/tasks/${reviewTaskId}/candidate/confirm`,{method:'POST'});const data=await response.json().catch(()=>({}));
 if(!response.ok){error.textContent=data.error||`替换失败（HTTP ${response.status}）`;error.hidden=false;return;}
 reviewTaskId='';segmentCandidateDialog.close();location.reload();
});
document.addEventListener('click',async(event)=>{
 const button=event.target.closest('[data-discard-task]');
 if(!button)return;
 if(!window.confirm('放弃这个候选？正式字幕不会改变。'))return;
 const response=await fetch(`/tasks/${button.dataset.discardTask}/candidate/discard`,{method:'POST'});
 if(response.ok)location.reload();
});
/* 通用 Tab 切换：更新 URL 参数与面板可见性 */
function updateTabUrl(name){
 try{
  const url=new URL(window.location.href);
  if(url.searchParams.get('tab')!==name){
   url.searchParams.set('tab',name);
   url.searchParams.delete('page');
   window.history.replaceState(null,'',url.toString());
  }
 }catch(_){}
}
window.updateTabUrl=updateTabUrl;
function initTabs(root=document){
 const urlTab=(new URLSearchParams(window.location.search)).get('tab');
 for(const bar of root.querySelectorAll('.tab-bar')){
  const activeTab=bar.querySelector('.tab.active');
  const targetName=urlTab||(activeTab?activeTab.dataset.tab:null)||'subtitles';
  const targetTab=bar.querySelector(`[data-tab="${targetName}"]`)||bar.querySelector('.tab');
  if(targetTab){
   for(const t of bar.querySelectorAll('.tab')){
    t.classList.toggle('active',t===targetTab);
    t.setAttribute('aria-selected',t===targetTab?'true':'false');
   }
   const scope=bar.parentElement||document;
   for(const panel of scope.querySelectorAll('[data-tab-panel]')){
    panel.classList.toggle('active',panel.dataset.tabPanel===targetTab.dataset.tab);
   }
  }
 }
}
window.initTabs=initTabs;
initTabs(document);
document.addEventListener('click',(event)=>{
 const tab=event.target.closest('.tab-bar .tab');
 if(!tab)return;
 const name=tab.dataset.tab;
 if(!name)return;
 const bar=tab.closest('.tab-bar');
 for(const t of bar.querySelectorAll('.tab')){
  t.classList.toggle('active',t===tab);
  t.setAttribute('aria-selected',t===tab?'true':'false');
 }
 const scope=bar.parentElement||document;
 for(const panel of scope.querySelectorAll('[data-tab-panel]')){
  panel.classList.toggle('active',panel.dataset.tabPanel===name);
 }
 updateTabUrl(name);
});
/* 配置弹窗：新增/复制/编辑共用一个 dialog，浏览器端始终不接触已有 Key。 */
document.addEventListener('click', event => {
  const button = event.target.closest('[data-open-dialog]');
  if (!button) return;
  const dialog = document.getElementById(button.dataset.openDialog);
  if (!dialog) return;
  const form = dialog.querySelector('form'), title = dialog.querySelector('[data-dialog-title]'), submit = dialog.querySelector('[data-dialog-submit]');
  if (!form) return;
  form.reset();
  form.elements.profile_id.value = '';
  form.elements.copy_from_profile_id.value = '';
  if (form.elements.api_key) form.elements.api_key.placeholder = '可选';
  const raw = button.dataset.copyProfile || button.dataset.editProfile;
  if (raw) {
    const p = JSON.parse(raw);
    if (form.elements.name) form.elements.name.value = p.name || '';
    if (form.elements.base_url) form.elements.base_url.value = p.base_url || '';
    if (form.elements.model) form.elements.model.value = p.model || '';
    if (form.elements.protocol) form.elements.protocol.value = p.protocol || 'openai_compatible';
    if (form.elements.max_request_seconds) form.elements.max_request_seconds.value = p.max_request_seconds ?? 60;
    if (form.elements.temperature) form.elements.temperature.value = p.temperature ?? 0;
    if (form.elements.transcribe_prompt) form.elements.transcribe_prompt.value = p.transcribe_prompt || '';
    if (form.elements.bilingual_prompt) form.elements.bilingual_prompt.value = p.bilingual_prompt || '';
    if (form.elements.translate_prompt) form.elements.translate_prompt.value = p.translate_prompt || '';
    if (form.elements.merge_prompt) form.elements.merge_prompt.value = p.merge_prompt || '';
    for (const cap of ['transcribe', 'translate', 'merge']) {
      const box = form.elements[`cap_${cap}`];
      if (box) box.checked = (p.capabilities || []).includes(cap);
    }
    if (form.elements.api_key) form.elements.api_key.value = '';
    if (form.elements.proxy_url) form.elements.proxy_url.value = p.proxy_url || '';
    if (form.elements.ca_bundle) form.elements.ca_bundle.value = p.ca_bundle || '';
    if (form.elements.verify_tls) form.elements.verify_tls.checked = p.verify_tls !== false;
    if (button.dataset.copyProfile) {
      form.elements.copy_from_profile_id.value = p.profile_id || '';
      form.elements.name.value = `${p.name || '未命名配置'} 副本`;
      if (form.elements.api_key) form.elements.api_key.placeholder = '留空复制原配置凭据';
      if (title) title.textContent = '复制配置';
      if (submit) submit.textContent = '创建副本';
    } else {
      form.elements.profile_id.value = p.profile_id || '';
      if (form.elements.api_key) form.elements.api_key.placeholder = '留空保持不变';
      if (title) title.textContent = '编辑配置';
      if (submit) submit.textContent = '保存';
    }
  } else {
    if (title) title.textContent = '新增配置';
    if (submit) submit.textContent = '创建配置';
  }
  dialog.showModal();
  form.elements.name?.focus();
  if (button.dataset.copyProfile) form.elements.name?.select();
});
document.addEventListener('click', event => {
  const button = event.target.closest('[data-close-dialog]');
  if (button) button.closest('dialog')?.close();
});

/* 创作者管理：分组搜索、行菜单，以及添加/修改/合并/删除 Dialog。 */
document.addEventListener('input',event=>{
  const search=event.target.closest('[data-creator-list-search]');
  if(!search)return;
  const q=normalizeCreatorName(search.value);
  const panel=search.closest('[data-tab-panel]');
  if(!panel)return;
  for(const row of panel.querySelectorAll('[data-creator-row]'))row.hidden=!normalizeCreatorName(row.dataset.creatorName).startsWith(q);
});
document.addEventListener('click',event=>{
  const menuBtn=event.target.closest('[data-creator-menu-button]');
  if(menuBtn){
    event.stopPropagation();
    const menu=menuBtn.parentElement.querySelector('[data-creator-menu]');
    for(const other of document.querySelectorAll('[data-creator-menu]'))if(other!==menu)other.hidden=true;
    if(menu)menu.hidden=!menu.hidden;
    return;
  }
  for(const menu of document.querySelectorAll('[data-creator-menu]'))menu.hidden=true;
});
document.addEventListener('click', event => {
  const openCreator = event.target.closest('[data-open-creator-create]');
  if (!openCreator) return;
  const manageCreate = document.getElementById('creator-manage-create');
  if (!manageCreate) return;
  const active = document.querySelector('.creator-tabs .tab.active')?.dataset.tab || 'circle';
  const kindInput = manageCreate.querySelector(`input[name="kind"][value="${active}"]`);
  if (kindInput) kindInput.checked = true;
  manageCreate.showModal();
  manageCreate.querySelector('input[name="name"]')?.focus();
});
function clearCreatorPicker(picker){for(const tag of picker.querySelectorAll('[data-selected-id]'))tag.remove();const input=picker.querySelector('[data-creator-search]');if(input)input.value='';picker._refreshCreators?.(false)}
function openMergeDialog(data){const dialog=document.getElementById('creator-merge-dialog'),form=dialog.querySelector('form'),picker=dialog.querySelector('[data-creator-picker]');form.elements.source_id.value=data.id;dialog.querySelector('[data-merge-source-name]').innerHTML=`<span class="creator-tag creator-tag-${data.kind}">${data.name}</span>`;dialog.querySelector('[data-merge-source-count]').textContent=`关联 ${data.count} 部作品`;clearCreatorPicker(picker);picker.dataset.allowedKind=data.kind;picker.dataset.excludeId=data.id;picker.dispatchEvent(new CustomEvent('creator-context-change'));dialog.showModal();picker.querySelector('[data-creator-search]').focus()}
document.addEventListener('click',async event=>{
  const editBtn=event.target.closest('[data-edit-creator]');
  if(editBtn){
    const dialog=document.getElementById('creator-edit-dialog'),form=dialog?.querySelector('form');
    if(dialog&&form){
      form.elements.creator_id.value=editBtn.dataset.id;
      form.elements.name.value=editBtn.dataset.name;
      const kindEl=dialog.querySelector('[data-edit-kind]');
      if(kindEl)kindEl.innerHTML=`<span class="creator-tag creator-tag-${editBtn.dataset.kind}">${editBtn.dataset.kind==='circle'?'社团':'声优'}</span>`;
      dialog.showModal();
      form.elements.name.focus();
    }
    return;
  }
  const mergeBtn=event.target.closest('[data-merge-creator]');
  if(mergeBtn){
    openMergeDialog(mergeBtn.dataset);
    return;
  }
  const delBtn=event.target.closest('[data-delete-creator]');
  if(delBtn){
    const dialog=document.getElementById('creator-delete-dialog'),form=dialog?.querySelector('form'),count=Number(delBtn.dataset.count);
    if(dialog&&form){
      form.elements.creator_id.value=delBtn.dataset.id;
      dialog.dataset.sourceId=delBtn.dataset.id;
      dialog.dataset.sourceName=delBtn.dataset.name;
      dialog.dataset.sourceKind=delBtn.dataset.kind;
      dialog.dataset.sourceCount=delBtn.dataset.count;
      const titleEl=dialog.querySelector('[data-delete-title]');
      if(titleEl)titleEl.textContent=count?'无法删除创作者':'删除创作者';
      const msgEl=dialog.querySelector('[data-delete-message]');
      if(msgEl)msgEl.textContent=count?`“${delBtn.dataset.name}”仍关联 ${count} 部作品，请先合并到同身份创作者。`:`确定删除“${delBtn.dataset.name}”吗？`;
      const confirmBtn=dialog.querySelector('[data-confirm-delete]');
      if(confirmBtn)confirmBtn.hidden=count>0;
      const mergeActionBtn=dialog.querySelector('[data-delete-to-merge]');
      if(mergeActionBtn)mergeActionBtn.hidden=count===0;
      dialog.showModal();
    }
    return;
  }
  const toMerge=event.target.closest('[data-delete-to-merge]');
  if(toMerge){
    const dialog=toMerge.closest('dialog');
    dialog?.close();
    openMergeDialog({
      id:dialog.dataset.sourceId,
      name:dialog.dataset.sourceName,
      kind:dialog.dataset.sourceKind,
      count:dialog.dataset.sourceCount,
    });
    return;
  }
  const twoStepBtn=event.target.closest('[data-two-step]');
  if(twoStepBtn){
    if(!twoStepBtn._armed){
      event.preventDefault();
      twoStepBtn._armed=true;
      twoStepBtn.dataset.originalText=twoStepBtn.textContent;
      twoStepBtn.textContent='确认删除？';
      twoStepBtn.classList.add('armed');
      clearTimeout(twoStepBtn._timer);
      twoStepBtn._timer=setTimeout(()=>{
        twoStepBtn._armed=false;
        twoStepBtn.textContent=twoStepBtn.dataset.originalText;
        twoStepBtn.classList.remove('armed');
      },3000);
    }else{
      clearTimeout(twoStepBtn._timer);
      twoStepBtn._armed=false;
    }
    return;
  }
  const deepgramBtn=event.target.closest('[data-delete-deepgram]');
  if(deepgramBtn){
    if(!deepgramBtn._armed){
      deepgramBtn._armed=true;
      deepgramBtn.textContent='确认';
      deepgramBtn.classList.add('armed');
      clearTimeout(deepgramBtn._timer);
      deepgramBtn._timer=setTimeout(()=>{
        deepgramBtn._armed=false;
        deepgramBtn.textContent='×';
        deepgramBtn.classList.remove('armed');
      },3000);
      return;
    }
    clearTimeout(deepgramBtn._timer);
    const response=await fetch('/settings/deepgram/delete-key',{method:'POST'});
    if(!response.ok){
      deepgramBtn._armed=false;
      deepgramBtn.textContent='×';
      deepgramBtn.classList.remove('armed');
      return;
    }
    const status=document.querySelector('[data-deepgram-status]');
    if(status){
      status.textContent='未配置';
      status.classList.remove('ok');
    }
    deepgramBtn.remove();
    return;
  }
});

/* 作品库搜索：服务端跨分页检索，输入停顿后刷新并回到第一页。 */
const workSearch = document.getElementById('work-search');
if (workSearch) {
  let searchTimer = null;
  let composing = false;
  let inFlightAbort = null;
  const applyWorkSearch = async () => {
    clearTimeout(searchTimer);
    const url = new URL(window.location.href);
    const query = workSearch.value.trim();
    if (query) url.searchParams.set('q', query); else url.searchParams.delete('q');
    url.searchParams.delete('page');
    const pageSizeSel = document.querySelector('[data-page-size-select]');
    if (pageSizeSel) url.searchParams.set('limit', pageSizeSel.value);
    const target = `${url.pathname}${url.search}`;
    if (target === `${window.location.pathname}${window.location.search}`) return;
    if (inFlightAbort) inFlightAbort.abort();
    inFlightAbort = new AbortController();
    window.history.replaceState(null, '', target);
    try {
      const res = await fetch(target, { headers: { 'sec-fetch-dest': 'iframe' }, signal: inFlightAbort.signal });
      if (!res.ok) { window.location.assign(target); return; }
      const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
      const newGrid = doc.querySelector('.works-grid');
      const curGrid = document.querySelector('.works-grid');
      if (newGrid && curGrid) curGrid.replaceWith(newGrid);
      const newPagination = doc.querySelector('.library-pagination');
      const curPagination = document.querySelector('.library-pagination');
      if (newPagination && curPagination) curPagination.replaceWith(newPagination);
      else if (newPagination && !curPagination) { const g = document.querySelector('.works-grid'); if (g) g.after(newPagination); }
      else if (!newPagination && curPagination) curPagination.remove();
    } catch (e) {
      if (e.name !== 'AbortError') window.location.assign(target);
    }
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
function setProcessingFieldVisible(field, visible){if(!field)return;field.hidden=!visible;for(const control of field.querySelectorAll('input,select,textarea'))control.disabled=!visible;}
function syncAsrFields(){const form=document.querySelector('[data-processing-form]');if(!form)return;const provider=form.elements.asr_provider?.value;setProcessingFieldVisible(form.querySelector('[data-asr-profile-field]'),provider==='model');setProcessingFieldVisible(form.querySelector('[data-whisper-field]'),provider==='local');setProcessingFieldVisible(form.querySelector('[data-local-asr-field]'),provider==='local');setProcessingFieldVisible(form.querySelector('[data-network-asr-field]'),provider==='deepgram'||provider==='model');setProcessingFieldVisible(form.querySelector('[data-merge-profile-field]'),provider==='model');}
document.addEventListener('change',event=>{if(event.target.name==='asr_provider'&&event.target.closest('[data-processing-form]'))syncAsrFields();});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-open-processing]');
  if(!button)return;
  const processingDialog=document.getElementById('processing-dialog');
  if(!processingDialog)return;
  const form=processingDialog.querySelector('[data-processing-form]');
  if(form){
    form.action=button.dataset.action;
    if(form.elements.scope)form.elements.scope.value=button.dataset.scope||'incomplete';
    if(form.elements.mode){form.elements.mode.value=button.dataset.mode||'continue';form.elements.mode.dispatchEvent(new Event('change',{bubbles:true}));}
    setProcessingFieldVisible(form.querySelector('[data-scope-field]'),Boolean(button.dataset.action&&button.dataset.action.includes('/items/')));
  }
  const title=processingDialog.querySelector('[data-processing-title]');
  if(title)title.textContent=button.dataset.title||'自定义处理';
  syncAsrFields();
  button.closest('details')?.removeAttribute('open');
  processingDialog.showModal();
});
syncAsrFields();
document.addEventListener('submit',event=>{
  const processingForm=event.target.closest('[data-processing-form]');
  if(!processingForm)return;
  if(processingForm.elements.mode.value!=='from_scratch')return;
  if(!window.confirm('从头进行 ASR 与翻译会覆盖现有源字幕、翻译字幕，并清除断点记录（原字幕会保留备份）。是否继续？'))event.preventDefault();
});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-open-track-rename]');
  if(!button)return;
  const trackRenameDialog=document.getElementById('track-rename-dialog');
  if(!trackRenameDialog)return;
  const form=trackRenameDialog.querySelector('[data-track-rename-form]');
  if(form){form.action=button.dataset.action;form.elements.filename.value=button.dataset.filename||'';}
  button.closest('details')?.removeAttribute('open');
  trackRenameDialog.showModal();
  form?.elements.filename.focus();
  form?.elements.filename.select();
});
function formatTrackDuration(value){if(!Number.isFinite(value))return'--:--';const total=Math.max(0,Math.round(value)),hours=Math.floor(total/3600),minutes=Math.floor(total%3600/60),seconds=total%60;return hours?`${hours}:${String(minutes).padStart(2,'0')}:${String(seconds).padStart(2,'0')}`:`${minutes}:${String(seconds).padStart(2,'0')}`}
function initTrackDurations(root=document){
  for(const output of root.querySelectorAll('[data-track-duration]')){if(output.textContent.trim()!=='--:--')continue;const audio=new Audio();audio.preload='metadata';audio.addEventListener('loadedmetadata',()=>{output.textContent=formatTrackDuration(audio.duration);audio.src=''});audio.addEventListener('error',()=>{output.textContent='--:--'});audio.src=output.dataset.trackDuration;}
}
initTrackDurations(document);
/* 同一时间只展开一个音轨操作菜单。 */
document.addEventListener('toggle',event=>{const menu=event.target.closest('.track-menu');if(!menu||!menu.open)return;for(const other of document.querySelectorAll('.track-menu[open]'))if(other!==menu)other.removeAttribute('open')},true);
/* 点击音轨行主体 → 打开播放器详情页；行内按钮/菜单不触发导航。 */
document.addEventListener('click',event=>{
  const row=event.target.closest('.track-row[data-track-player]');
  if(!row)return;
  if(event.target.closest('a,button,form,details,.track-menu,input,select,textarea,[data-task-id]'))return;
  event.stopPropagation();
  if(row.dataset.trackPlayer) {
    if (window.htmx) {
      window.htmx.ajax('GET', row.dataset.trackPlayer, { target: '#main-content', select: '#main-content', swap: 'outerHTML', pushUrl: true });
    } else {
      window.location.href=row.dataset.trackPlayer;
    }
  }
});
document.addEventListener('keydown',event=>{
  if(event.key!=='Enter'&&event.key!==' ')return;
  const row=event.target.closest('.track-row[data-track-player]');
  if(!row)return;
  const active=document.activeElement;
  if(active&&active!==row&&row.contains(active))return;
  if(!row.dataset.trackPlayer)return;
  event.preventDefault();
  if (window.htmx) {
    window.htmx.ajax('GET', row.dataset.trackPlayer, { target: '#main-content', select: '#main-content', swap: 'outerHTML', pushUrl: true });
  } else {
    window.location.href=row.dataset.trackPlayer;
  }
});

/* 就地播放：点击 data-play-track 时在底部条中开始播放（不跳转页面）。
 * 按钮在内容页（iframe 内），播放条在顶层——驱动 window.top 的全局播放器。 */
document.addEventListener('click',event=>{
  const btn=event.target.closest('[data-play-track]');
  if(!btn)return;
  event.stopPropagation();
  const url=btn.dataset.playTrack||'';
  const trackId=btn.dataset.trackId||url.split('/').filter(Boolean).slice(-2)[0];
  if(!trackId)return;
  const row=btn.closest('.track-row');
  const title=btn.dataset.trackTitle||row?.querySelector('h2')?.textContent||'播放中';
  const itemId=btn.dataset.itemId||row?.dataset.itemId||'';
  const player=window.top.SubForgePlayer||window.SubForgePlayer;
  if(!player)return;
  player.setTrack(trackId,title,itemId);
  player.play(); // 切换音轨后直接播放（此刻有用户手势，自动播放放行）
  const topBar=window.top.document?.getElementById('player-bar')||document.getElementById('player-bar');
  if(topBar)topBar.hidden=false;
});
function initWidgets(root = document) {
  initTrackDurations(root);
  if (typeof enhanceSelects === 'function') enhanceSelects(root);
  for (const picker of root.querySelectorAll('[data-creator-picker]')) setupCreatorPicker(picker);
  syncKindFields(root);
}
window.SubForgeApp = window.SubForgeApp || {};
window.SubForgeApp.initWidgets = initWidgets;

/* RJ 文件夹导入：选择文件夹（事件委托） */
document.addEventListener('click', async event => {
  const pickFolderBtn = event.target.closest('[data-pick-media-folder]');
  if (!pickFolderBtn) return;
  const form = pickFolderBtn.closest('form') || document.querySelector('[data-folder-import-form]');
  const error = form?.querySelector('[data-folder-error]');
  if (error) error.hidden = true;
  pickFolderBtn.disabled = true;
  try {
    const response = await fetch('/picker/media-folder', { method: 'POST' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.cancelled) {
      if (!data.cancelled && error) {
        error.textContent = data.error || '无法打开文件夹选择器';
        error.hidden = false;
      }
      return;
    }
    if (form) {
      form.elements.selection_id.value = data.selection_id;
      const folderName = form.querySelector('[data-folder-name]');
      if (folderName) folderName.textContent = data.name;
      const rjMatch = (data.name || '').match(/RJ\d{6,8}/i);
      if (rjMatch) {
        const rjInput = form.querySelector('input[name="rj_code"]');
        if (rjInput && !rjInput.value.trim()) {
          rjInput.value = rjMatch[0].toUpperCase();
        }
      }
    }
  } catch (err) {
    if (error) {
      error.textContent = `选择文件夹失败：${err.message}`;
      error.hidden = false;
    }
  } finally {
    pickFolderBtn.disabled = false;
  }
});

/* RJ 文件夹导入：扫描并预览（事件委托） */
document.addEventListener('click', async event => {
  const previewBtn = event.target.closest('[data-preview-folder-import]');
  if (!previewBtn) return;
  const form = previewBtn.closest('form') || document.querySelector('[data-folder-import-form]');
  const folderPreviewDialog = document.getElementById('folder-import-preview');
  if (!form || !folderPreviewDialog) return;
  const error = form.querySelector('[data-folder-error]');
  if (error) error.hidden = true;
  if (!form.elements.selection_id?.value) {
    if (error) {
      error.textContent = '请先选择 RJ 文件夹';
      error.hidden = false;
    }
    return;
  }
  if (!form.elements.rj_code?.value.trim()) {
    if (error) {
      error.textContent = '请填写 RJ 号';
      error.hidden = false;
    }
    return;
  }
  previewBtn.disabled = true;
  try {
    const body = new URLSearchParams({ selection_id: form.elements.selection_id.value }).toString();
    const response = await fetch('/api/import-folders/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (error) {
        error.textContent = data.error || '扫描文件夹失败';
        error.hidden = false;
      }
      return;
    }
    folderPreviewDialog.querySelector('[data-preview-audio]').textContent = data.audio_count;
    folderPreviewDialog.querySelector('[data-preview-video]').textContent = data.video_count;
    folderPreviewDialog.querySelector('[data-preview-skipped]').textContent = data.skipped_count;
    folderPreviewDialog.querySelector('[data-preview-folder]').textContent = `${data.folder} · 共 ${data.media_count} 个媒体文件`;
    const list = folderPreviewDialog.querySelector('[data-preview-files]');
    list.replaceChildren(...data.files.map(name => {
      const li = document.createElement('li');
      li.textContent = name;
      return li;
    }));
    folderPreviewDialog.showModal();
  } catch (err) {
    if (error) {
      error.textContent = `扫描文件夹失败：${err.message}`;
      error.hidden = false;
    }
  } finally {
    previewBtn.disabled = false;
  }
});

/* RJ 文件夹导入：确认开始导入（事件委托） */
document.addEventListener('click', async event => {
  const confirmBtn = event.target.closest('[data-confirm-folder-import]');
  if (!confirmBtn) return;
  const form = document.querySelector('[data-folder-import-form]');
  const folderPreviewDialog = document.getElementById('folder-import-preview');
  if (!form) return;
  confirmBtn.disabled = true;
  confirmBtn.textContent = '开始中…';
  try {
    const formData = new FormData(form);
    formData.append('csrf_token', window.SUBFORGE_CSRF || '');
    const body = new URLSearchParams(formData).toString();
    const response = await fetch(form.action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = '开始导入';
      folderPreviewDialog?.close();
      const error = form.querySelector('[data-folder-error]');
      if (error) {
        error.textContent = data.error || '无法开始文件夹导入';
        error.hidden = false;
      }
      return;
    }
    folderPreviewDialog?.close();
    document.getElementById('import-dialog')?.close();
    window.location.href = '/downloads';
  } catch (err) {
    confirmBtn.disabled = false;
    confirmBtn.textContent = '开始导入';
    folderPreviewDialog?.close();
    const error = form.querySelector('[data-folder-error]');
    if (error) {
      error.textContent = `启动导入失败：${err.message}`;
      error.hidden = false;
    }
  }
});

/* URL 下载导入：fetch 提交，错误在对话框内友好显示（事件委托） */
document.addEventListener('submit', async event => {
  const urlImportForm = event.target.closest('[data-import-url-form]');
  if (!urlImportForm) return;
  event.preventDefault();
  const errEl = urlImportForm.querySelector('[data-import-error]');
  const btn = urlImportForm.querySelector('[data-import-submit]');
  if (errEl) errEl.hidden = true;
  const formData = new FormData(urlImportForm);
  formData.append('csrf_token', window.SUBFORGE_CSRF || '');
  const body = new URLSearchParams(formData).toString();
  if (btn) {
    btn.disabled = true;
    btn.textContent = '准备下载…';
  }
  try {
    const resp = await fetch(urlImportForm.action, {
      method: 'POST',
      body,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 202 && data.task_id) {
      if (btn) btn.textContent = '下载中…';
      let pollCount = 0;
      for (;;) {
        await new Promise(r => setTimeout(r, 1200));
        pollCount++;
        const st = await fetch(`/api/imports/${data.task_id}`).then(r => r.json()).catch(() => null);
        if (!st) continue;
        if (st.status === 'done' && st.item_id) {
          window.location.href = `/items/${st.item_id}`;
          return;
        }
        if (st.status === 'error') {
          if (errEl) {
            errEl.textContent = st.message || '下载失败';
            errEl.hidden = false;
          }
          break;
        }
        if (btn) btn.textContent = st.message || '下载中…';
        if (pollCount >= 5) {
          document.getElementById('import-dialog')?.close();
          window.location.href = '/downloads?tab=downloads';
          return;
        }
      }
    } else if (!resp.ok || data.error) {
      if (errEl) {
        errEl.textContent = data.error || `下载失败（HTTP ${resp.status}），请稍后重试`;
        errEl.hidden = false;
      }
    }
  } catch (err) {
    if (errEl) {
      errEl.textContent = `下载失败：${err.message}`;
      errEl.hidden = false;
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '下载并导入';
    }
  }
});

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
/* 原生音频模型配置：公开字段回填，API Key 永不回填到浏览器。 */
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-edit-gemini-profile]');
  if(!button)return;
  const form=document.getElementById('gemini-profile-form');if(!form)return;
  try{
    const profile=JSON.parse(button.dataset.editGeminiProfile);
    for(const name of ['profile_id','name','protocol','base_url','model','max_segment_seconds','temperature','bilingual_prompt','transcribe_prompt','proxy_url','ca_bundle']){
      if(!form.elements[name])continue;
      const source=name==='max_segment_seconds'?'max_request_seconds':name;
      form.elements[name].value=profile[source]??'';
    }
    form.elements.api_key.value='';form.elements.verify_tls.checked=!!profile.verify_tls;
    form.scrollIntoView({behavior:'smooth',block:'start'});form.elements.name.focus();
  }catch(e){
    console.error(e);
  }
});

/* 作品库：底部分页条支持动态配置每页条数（默认10条，可选12/14/20） */
document.addEventListener('change', (e) => {
  const select = e.target.closest('[data-page-size-select]');
  if (!select) return;
  const newLimit = select.value;
  const url = new URL(window.location.href);
  url.searchParams.set('limit', newLimit);
  url.searchParams.delete('page');
  const target = `${url.pathname}${url.search}`;
  if (window.htmx) {
    htmx.ajax('GET', target, { target: '#main-content', select: '#main-content', pushUrl: true });
  } else {
    window.location.assign(target);
  }
});
/* window.__subforgeAppInitialized block end */
}
