/* 悬浮歌词（Document Picture-in-Picture）：顶层外壳模块。
 * PiP 窗口只允许顶层浏览上下文开窗，因此实现在外壳层：
 * 播放页按钮与底部播放条按钮都委托到 window.SubForgeFloatLyrics.toggle()。
 * 歌词数据经 /tracks/{id}/subtitles 双轨接口懒加载并按音轨缓存；
 * 显示模式沿用播放页的字幕模式（sf.subtitleMode：双语/仅原文/仅译文/关闭），
 * 播放页内切换模式经 storage 事件实时同步到悬浮窗。 */
(() => {
  const PLAY_KEY = 'sf.playback';
  const MODE_KEY = 'sf.subtitleMode';
  let pipWin = null, els = null, locked = false;
  let source = [], target = [], loadedTrack = null;
  let rafId = 0, themeObserver = null;
  const changeListeners = new Map();

  const readState = () => { try { return JSON.parse(localStorage.getItem(PLAY_KEY) || 'null'); } catch { return null; } };
  const mode = () => localStorage.getItem(MODE_KEY) || 'both';
  function locate(entries, time) {
    let lo = 0, hi = entries.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1, e = entries[mid];
      if (time < e.start) hi = mid - 1; else if (time > e.end) lo = mid + 1; else return mid;
    }
    return -1;
  }
  const currentTrackId = () => { const st = readState(); return st && st.trackId; };

  const FLOAT_CSS = `
:root{font-family:ui-monospace,"Cascadia Mono","JetBrains Mono",Consolas,"Liberation Mono",monospace,"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif}
body{margin:0;height:100vh;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:6px;
  background:var(--float-bg);color:var(--float-fg);overflow:hidden;padding:8px 20px;-webkit-user-select:none;user-select:none}
.float-main{font-size:1.5rem;font-weight:650;line-height:1.35;text-align:center;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.float-sub{font-size:1.05rem;color:var(--fg-dim);line-height:1.4;text-align:center;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.float-idle{color:var(--fg-faint);font-size:1rem;font-weight:400}
.float-controls{position:fixed;top:6px;right:8px;display:flex;gap:6px}
.float-chip{border:1px solid var(--line-strong);border-radius:99px;background:var(--panel);color:var(--fg-dim);
  font:inherit;font-size:.75rem;padding:2px 10px;cursor:pointer;opacity:.45;transition:opacity .12s}
.float-controls:hover .float-chip{opacity:1}
body.locked .float-main,body.locked .float-sub{pointer-events:none}
body.locked #float-close{display:none}
`;

  function syncTheme() {
    if (!pipWin) return;
    const cs = getComputedStyle(document.documentElement);
    const root = pipWin.document.documentElement;
    root.dataset.theme = document.documentElement.dataset.theme;
    root.style.setProperty('--float-bg', cs.backgroundColor);
    root.style.setProperty('--float-fg', cs.color);
    ['--panel', '--line', '--line-strong', '--fg-dim', '--fg-faint', '--accent'].forEach(v => root.style.setProperty(v, cs.getPropertyValue(v)));
  }

  async function loadSubtitles(trackId) {
    if (loadedTrack === trackId) return;
    loadedTrack = trackId; source = []; target = [];
    try {
      const r = await fetch(`/tracks/${trackId}/subtitles`);
      if (r.ok) {
        const d = await r.json();
        source = d.source || []; target = d.target || [];
      }
    } catch { /* 网络失败保持空态，悬浮窗显示"暂无字幕" */ }
    render();
  }

  /* 脏检查：仅在行内容变化时写 PiP DOM。跨文档写入会强制 PiP 文档重排重绘，
   * 每帧无条件写入会让媒体解码线程挨饿、audio.currentTime 推进减速（音字整体变慢）。 */
  let lastMain = null, lastSub = null, lastIdle = null;
  function writeMain(el, text, idle) {
    if (lastMain !== text) { el.textContent = text; lastMain = text; }
    if (lastIdle !== idle) { el.classList.toggle('float-idle', idle); lastIdle = idle; }
  }
  function writeSub(text) { if (lastSub !== text) { els.sub.textContent = text; lastSub = text; } }
  function render() {
    if (!els || !els.win) return;
    const player = window.SubForgePlayer;
    const { main, sub } = els;
    const m = mode();
    if (m === 'off') { writeMain(main, '字幕已关闭', true); writeSub(''); return; }
    if (!source.length && !target.length) { writeMain(main, '暂无字幕', true); writeSub(''); return; }
    if (!player || !player.audio) { writeMain(main, '等待播放…', true); writeSub(''); return; }
    writeMain(main, '', false);
    const t = player.currentTime;
    const si = locate(source, t), ti = locate(target, t);
    if (m === 'both') {
      writeMain(main, si >= 0 ? source[si].text : '…', false);
      writeSub(ti >= 0 ? target[ti].text : '');
    } else if (m === 'source') {
      writeMain(main, si >= 0 ? source[si].text : '…', false);
      writeSub('');
    } else {
      writeMain(main, ti >= 0 ? target[ti].text : (si >= 0 ? source[si].text : '…'), false);
      writeSub('');
    }
  }
  function loop() { render(); rafId = requestAnimationFrame(loop); }
  function notify() { for (const fn of changeListeners.values()) fn(); }

  function applyLock() {
    if (!pipWin) return;
    pipWin.document.body.classList.toggle('locked', locked);
    const btn = pipWin.document.getElementById('float-lock');
    if (btn) btn.textContent = locked ? '解锁' : '锁定';
  }

  async function open(trackId) {
    pipWin = await window.documentPictureInPicture.requestWindow({ width: 520, height: 150 });
    const doc = pipWin.document;
    doc.head.append(Object.assign(doc.createElement('style'), { textContent: FLOAT_CSS }));
    doc.body.innerHTML = `<div class="float-main" id="float-main">加载中…</div><div class="float-sub" id="float-sub"></div>
      <div class="float-controls"><button class="float-chip" id="float-lock">锁定</button><button class="float-chip" id="float-close">关闭</button></div>`;
    els = { win: pipWin, main: doc.getElementById('float-main'), sub: doc.getElementById('float-sub') };
    locked = false; lastMain = lastSub = lastIdle = null;
    syncTheme(); render();
    themeObserver = new MutationObserver(syncTheme);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    doc.getElementById('float-lock').onclick = () => { locked = !locked; applyLock(); };
    doc.getElementById('float-close').onclick = () => pipWin.close();
    pipWin.addEventListener('pagehide', cleanup);
    notify();
    loadSubtitles(trackId);
    loop();
  }
  function cleanup() {
    cancelAnimationFrame(rafId); rafId = 0;
    themeObserver?.disconnect(); themeObserver = null;
    pipWin = null; els = null; locked = false;
    notify();
  }

  window.SubForgeFloatLyrics = {
    /* 入口：trackId 缺省时取当前播放音轨；需要用户手势（点击）触发 */
    async toggle(trackId) {
      trackId = trackId || currentTrackId();
      if (!trackId) return;
      if (pipWin) { pipWin.close(); return; }
      if (!('documentPictureInPicture' in window)) return;
      try { await open(trackId); } catch { /* 用户手势缺失或开窗失败：静默 */ }
    },
    isActive: () => !!pipWin,
    onChange(fn, tag) { changeListeners.set(tag || fn, fn); },
  };

  /* 音轨切换 / 字幕模式切换（播放页 iframe 写 localStorage）→ 顶层收到 storage 事件 */
  window.addEventListener('storage', e => {
    if (e.key === PLAY_KEY) {
      const tid = currentTrackId();
      if (tid && tid !== loadedTrack && pipWin) loadSubtitles(tid);
    }
    if (e.key === MODE_KEY && pipWin) render();
  });
})();
