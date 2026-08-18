/* 全局播放器（单例）：play 界面与底部播放条共享同一个音频源。
 * 音频放在同源隐藏 iframe 中；播放状态经 localStorage 同步。
 * 跳页后在新页面自动重建并续播（浏览器对已播放站点放行自动播放）。 */
(() => {
  const bar = document.getElementById('player-bar');
  const KEY = 'sf.playback';
  if (!bar) return;

  const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; } };
  const write = (s) => localStorage.setItem(KEY, JSON.stringify(s));
  const fmtT = (t) => { if (t == null || !isFinite(t)) return '--:--'; const s = Math.max(0, Math.floor(t)), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60; const p = n => String(n).padStart(2, '0'); return h ? `${h}:${p(m)}:${p(sec)}` : `${m}:${p(sec)}`; };

  /* ── 全局单例：播放页与播放条共用 ── */
  const player = {
    state: read() || null,
    frame: null,
    audio: null,
    _listeners: { timeupdate: [], play: [], pause: [], loadedmetadata: [] },
    on(evt, fn) { this._listeners[evt]?.push(fn); },
    _emit(evt) { for (const fn of this._listeners[evt] || []) fn(this.audio); },
    get currentTime() { return this.audio ? this.audio.currentTime : 0; },
    get paused() { return this.audio ? this.audio.paused : true; },
    get duration() { return this.audio ? this.audio.duration || 0 : 0; },
    seek(t) { if (this.audio) this.audio.currentTime = t; },
    async toggle() {
      const a = await this.ensureAudio();
      if (!a) return;
      if (a.paused) await a.play().catch(() => {}); else a.pause();
    },
    async play() { const a = await this.ensureAudio(); if (a) await a.play().catch(() => {}); },
    pause() { this.audio?.pause(); },
    ensureFrame() {
      if (this.frame && this.frame.contentWindow) return this.frame;
      if (!this.state || !this.state.trackId) return null;
      this.frame = document.createElement('iframe');
      this.frame.style.display = 'none';
      this.frame.setAttribute('aria-hidden', 'true');
      this.frame.src = `/tracks/${this.state.trackId}/play?embed=1`;
      document.body.appendChild(this.frame);
      this.audio = null;
      return this.frame;
    },
    bindAudio() {
      const doc = this.frame?.contentDocument;
      this.audio = doc ? doc.getElementById('audio') : null;
      if (!this.audio) return null;
      const s = read();
      if (s && s.currentTime && isFinite(s.currentTime) && this.audio.duration) {
        this.audio.currentTime = Math.min(s.currentTime, this.audio.duration);
      }
      this.audio.addEventListener('timeupdate', () => {
        const st = read();
        if (st) { st.currentTime = this.audio.currentTime; st.duration = this.audio.duration || st.duration; write(st); }
        this._emit('timeupdate');
      });
      this.audio.addEventListener('play', () => { const st = read(); if (st) { st.playing = true; write(st); } this._emit('play'); });
      this.audio.addEventListener('pause', () => { const st = read(); if (st) { st.playing = false; write(st); } this._emit('pause'); });
      this.audio.addEventListener('ended', () => { const st = read(); if (st) { st.playing = false; write(st); } this._emit('pause'); });
      this.audio.addEventListener('loadedmetadata', () => { const st = read(); if (st && st.currentTime && isFinite(st.currentTime)) this.audio.currentTime = Math.min(st.currentTime, this.audio.duration || st.currentTime); this._emit('loadedmetadata'); });
      return this.audio;
    },
    async ensureAudio() {
      this.ensureFrame();
      for (let i = 0; i < 50 && !(this.frame && this.frame.contentDocument && this.frame.contentDocument.getElementById('audio')); i++) {
        await new Promise(r => setTimeout(r, 100));
      }
      if (!this.audio) this.bindAudio();
      return this.audio;
    },
    async resume() {
      const a = await this.ensureAudio();
      if (!a) return false;
      if (!a.paused) return true;
      try { await a.play(); return true; } catch { return false; }
    },
    /* 设置当前播放（就地播放按钮用）：写状态后由调用方 reload 重建 */
    setTrack(trackId, title, itemId) {
      this.state = { trackId, title, itemId, currentTime: 0, playing: true };
      write(this.state);
    },
    /* 激活播放：设状态 + 渲染播放条 + 准备 iframe（播放页初始化用） */
    activate(trackId, title, itemId) {
      const st = read();
      if (!st || st.trackId !== trackId) {
        this.state = { trackId, title, itemId, currentTime: 0, duration: 0, playing: false };
        write(this.state);
      } else {
        this.state = st;
      }
      renderBar();
      if (this.state.playing || (this.state.currentTime && this.state.currentTime > 1)) {
        this.resume();
      }
      return this;
    },
    close() {
      const s = read(); if (s) { s.playing = false; write(s); }
      this.audio?.pause();
      this.frame?.remove();
      this.frame = null; this.audio = null;
      bar.hidden = true;
    },
  };
  window.SubForgePlayer = player;

  /* ── 底部播放条渲染（所有页面含播放页） ── */
  const renderBar = () => {
    const st = read();
    if (!st || !st.trackId) { bar.hidden = true; return; }
    bar.hidden = false;
    bar.className = 'player-bar';
    const safeTitle = (st.title || '播放中').replace(/"/g, '&quot;');
    bar.innerHTML = `
      <img class="player-bar-cover" src="/covers/${st.itemId || ''}" alt="" onerror="this.remove()">
      <a class="player-bar-title" href="/tracks/${st.trackId}/play" title="${safeTitle}">${safeTitle}</a>
      <span class="player-bar-time" data-role="time">${fmtT(st.currentTime)}</span>
      <button type="button" class="ghost small" data-role="resume" hidden>▶ 继续播放</button>
      <button type="button" class="ghost small" data-role="toggle" aria-label="播放/暂停">▶</button>
      <button type="button" class="ghost small" data-role="open" aria-label="打开播放页">⛶</button>
      <button type="button" class="ghost small" data-role="close" aria-label="关闭">✕</button>
    `;
    const toggleBtn = bar.querySelector('[data-role="toggle"]');
    const resumeBtn = bar.querySelector('[data-role="resume"]');
    bar.querySelector('[data-role="toggle"]').addEventListener('click', () => player.toggle());
    bar.querySelector('[data-role="resume"]').addEventListener('click', async () => { const a = await player.ensureAudio(); if (a) await a.play().catch(() => {}); });
    bar.querySelector('[data-role="open"]').addEventListener('click', () => { window.location.href = `/tracks/${st.trackId}/play`; });
    bar.querySelector('[data-role="close"]').addEventListener('click', () => player.close());
    const syncUI = () => {
      bar.querySelector('[data-role="time"]').textContent = fmtT(player.currentTime);
      toggleBtn.textContent = player.paused ? '▶' : '⏸';
      resumeBtn.hidden = !player.paused || !(st.playing);
    };
    player.on('timeupdate', syncUI);
    player.on('play', syncUI);
    player.on('pause', syncUI);
    syncUI();
  };

  renderBar();
  // 跨页恢复：之前正在播放或有进度 → 自动重建 iframe 续播
  const st = read();
  if (st && (st.playing || (st.currentTime && st.currentTime > 1))) {
    player.resume().then(ok => { if (!ok) renderBar(); });
  }
})();

/* 就地播放：点击 data-play-track 时在底部条中开始播放（不跳转页面）。 */
for (const btn of document.querySelectorAll('[data-play-track]')) {
  btn.addEventListener('click', () => {
    const url = btn.dataset.playTrack;
    const trackId = url.split('/').filter(Boolean).slice(-2)[0];
    const row = btn.closest('.track-row');
    const title = row?.querySelector('h2')?.textContent || '播放中';
    window.SubForgePlayer?.setTrack(trackId, title, '');
    location.reload();
  });
}
