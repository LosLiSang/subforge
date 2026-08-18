/* 全局底部播放条：任何页面就地播放，跨页不中断。
 * 音频放在同源隐藏 iframe 中（页面导航不会销毁 iframe），
 * 播放状态经 localStorage 同步，各页面底部显示控制条。 */
(() => {
  const bar = document.getElementById('player-bar');
  const KEY = 'sf.playback';
  if (!bar) return;

  const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; } };
  const write = (s) => localStorage.setItem(KEY, JSON.stringify(s));
  const fmtT = (t) => { if (t == null || !isFinite(t)) return '--:--'; const s = Math.max(0, Math.floor(t)), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60; const p = n => String(n).padStart(2, '0'); return h ? `${h}:${p(m)}:${p(sec)}` : `${m}:${p(sec)}`; };

  // 播放页（含 iframe embed）由 player.js 驱动，这里不渲染。
  if (document.getElementById('player')) return;

  const state = read();
  if (!state || !state.trackId) return;

  bar.hidden = false;
  bar.className = 'player-bar';
  const safeTitle = (state.title || '播放中').replace(/"/g, '&quot;');
  bar.innerHTML = `
    <img class="player-bar-cover" src="/covers/${state.itemId || ''}" alt="" onerror="this.remove()">
    <a class="player-bar-title" href="/tracks/${state.trackId}/play" title="${safeTitle}">${safeTitle}</a>
    <span class="player-bar-time" data-role="time">--:--</span>
    <button type="button" class="ghost small" data-role="toggle" aria-label="播放/暂停">▶</button>
    <button type="button" class="ghost small" data-role="open" aria-label="打开播放页">⛶</button>
    <button type="button" class="ghost small" data-role="close" aria-label="关闭">✕</button>
  `;

  let frame = null;
  let audio = null;

  function ensureFrame() {
    if (frame && frame.contentWindow) return frame;
    frame = document.createElement('iframe');
    frame.style.display = 'none';
    frame.setAttribute('aria-hidden', 'true');
    frame.src = `/tracks/${state.trackId}/play?embed=1`;
    document.body.appendChild(frame);
    audio = null;
    return frame;
  }

  function bindAudio() {
    const doc = frame?.contentDocument;
    audio = doc ? doc.getElementById('audio') : null;
    if (!audio) return;
    const now = read();
    if (now && now.currentTime && isFinite(now.currentTime) && audio.duration) {
      audio.currentTime = Math.min(now.currentTime, audio.duration);
    }
    if (now?.playing && audio.paused) {
      audio.play().catch(() => {});
    }
    audio.addEventListener('timeupdate', () => {
      const s = read();
      if (s) { s.currentTime = audio.currentTime; s.duration = audio.duration || s.duration; write(s); }
      bar.querySelector('[data-role="time"]').textContent = fmtT(audio.currentTime);
    });
    audio.addEventListener('play', () => { const s = read(); if (s) { s.playing = true; write(s); } bar.querySelector('[data-role="toggle"]').textContent = '⏸'; });
    audio.addEventListener('pause', () => { const s = read(); if (s) { s.playing = false; write(s); } bar.querySelector('[data-role="toggle"]').textContent = '▶'; });
    audio.addEventListener('loadedmetadata', () => {
      const s = read();
      if (s && s.currentTime && isFinite(s.currentTime)) {
        audio.currentTime = Math.min(s.currentTime, audio.duration || s.currentTime);
      }
    });
  }

  async function ensureBound() {
    ensureFrame();
    for (let i = 0; i < 50 && !(frame.contentDocument && frame.contentDocument.getElementById('audio')); i++) {
      await new Promise(r => setTimeout(r, 100));
    }
    bindAudio();
    return audio;
  }

  bar.querySelector('[data-role="toggle"]').addEventListener('click', async () => {
    const a = await ensureBound();
    if (!a) return;
    if (a.paused) await a.play().catch(() => {}); else a.pause();
  });
  bar.querySelector('[data-role="open"]').addEventListener('click', () => { window.location.href = `/tracks/${state.trackId}/play`; });
  bar.querySelector('[data-role="close"]').addEventListener('click', () => {
    const s = read(); if (s) { s.playing = false; write(s); }
    audio?.pause();
    frame?.remove();
    bar.hidden = true;
  });

  // 跨页恢复：之前正在播放或有进度 → 自动重建 iframe 续播（有播放许可时自动开始）
  if (state.playing || (state.currentTime && state.currentTime > 1)) {
    ensureBound().then(a => {
      if (a && a.paused && state.playing) a.play().catch(() => {});
    });
  }
})();

/* 就地播放：点击 data-play-track 时在底部条中开始播放（不跳转页面）。 */
for (const btn of document.querySelectorAll('[data-play-track]')) {
  btn.addEventListener('click', () => {
    const url = btn.dataset.playTrack;
    const trackId = url.split('/').filter(Boolean).slice(-2)[0];
    const row = btn.closest('.track-row');
    const title = row?.querySelector('h2')?.textContent || '播放中';
    const cur = JSON.parse(localStorage.getItem('sf.playback') || 'null') || {};
    localStorage.setItem('sf.playback', JSON.stringify({ ...cur, trackId, title, currentTime: 0, playing: true }));
    location.reload(); // 重新加载让 global-player.js 统一重建底部条并续播
  });
}
