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
    audioContext: null,
    sourceNode: null,
    gainNode: null,
    _listeners: { timeupdate: [], play: [], pause: [], loadedmetadata: [] },
    on(evt, fn) { this._listeners[evt]?.push(fn); },
    _emit(evt) { for (const fn of this._listeners[evt] || []) fn(this.audio); },
    get currentTime() { return this.audio ? this.audio.currentTime : 0; },
    get paused() { return this.audio ? this.audio.paused : true; },
    get duration() { return this.audio ? this.audio.duration || 0 : 0; },
    seek(t) { if (this.audio) this.audio.currentTime = t; },
    get volume() { const value = read()?.volume; return Number.isFinite(value) ? Math.max(0, Math.min(2, value)) : 1; },
    setVolume(value) {
      const volume = Math.max(0, Math.min(2, Number(value) || 0));
      if (this.gainNode) this.gainNode.gain.value = volume;
      else if (this.audio) this.audio.volume = Math.min(1, volume);
      const st = read() || {};
      st.volume = volume;
      write(st);
      return volume;
    },
    _releaseAudioGraph() {
      this.sourceNode?.disconnect();
      this.gainNode?.disconnect();
      this.sourceNode = null;
      this.gainNode = null;
    },
    _setupAudioGraph() {
      if (!this.audio || this.sourceNode) return;
      try {
        this.audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
        this.sourceNode = this.audioContext.createMediaElementSource(this.audio);
        this.gainNode = this.audioContext.createGain();
        this.sourceNode.connect(this.gainNode).connect(this.audioContext.destination);
        this.audio.volume = 1;
        this.gainNode.gain.value = this.volume;
      } catch (_) {
        // Older browsers or repeated MediaElementSource binding: use native 0–100% volume.
        this.audio.volume = Math.min(1, this.volume);
      }
    },
    async _resumeAudioContext() { if (this.audioContext?.state === 'suspended') await this.audioContext.resume().catch(() => {}); },
    async toggle() {
      const a = await this.ensureAudio();
      if (!a) return;
      if (a.paused) { await this._resumeAudioContext(); await a.play().catch(() => {}); } else a.pause();
    },
    async play() { const a = await this.ensureAudio(); if (a) { await this._resumeAudioContext(); await a.play().catch(() => {}); } },
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
      this._setupAudioGraph();
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
      try { await this._resumeAudioContext(); await a.play(); return true; } catch { return false; }
    },
    /* 设置当前播放（就地播放按钮用）：切换音轨时释放旧 iframe 重建 */
    setTrack(trackId, title, itemId) {
      if (this.frame && this.state && this.state.trackId !== trackId) {
        this.frame.remove();
        this.frame = null;
        this._releaseAudioGraph();
        this.audio = null;
      }
      this.state = { trackId, title, itemId, currentTime: 0, duration: 0, playing: false, volume: this.volume };
      write(this.state);
      renderBar();
    },
    /* 激活播放：设状态 + 渲染播放条 + 准备 iframe（播放页初始化用）。
     * 不自动播放——音频由底部播放栏（或播放页控制条）上的用户操作控制。 */
    activate(trackId, title, itemId) {
      const st = read();
      if (!st || st.trackId !== trackId) {
        // 播放页切换音轨时必须释放旧 embed iframe；否则 ensureAudio()
        // 会复用旧音轨的 <audio>，页面显示 B 却实际播放 A。
        if (this.frame) this.frame.remove();
        this.frame = null;
        this._releaseAudioGraph();
        this.audio = null;
        this.state = { trackId, title, itemId, currentTime: 0, duration: 0, playing: false, volume: this.volume };
        write(this.state);
      } else {
        this.state = st;
        // 同音轨时也要修复旧版记录缺失/过期的 itemId（旧代码写入 ''导致封面 404）。
        if (itemId && st.itemId !== itemId) {
          st.itemId = itemId;
          write(st);
          renderBar();
        }
      }
      renderBar();
      return this;
    },
    close() {
      const s = read(); if (s) { s.playing = false; write(s); }
      this.audio?.pause();
      this.frame?.remove();
      this._releaseAudioGraph();
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
    const volume = Number.isFinite(st.volume) ? Math.max(0, Math.min(2, st.volume)) : 1;
    const coverUrl = st.itemId ? `/covers/${st.itemId}` : '';
    bar.innerHTML = `
      <div class="player-bar-title-row"><a class="player-bar-title" href="/tracks/${st.trackId}/play" target="content-frame" title="${safeTitle}">${safeTitle}</a></div>
      <div class="player-bar-lower-row">
        <div class="player-bar-cover">${coverUrl ? `<img src="${coverUrl}" alt="" onerror="this.hidden=true">` : ''}</div>
        <div class="player-bar-progress-wrap"><input type="range" class="player-bar-seek" data-role="seek" min="0" max="${st.duration || 0}" step="0.1" value="${st.currentTime || 0}" aria-label="播放进度"><span class="player-bar-time" data-role="time">${fmtT(st.currentTime)}</span></div>
        <button type="button" class="ghost small" data-role="toggle" aria-label="播放/暂停">▶</button>
        <label class="player-bar-volume" title="音量"><span aria-hidden="true">🔊</span><input type="range" data-role="volume" min="0" max="2" step="0.01" value="${volume}" aria-label="音量，最高 200%"><output data-role="volume-value">${Math.round(volume * 100)}%</output></label>
        <button type="button" class="ghost small" data-role="open" aria-label="打开播放页">⛶</button>
      </div>
    `;
    const toggleBtn = bar.querySelector('[data-role="toggle"]');
    const seekInput = bar.querySelector('[data-role="seek"]');
    const volumeInput = bar.querySelector('[data-role="volume"]');
    const volumeValue = bar.querySelector('[data-role="volume-value"]');
    bar.querySelector('[data-role="toggle"]').addEventListener('click', () => player.toggle());
    // iframe 外壳：打开播放页 = iframe 内导航（顶层外壳保持不变）
    bar.querySelector('[data-role="open"]').addEventListener('click', () => {
      const frame = document.getElementById('content-frame');
      if (frame) { frame.src = `/tracks/${st.trackId}/play`; }
      else { window.location.href = `/tracks/${st.trackId}/play`; }
    });
    seekInput.addEventListener('input', () => { player.seek(parseFloat(seekInput.value)); });
    volumeInput.addEventListener('input', () => { const value = player.setVolume(volumeInput.value); volumeValue.value = `${Math.round(value * 100)}%`; volumeValue.textContent = `${Math.round(value * 100)}%`; });
    const syncUI = () => {
      bar.querySelector('[data-role="time"]').textContent = fmtT(player.currentTime);
      toggleBtn.textContent = player.paused ? '▶' : '⏸';
      const dur = player.duration || st.duration || 0;
      seekInput.max = dur || 0;
      seekInput.value = player.currentTime || 0;
      volumeInput.value = player.volume;
      volumeValue.value = `${Math.round(player.volume * 100)}%`;
      volumeValue.textContent = `${Math.round(player.volume * 100)}%`;
    };
    player.on('timeupdate', syncUI);
    player.on('play', syncUI);
    player.on('pause', syncUI);
    player.on('loadedmetadata', syncUI);
    syncUI();
  };

  renderBar();
})();
