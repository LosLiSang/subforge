for(const form of document.querySelectorAll('form[data-secure]')){form.addEventListener('submit',e=>{if(form.dataset.confirm&&!confirm(form.dataset.confirm)){e.preventDefault();return}let input=form.querySelector('input[name=csrf_token]');if(!input){input=document.createElement('input');input.type='hidden';input.name='csrf_token';form.append(input)}input.value=window.SUBFORGE_CSRF||'';});}
const originalFetch=window.fetch;window.fetch=(input,init={})=>{init.headers=new Headers(init.headers||{});if(init.method&&init.method.toUpperCase()!=='GET'){init.headers.set('X-CSRF-Token',window.SUBFORGE_CSRF||'');}return originalFetch(input,init)};
const picker=document.getElementById('pick-audio');if(picker)picker.addEventListener('click',async()=>{const dialog=document.getElementById('import-dialog');if(!dialog)return;dialog.showModal();});
/* 导入弹窗：本地 tab 内点按钮才触发文件选择 */
const pickImportFile=document.querySelector('[data-pick-import-file]');if(pickImportFile)pickImportFile.addEventListener('click',async()=>{const response=await fetch('/picker/audio',{method:'POST'});if(!response.ok)return;const data=await response.json();if(data.cancelled)return;document.getElementById('selection-id').value=data.selection_id;document.getElementById('selected-name').textContent=data.filename;});
/* 导入弹窗：本地/链接 下拉切换 */
const importSelect=document.querySelector('[data-import-select]');if(importSelect)importSelect.addEventListener('change',()=>{const name=importSelect.value;for(const p of document.querySelectorAll('[data-import-panel]'))p.hidden=p.dataset.importPanel!==name;syncKindFields();});
/* 导入弹窗：类型切换控制 RJ 号字段显隐（仅 RJ 作品有 RJ 号） */
function syncKindFields(){for(const sel of document.querySelectorAll('[data-kind-select]')){const panel=sel.closest('[data-import-panel]');const rjField=panel?.querySelector('[data-rj-field]');if(rjField)rjField.style.display=sel.value==='rj_work'?'':'none';}}
for(const sel of document.querySelectorAll('[data-kind-select]')){sel.addEventListener('change',syncKindFields);}syncKindFields();
for(const button of document.querySelectorAll('[data-test-endpoint]'))button.addEventListener('click',async()=>{const output=button.parentElement.querySelector('.check-result');if(!output)return;output.textContent='检查中…';try{const response=await fetch(button.dataset.testEndpoint,{method:'POST'});const data=await response.json().catch(()=>({ok:false,message:`HTTP ${response.status}`}));output.textContent=data.ok?`✅ ${data.message}`:`❌ ${data.message||data.ok}`;}catch(e){output.textContent=`❌ ${e.message||e}`;}});
for(const button of document.querySelectorAll('[data-pick-directory]'))button.addEventListener('click',async()=>{const response=await fetch('/picker/directory',{method:'POST'});if(!response.ok)return;const data=await response.json();if(data.cancelled)return;const field=button.dataset.field,form=button.closest('form');form.elements[`${field}_selection`].value=data.selection_id;form.elements[field].value=data.name;});
for(const row of document.querySelectorAll('[data-task-id]')){const source=new EventSource(`/tasks/${row.dataset.taskId}/events`);source.onmessage=event=>{const data=JSON.parse(event.data);if(data.stage)row.querySelector('.task-stage').textContent=data.stage;if(data.progress!=null)row.querySelector('.task-progress').textContent=Math.round(data.progress*100);if(data.total!=null)row.querySelector('.task-batches').textContent=`（${data.completed||0}/${data.total} 批次）`;if(data.type==='task_completed'){row.querySelector('.task-status').textContent='completed';source.close();location.reload()}if(data.type==='task_failed'||data.type==='task_cancelled'){row.querySelector('.task-status').textContent=data.type.replace('task_','');source.close()}};}
/* 设置页 Tab 切换：同屏只显示一个分区，表单仍是一个整体（保存语义不变） */
for(const tab of document.querySelectorAll('.tab-bar .tab')){tab.addEventListener('click',()=>{const name=tab.dataset.tab;for(const t of document.querySelectorAll('.tab-bar .tab')){t.classList.toggle('active',t===tab);t.setAttribute('aria-selected',t===tab?'true':'false')}for(const panel of document.querySelectorAll('[data-tab-panel]'))panel.classList.toggle('active',panel.dataset.tabPanel===name);});}
/* 配置弹窗：新增/编辑共用一个 dialog，编辑时用 data-edit-profile 回填（不含 Key） */
for(const button of document.querySelectorAll('[data-open-dialog]')){button.addEventListener('click',()=>{const dialog=document.getElementById(button.dataset.openDialog);if(!dialog)return;const form=dialog.querySelector('form');form.reset();form.elements.profile_id.value='';const editRaw=button.dataset.editProfile;if(editRaw){const p=JSON.parse(editRaw);form.elements.profile_id.value=p.profile_id||'';form.elements.name.value=p.name||'';form.elements.base_url.value=p.base_url||'';form.elements.model.value=p.model||'';form.elements.api_key.value='';form.elements.proxy_url.value=p.proxy_url||'';form.elements.ca_bundle.value=p.ca_bundle||'';form.elements.verify_tls.checked=p.verify_tls!==false;dialog.querySelector('[data-dialog-title]').textContent='编辑配置';}else{dialog.querySelector('[data-dialog-title]').textContent='新增配置';}dialog.showModal();});}
for(const button of document.querySelectorAll('[data-close-dialog]'))button.addEventListener('click',()=>button.closest('dialog')?.close());
/* 删除配置：二次点击确认，3 秒后自动复位 */
for(const button of document.querySelectorAll('[data-two-step]')){const confirmText='确认删除？';let armed=false,timer=null;button.addEventListener('click',e=>{if(!armed){e.preventDefault();armed=true;button.dataset.originalText=button.textContent;button.textContent=confirmText;button.classList.add('armed');timer=setTimeout(()=>{armed=false;button.textContent=button.dataset.originalText;button.classList.remove('armed')},3000);}else{clearTimeout(timer);}});}

/* 作品库搜索过滤：标题 / RJ / 作者 实时过滤卡片 */
const workSearch = document.getElementById('work-search');
if (workSearch) {
  workSearch.addEventListener('input', () => {
    const q = workSearch.value.trim().toLowerCase();
    for (const card of document.querySelectorAll('.work-card')) {
      card.style.display = card.textContent.toLowerCase().includes(q) ? '' : 'none';
    }
  });
}

/* iframe 外壳：通知顶层当前路径（侧边栏高亮） */
if (window.parent !== window) {
  try {
    window.parent.postMessage({ __navPath: window.location.pathname }, window.location.origin);
  } catch (e) {}
}

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
    player.setTrack(trackId, title, '');
    player.play(); // 切换音轨后直接播放（此刻有用户手势，自动播放放行）
    const topBar = window.top.document?.getElementById('player-bar');
    if (topBar) topBar.hidden = false;
  });
}

/* URL 下载导入：fetch 提交，错误在对话框内友好显示（避免裸 JSON 页面） */
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
