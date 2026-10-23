/* ECA_BOT web control panel */
(function () {
  "use strict";

  const POLL_MS = 2500;
  const TOAST_MS = 3500;

  const el = {
    loginView: document.getElementById("login-view"),
    appView: document.getElementById("app-view"),
    loginForm: document.getElementById("login-form"),
    token: document.getElementById("token"),
    loginError: document.getElementById("login-error"),
    logoutBtn: document.getElementById("logout-btn"),
    pillOnline: document.getElementById("pill-online"),
    pillVoice: document.getElementById("pill-voice"),
    pillGuild: document.getElementById("pill-guild"),
    channelSelect: document.getElementById("channel-select"),
    joinBtn: document.getElementById("join-btn"),
    leaveBtn: document.getElementById("leave-btn"),
    playQuery: document.getElementById("play-query"),
    playDownload: document.getElementById("play-download"),
    playBtn: document.getElementById("play-btn"),
    playerNowTitle: document.getElementById("player-now-title"),
    playerNowMeta: document.getElementById("player-now-meta"),
    playerNowImg: document.getElementById("player-now-img"),
    seek: document.getElementById("seek"),
    seekPos: document.getElementById("seek-pos"),
    seekDur: document.getElementById("seek-dur"),
    filterSelect: document.getElementById("filter-select"),
    crossfade: document.getElementById("crossfade"),
    crossfadeLabel: document.getElementById("crossfade-label"),
    queueList: document.getElementById("queue-list"),
    queueEmpty: document.getElementById("queue-empty"),
    queueCount: document.getElementById("queue-count"),
    searchQuery: document.getElementById("search-query"),
    searchBtn: document.getElementById("search-btn"),
    searchResults: document.getElementById("search-results"),
    searchEmpty: document.getElementById("search-empty"),
    plName: document.getElementById("pl-name"),
    plCreate: document.getElementById("pl-create"),
    plList: document.getElementById("pl-list"),
    plEmpty: document.getElementById("pl-empty"),
    plRefresh: document.getElementById("pl-refresh"),
    plDetail: document.getElementById("pl-detail"),
    plDetailTitle: document.getElementById("pl-detail-title"),
    plDetailClose: document.getElementById("pl-detail-close"),
    plSong: document.getElementById("pl-song"),
    plAdd: document.getElementById("pl-add"),
    plYoutubeUrl: document.getElementById("pl-youtube-url"),
    plYoutubeImport: document.getElementById("pl-youtube-import"),
    plSongs: document.getElementById("pl-songs"),
    plSongsEmpty: document.getElementById("pl-songs-empty"),
    libList: document.getElementById("lib-list"),
    libEmpty: document.getElementById("lib-empty"),
    libRefresh: document.getElementById("lib-refresh"),
    npTitle: document.getElementById("np-title"),
    npSub: document.getElementById("np-sub"),
    btnPause: document.getElementById("btn-pause"),
    btnResume: document.getElementById("btn-resume"),
    btnSkip: document.getElementById("btn-skip"),
    btnStop: document.getElementById("btn-stop"),
    btnShuffle: document.getElementById("btn-shuffle"),
    btnClear: document.getElementById("btn-clear"),
    btnAutoplay: document.getElementById("btn-autoplay"),
    btnLoop: document.getElementById("btn-loop"),
    vol: document.getElementById("vol"),
    volLabel: document.getElementById("vol-label"),
    toast: document.getElementById("toast"),
  };

  let pollTimer = null;
  let ws = null;
  let wsAlive = false;
  let selectedPlaylist = null;
  let volDebounce = null;
  let lastVolSent = null;
  let toastTimer = null;
  let queueDragActive = false;
  let queueDragStartOrder = "";
  // Son gelen konum; aradaki süre tarayıcıda ilerletilir
  let playback = { position: 0, duration: 0, speed: 1, running: false, at: 0 };
  let seekHold = false;

  const LOOP_TITLES = { off: "Döngü: kapalı", song: "Döngü: şarkı", queue: "Döngü: kuyruk" };
  const LOOP_NEXT = { off: "song", song: "queue", queue: "off" };

  function formatTime(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = String(sec % 60).padStart(2, "0");
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + s : m + ":" + s;
  }

  function parseError(data, fallback) {
    if (!data) return fallback || "İstek başarısız";
    if (typeof data.detail === "object" && data.detail !== null) {
      return data.detail.error || data.detail.message || fallback || "Hata";
    }
    if (typeof data.detail === "string") return data.detail;
    if (data.error) return data.error;
    return fallback || "İstek başarısız";
  }

  async function api(path, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    const hasBody = opts.body !== undefined && opts.body !== null;
    if (hasBody && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, {
      credentials: "include",
      ...opts,
      headers,
    });
    let data = null;
    const text = await res.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_) {
        data = null;
      }
    }
    if (!res.ok) {
      const msg = parseError(data, res.statusText || "HTTP " + res.status);
      const err = new Error(msg);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function showToast(msg, ok) {
    if (!msg) return;
    el.toast.textContent = msg;
    el.toast.classList.toggle("ok", !!ok);
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.toast.hidden = true;
    }, TOAST_MS);
  }

  function toastError(err) {
    const msg = (err && err.message) || String(err) || "Hata";
    showToast(msg, false);
  }

  function setLoginError(msg) {
    if (!msg) {
      el.loginError.hidden = true;
      el.loginError.textContent = "";
      return;
    }
    el.loginError.textContent = msg;
    el.loginError.hidden = false;
  }

  function showLogin() {
    el.appView.hidden = true;
    el.loginView.hidden = false;
    stopRealtime();
  }

  function showApp() {
    el.loginView.hidden = true;
    el.appView.hidden = false;
  }

  function formatDuration(sec) {
    if (sec == null || sec === "" || isNaN(Number(sec))) return "";
    const s = Math.max(0, Math.floor(Number(sec)));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return m + ":" + String(r).padStart(2, "0");
  }

  function formatSize(bytes) {
    if (bytes == null || isNaN(Number(bytes))) return "";
    const n = Number(bytes);
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* —— Tabs —— */
  document.querySelectorAll(".tabs .tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const tab = btn.getAttribute("data-tab");
      document.querySelectorAll(".tabs .tab").forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      document.querySelectorAll(".tab-panel").forEach(function (panel) {
        panel.hidden = panel.id !== "tab-" + tab;
      });
      if (tab === "playlists") loadPlaylists();
      if (tab === "library") loadLibrary();
      if (tab === "search") el.searchQuery.focus();
      if (tab === "ytm") ytmOnShow();
    });
  });

  /* —— Auth —— */
  el.loginForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    setLoginError("");
    const token = (el.token.value || "").trim();
    if (!token) {
      setLoginError("Token gerekli");
      return;
    }
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ token: token }),
      });
      el.token.value = "";
      await enterApp();
    } catch (err) {
      setLoginError(err.message || "Giriş başarısız");
    }
  });

  el.logoutBtn.addEventListener("click", async function () {
    try {
      await api("/api/auth/logout", { method: "POST", body: "{}" });
    } catch (_) {
      /* still leave UI */
    }
    showLogin();
  });

  async function probeAuth() {
    try {
      await api("/api/status");
      return true;
    } catch (err) {
      if (err.status === 401) return false;
      // Other errors (guild, etc.) still mean authenticated
      if (err.status && err.status !== 401) return true;
      return false;
    }
  }

  async function enterApp() {
    showApp();
    try {
      await Promise.all([refreshState(), loadChannels(), loadPlaylists(), loadLibrary()]);
    } catch (err) {
      if (err.status === 401) {
        showLogin();
        return;
      }
      toastError(err);
    }
    connectWs();
  }

  /* —— State UI —— */
  function applyStatus(status) {
    if (!status) return;
    const online = !!status.online;
    el.pillOnline.textContent = online ? "Online" : "Offline";
    el.pillOnline.classList.toggle("on", online);
    el.pillOnline.classList.toggle("off", !online);

    const voice = status.voice_channel;
    if (voice) {
      el.pillVoice.textContent = "Ses: " + voice;
      el.pillVoice.classList.add("on");
      el.pillVoice.classList.remove("off", "warn");
    } else {
      el.pillVoice.textContent = "Ses yok";
      el.pillVoice.classList.remove("on");
      el.pillVoice.classList.add("warn");
    }

    el.pillGuild.textContent = status.guild_name || status.guild_id || "Guild";

    if (typeof status.volume === "number") {
      const v = Math.round(status.volume);
      if (document.activeElement !== el.vol) {
        el.vol.value = String(v);
        el.volLabel.textContent = String(v);
      }
      lastVolSent = v;
    }

    const playing = !!status.is_playing;
    const paused = !!status.is_paused;
    el.btnPause.disabled = !playing || paused;
    el.btnResume.disabled = !paused;
    el.btnAutoplay.setAttribute("aria-pressed", status.autoplay ? "true" : "false");
    const loop = status.loop || "off";
    el.btnLoop.dataset.mode = loop;
    el.btnLoop.textContent = loop === "song" ? "🔂" : "🔁";
    el.btnLoop.title = LOOP_TITLES[loop] || LOOP_TITLES.off;
    el.btnLoop.setAttribute("aria-pressed", loop !== "off" ? "true" : "false");
    if (document.activeElement !== el.filterSelect) {
      el.filterSelect.value = status.filter || "off";
    }
    if (typeof status.crossfade === "number" && document.activeElement !== el.crossfade) {
      el.crossfade.value = String(status.crossfade);
      el.crossfadeLabel.textContent = crossfadeText(status.crossfade);
    }
    playback.running = playing && !paused && !status.is_loading;
  }

  function renderPlayback() {
    let pos = playback.position;
    if (playback.running) pos += ((Date.now() - playback.at) / 1000) * playback.speed;
    if (playback.duration) pos = Math.min(pos, playback.duration);
    el.seekPos.textContent = formatTime(pos);
    el.seekDur.textContent = playback.duration ? formatTime(playback.duration) : "—";
    if (!seekHold) {
      el.seek.max = String(playback.duration || 0);
      el.seek.value = String(Math.floor(pos));
    }
  }

  function setNowArt(url) {
    if (url && /^https?:\/\//.test(url)) {
      if (el.playerNowImg.getAttribute("src") !== url) el.playerNowImg.src = url;
      el.playerNowImg.hidden = false;
    } else {
      el.playerNowImg.hidden = true;
      el.playerNowImg.removeAttribute("src");
    }
  }

  function applyNow(now) {
    if (!now || !now.name) {
      el.npTitle.textContent = "Çalmıyor";
      el.npSub.textContent = "—";
      el.playerNowTitle.textContent = "Çalmıyor";
      el.playerNowMeta.textContent = "—";
      setNowArt(null);
      playback = { position: 0, duration: 0, speed: 1, running: false, at: Date.now() };
      el.seek.disabled = true;
      renderPlayback();
      return;
    }
    setNowArt(now.thumbnail);
    playback.position = now.position || 0;
    playback.duration = now.duration || 0;
    playback.speed = now.speed || 1;
    playback.at = Date.now();
    el.seek.disabled = !playback.duration;
    renderPlayback();
    const src = now.is_stream ? "Stream" : "Yerel";
    const user = now.user || "—";
    el.npTitle.textContent = now.name;
    el.npSub.textContent = src + " · " + user;
    el.playerNowTitle.textContent = now.name;
    el.playerNowMeta.textContent =
      src + " · İsteyen: " + user + (now.webpage_url ? " · " + now.webpage_url : "");
  }

  function queueOrderFromDom() {
    return Array.from(el.queueList.querySelectorAll("li[data-queue-id]")).map(function (item) {
      return item.dataset.queueId;
    });
  }

  function updateQueueIndexes() {
    el.queueList.querySelectorAll("li[data-queue-id]").forEach(function (item, index) {
      const idx = item.querySelector(".idx");
      if (idx) idx.textContent = String(index + 1);
    });
  }

  async function submitQueueOrder() {
    const queue_ids = queueOrderFromDom();
    try {
      const snapshot = await api("/api/queue/reorder", {
        method: "POST",
        body: JSON.stringify({ queue_ids: queue_ids }),
      });
      applySnapshot(snapshot);
    } catch (err) {
      toastError(err);
    } finally {
      await refreshState().catch(function (err) {
        if (err.status === 401) {
          showLogin();
        } else {
          toastError(err);
        }
      });
    }
  }

  async function removeQueueItem(queueId) {
    try {
      const snapshot = await api("/api/queue/" + encodeURIComponent(queueId), {
        method: "DELETE",
      });
      applySnapshot(snapshot);
    } catch (err) {
      if (err.status === 401) {
        showLogin();
      } else {
        toastError(err);
      }
    }
  }

  function handleQueueDragStart(event) {
    queueDragActive = true;
    queueDragStartOrder = JSON.stringify(queueOrderFromDom());
    event.currentTarget.classList.add("dragging");
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", event.currentTarget.dataset.queueId);
    }
  }

  function handleQueueDragEnd(event) {
    event.currentTarget.classList.remove("dragging");
    const changed = queueDragStartOrder !== JSON.stringify(queueOrderFromDom());
    queueDragActive = false;
    queueDragStartOrder = "";
    updateQueueIndexes();
    if (changed) {
      submitQueueOrder();
    } else {
      refreshState().catch(toastError);
    }
  }

  el.queueList.addEventListener("dragover", function (event) {
    if (!queueDragActive) return;
    event.preventDefault();
    const dragged = el.queueList.querySelector("li.dragging");
    const target = event.target.closest("li[data-queue-id]");
    if (!dragged || !target || target === dragged) return;
    const bounds = target.getBoundingClientRect();
    const afterTarget = event.clientY > bounds.top + bounds.height / 2;
    el.queueList.insertBefore(dragged, afterTarget ? target.nextSibling : target);
    updateQueueIndexes();
  });

  el.queueList.addEventListener("drop", function (event) {
    if (queueDragActive) event.preventDefault();
  });

  function applyQueue(queue) {
    if (queueDragActive) return;
    const items = Array.isArray(queue) ? queue : [];
    el.queueList.innerHTML = "";
    el.queueCount.textContent = String(items.length);
    el.queueEmpty.hidden = items.length > 0;
    items.forEach(function (song, i) {
      const li = document.createElement("li");
      li.draggable = true;
      li.dataset.queueId = String(song.queue_id);
      li.addEventListener("dragstart", handleQueueDragStart);
      li.addEventListener("dragend", handleQueueDragEnd);
      const src = song.is_stream ? "🌐" : "📁";
      li.innerHTML =
        '<span class="idx">' +
        (i + 1) +
        "</span>" +
        '<div class="item-main">' +
        '<div class="item-title">' +
        escapeHtml(song.name || "—") +
        "</div>" +
        '<div class="item-meta">' +
        src +
        " · " +
        escapeHtml(song.user || "—") +
        "</div>" +
        "</div>" +
        '<div class="item-actions">' +
        '<button type="button" class="btn btn-sm btn-danger" draggable="false">Kaldır</button>' +
        "</div>";
      li.querySelector("button").addEventListener("click", function () {
        removeQueueItem(song.queue_id);
      });
      el.queueList.appendChild(li);
    });
  }

  function applySnapshot(snap) {
    if (!snap || snap.error) return;
    if (snap.status) applyStatus(snap.status);
    if (snap.now !== undefined) {
      applyNow(snap.now);
    } else if (snap.current !== undefined) {
      applyNow(snap.current);
    }
    if (snap.queue !== undefined) applyQueue(snap.queue);
  }

  async function refreshState() {
    const snap = await api("/api/status")
      .then(async function (status) {
        let now = null;
        let queue = [];
        try {
          const n = await api("/api/now");
          now = n && n.now !== undefined ? n.now : n;
        } catch (_) {}
        try {
          const q = await api("/api/queue");
          queue = (q && q.queue) || [];
        } catch (_) {}
        return { status: status, now: now, queue: queue };
      });
    applySnapshot(snap);
    return snap;
  }

  /* —— WebSocket + poll fallback —— */
  function stopRealtime() {
    wsAlive = false;
    if (ws) {
      try {
        ws.close();
      } catch (_) {}
      ws = null;
    }
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(function () {
      refreshState().catch(function (err) {
        if (err.status === 401) {
          stopRealtime();
          showLogin();
        }
      });
    }, POLL_MS);
  }

  function connectWs() {
    stopRealtime();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = proto + "://" + location.host + "/ws/state";
    try {
      ws = new WebSocket(url);
    } catch (_) {
      startPolling();
      return;
    }
    ws.onopen = function () {
      wsAlive = true;
    };
    ws.onmessage = function (ev) {
      try {
        const data = JSON.parse(ev.data);
        if (data && data.error) return;
        applySnapshot(data);
      } catch (_) {}
    };
    ws.onerror = function () {
      /* close will fire */
    };
    ws.onclose = function () {
      wsAlive = false;
      ws = null;
      if (!el.appView.hidden) startPolling();
    };
  }

  /* —— Voice —— */
  async function loadChannels() {
    try {
      const data = await api("/api/channels");
      const channels = (data && data.channels) || [];
      const prev = el.channelSelect.value;
      el.channelSelect.innerHTML = "";
      if (!channels.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Kanal yok";
        el.channelSelect.appendChild(opt);
        return;
      }
      channels.forEach(function (ch) {
        const opt = document.createElement("option");
        opt.value = ch.id;
        opt.textContent = ch.name;
        el.channelSelect.appendChild(opt);
      });
      if (prev && channels.some(function (c) { return c.id === prev; })) {
        el.channelSelect.value = prev;
      }
    } catch (err) {
      el.channelSelect.innerHTML = '<option value="">Kanal yüklenemedi</option>';
      if (err.status !== 401) toastError(err);
      throw err;
    }
  }

  el.joinBtn.addEventListener("click", async function () {
    const channel_id = el.channelSelect.value;
    if (!channel_id) {
      showToast("Kanal seçin", false);
      return;
    }
    try {
      const status = await api("/api/voice/join", {
        method: "POST",
        body: JSON.stringify({ channel_id: channel_id }),
      });
      applyStatus(status);
      showToast("Ses kanalına katıldı", true);
    } catch (err) {
      toastError(err);
    }
  });

  el.leaveBtn.addEventListener("click", async function () {
    try {
      await api("/api/voice/leave", { method: "POST", body: "{}" });
      showToast("Ses kanalından ayrıldı", true);
      await refreshState().catch(function () {});
    } catch (err) {
      toastError(err);
    }
  });

  /* —— Play —— */
  el.playBtn.addEventListener("click", async function () {
    const query = (el.playQuery.value || "").trim();
    if (!query) {
      showToast("URL veya dosya adı girin", false);
      return;
    }
    try {
      el.playBtn.disabled = true;
      const snap = await api("/api/play", {
        method: "POST",
        body: JSON.stringify({
          query: query,
          download: !!el.playDownload.checked,
        }),
      });
      applySnapshot(snap);
      showToast("Çalınıyor / kuyruğa eklendi", true);
    } catch (err) {
      toastError(err);
    } finally {
      el.playBtn.disabled = false;
    }
  });

  el.playQuery.addEventListener("keydown", function (e) {
    if (e.key === "Enter") el.playBtn.click();
  });

  /* —— Controls —— */
  async function control(action) {
    try {
      const snap = await api("/api/control/" + action, {
        method: "POST",
        body: "{}",
      });
      applySnapshot(snap);
    } catch (err) {
      toastError(err);
    }
  }

  el.btnPause.addEventListener("click", function () { control("pause"); });
  el.btnResume.addEventListener("click", function () { control("resume"); });
  el.btnSkip.addEventListener("click", function () { control("skip"); });
  el.btnStop.addEventListener("click", function () { control("stop"); });
  el.btnShuffle.addEventListener("click", function () { control("shuffle"); });
  el.btnClear.addEventListener("click", function () { control("clear"); });
  el.btnAutoplay.addEventListener("click", async function () {
    const enabled = el.btnAutoplay.getAttribute("aria-pressed") !== "true";
    try {
      const snap = await api("/api/autoplay", {
        method: "POST",
        body: JSON.stringify({ enabled: enabled }),
      });
      applySnapshot(snap);
      showToast(enabled ? "Autoplay açık" : "Autoplay kapalı", true);
    } catch (err) {
      if (err.status === 401) {
        showLogin();
      } else {
        toastError(err);
      }
    }
  });

  async function postAndApply(path, body) {
    try {
      applySnapshot(await api(path, { method: "POST", body: JSON.stringify(body) }));
      return true;
    } catch (err) {
      if (err.status === 401) {
        showLogin();
      } else {
        toastError(err);
      }
      return false;
    }
  }

  el.btnLoop.addEventListener("click", async function () {
    const mode = LOOP_NEXT[el.btnLoop.dataset.mode || "off"];
    if (await postAndApply("/api/loop", { mode: mode })) {
      showToast(LOOP_TITLES[mode], true);
    }
  });

  el.filterSelect.addEventListener("change", function () {
    postAndApply("/api/filter", { name: el.filterSelect.value });
  });

  function crossfadeText(sec) {
    return sec > 0 ? sec + " sn" : "Kapalı";
  }

  el.crossfade.addEventListener("input", function () {
    el.crossfadeLabel.textContent = crossfadeText(Number(el.crossfade.value));
  });
  el.crossfade.addEventListener("change", function () {
    postAndApply("/api/crossfade", { seconds: Number(el.crossfade.value) });
  });

  // Sürüklerken canlı güncelleme konumu geri almasın; bırakınca atla
  el.seek.addEventListener("input", function () {
    seekHold = true;
    el.seekPos.textContent = formatTime(Number(el.seek.value));
  });
  el.seek.addEventListener("change", async function () {
    await postAndApply("/api/seek", { position: Number(el.seek.value) });
    seekHold = false;
    renderPlayback();
  });

  setInterval(renderPlayback, 500);

  function sendVolume(vol) {
    api("/api/volume", {
      method: "POST",
      body: JSON.stringify({ vol: vol }),
    })
      .then(function (data) {
        if (data && typeof data.volume === "number") {
          lastVolSent = Math.round(data.volume);
          if (document.activeElement !== el.vol) {
            el.vol.value = String(lastVolSent);
            el.volLabel.textContent = String(lastVolSent);
          }
        }
      })
      .catch(toastError);
  }

  el.vol.addEventListener("input", function () {
    const v = Number(el.vol.value);
    el.volLabel.textContent = String(v);
    clearTimeout(volDebounce);
    volDebounce = setTimeout(function () {
      if (v !== lastVolSent) sendVolume(v);
    }, 150);
  });

  /* —— Search —— */
  el.searchBtn.addEventListener("click", doSearch);
  el.searchQuery.addEventListener("keydown", function (e) {
    if (e.key === "Enter") doSearch();
  });

  async function doSearch() {
    const query = (el.searchQuery.value || "").trim();
    if (!query) {
      showToast("Arama metni girin", false);
      return;
    }
    try {
      el.searchBtn.disabled = true;
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({ query: query }),
      });
      renderSearchResults((data && data.results) || []);
    } catch (err) {
      toastError(err);
    } finally {
      el.searchBtn.disabled = false;
    }
  }

  function renderSearchResults(results) {
    el.searchResults.innerHTML = "";
    el.searchEmpty.hidden = results.length > 0;
    results.forEach(function (item, index) {
      const title = item.title || item.name || item.url || "Sonuç " + (index + 1);
      const dur = formatDuration(item.duration);
      const meta = [dur, item.channel || item.uploader || ""].filter(Boolean).join(" · ");
      const li = document.createElement("li");
      li.innerHTML =
        '<span class="idx">' +
        (index + 1) +
        "</span>" +
        '<div class="item-main">' +
        '<div class="item-title">' +
        escapeHtml(title) +
        "</div>" +
        (meta ? '<div class="item-meta">' + escapeHtml(meta) + "</div>" : "") +
        "</div>" +
        '<div class="item-actions"><button type="button" class="btn btn-sm btn-green">Çal</button></div>';
      li.querySelector("button").addEventListener("click", async function () {
        try {
          const snap = await api("/api/search/play", {
            method: "POST",
            body: JSON.stringify({ index: index }),
          });
          applySnapshot(snap);
          showToast("Seçilen sonuç çalınıyor", true);
        } catch (err) {
          toastError(err);
        }
      });
      el.searchResults.appendChild(li);
    });
  }

  /* —— YouTube Music —— */
  const ytm = {
    form: document.getElementById("ytm-form"),
    query: document.getElementById("ytm-query"),
    kind: document.getElementById("ytm-kind"),
    homeBtn: document.getElementById("ytm-home-btn"),
    view: document.getElementById("ytm-view"),
    status: document.getElementById("ytm-status"),
  };
  let ytmLoaded = false;
  let ytmRequest = 0; // eski isteklerin geç gelen sonucunu yok saymak için
  let ytmSaved = null; // albüm/playlist açılınca geri dönülecek liste (DOM, ✓ durumlarıyla)

  function ytmSetStatus(text) {
    ytm.status.textContent = text || "";
    ytm.status.hidden = !text;
  }

  async function ytmLoad(path, render, loadingText) {
    const req = ++ytmRequest;
    ytm.view.innerHTML = "";
    ytmSetStatus(loadingText || "Yükleniyor…");
    try {
      const data = await api(path);
      if (req !== ytmRequest) return;
      ytmSetStatus("");
      render(data);
    } catch (err) {
      if (req !== ytmRequest) return;
      if (err.status === 401) {
        showLogin();
        return;
      }
      ytmSetStatus("Yüklenemedi: " + err.message);
    }
  }

  function ytmButton(label, cls, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-sm " + cls;
    b.textContent = label;
    b.addEventListener("click", function () {
      onClick(b);
    });
    return b;
  }

  function ytmRow(thumbnail, title, meta, actions) {
    const li = document.createElement("li");
    const img = document.createElement("img");
    img.className = "thumb";
    img.alt = "";
    img.loading = "lazy";
    img.referrerPolicy = "no-referrer";
    if (thumbnail) img.src = thumbnail;
    li.appendChild(img);
    const main = document.createElement("div");
    main.className = "item-main";
    main.innerHTML =
      '<div class="item-title">' +
      escapeHtml(title) +
      "</div>" +
      (meta ? '<div class="item-meta">' + escapeHtml(meta) + "</div>" : "");
    li.appendChild(main);
    const act = document.createElement("div");
    act.className = "item-actions";
    actions.forEach(function (a) {
      act.appendChild(a);
    });
    li.appendChild(act);
    return li;
  }

  async function ytmAdd(btn, path, body) {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "…";
    try {
      const snap = await api(path, { method: "POST", body: JSON.stringify(body) });
      applySnapshot(snap);
      btn.textContent = "✓";
      const name = snap.collection ? snap.collection.title + ": " : "";
      showToast(name + (snap.added > 1 ? snap.added + " şarkı kuyruğa eklendi" : "Kuyruğa eklendi"), true);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = label;
      if (err.status === 401) {
        showLogin();
      } else {
        toastError(err);
      }
    }
  }

  function ytmItemRow(item) {
    if (item.kind === "song") {
      const meta = [item.artists, item.album, item.duration].filter(Boolean).join(" · ");
      return ytmRow(item.thumbnail, item.title, meta, [
        ytmButton("+ Ekle", "btn-green", function (b) {
          ytmAdd(b, "/api/queue/add", {
            tracks: [{
              video_id: item.video_id,
              title: item.title,
              artists: item.artists,
              duration: item.duration || "",
              thumbnail: item.thumbnail || "",
            }],
          });
        }),
      ]);
    }
    const fallback = item.kind === "album" ? "Albüm" : "Playlist";
    return ytmRow(item.thumbnail, item.title, item.subtitle || fallback, [
      ytmButton("Aç", "btn-secondary", function () {
        ytmOpen(item.id);
      }),
      ytmButton("+ Tümü", "btn-green", function (b) {
        ytmAdd(b, "/api/queue/add-collection", { id: item.id });
      }),
    ]);
  }

  function ytmList(items) {
    const ul = document.createElement("ul");
    ul.className = "list";
    items.forEach(function (item) {
      ul.appendChild(ytmItemRow(item));
    });
    return ul;
  }

  function ytmRenderHome(data) {
    const sections = (data && data.sections) || [];
    if (!sections.length) {
      ytmSetStatus("Öneri bulunamadı");
      return;
    }
    sections.forEach(function (sec) {
      const h = document.createElement("h3");
      h.className = "ytm-section-title";
      h.textContent = sec.title;
      ytm.view.appendChild(h);
      ytm.view.appendChild(ytmList(sec.items));
    });
  }

  function ytmRenderResults(data) {
    const results = (data && data.results) || [];
    if (!results.length) {
      ytmSetStatus("Sonuç yok");
      return;
    }
    ytm.view.appendChild(ytmList(results));
  }

  function ytmRenderCollection(c) {
    const head = document.createElement("div");
    head.className = "ytm-head";
    head.appendChild(ytmButton("← Geri", "btn-ghost", ytmBack));
    const info = ytmRow(
      c.thumbnail,
      c.title,
      [c.subtitle, c.tracks.length + " şarkı"].filter(Boolean).join(" · "),
      [
        ytmButton("+ Tümünü ekle", "btn-green", function (b) {
          ytmAdd(b, "/api/queue/add-collection", { id: c.id });
        }),
      ]
    );
    info.classList.add("ytm-cover");
    const ul = document.createElement("ul");
    ul.className = "list";
    ul.appendChild(info);
    head.appendChild(ul);
    ytm.view.appendChild(head);
    ytm.view.appendChild(
      ytmList(
        c.tracks.map(function (t) {
          return Object.assign({ kind: "song" }, t);
        })
      )
    );
  }

  function ytmHome() {
    ytmSaved = null;
    ytmLoad("/api/ytm/home", ytmRenderHome, "Ana sayfa yükleniyor…");
  }

  function ytmOpen(id) {
    ytmSaved = document.createDocumentFragment();
    while (ytm.view.firstChild) ytmSaved.appendChild(ytm.view.firstChild);
    ytmLoad("/api/ytm/collection/" + encodeURIComponent(id), ytmRenderCollection);
  }

  function ytmBack() {
    if (!ytmSaved) {
      ytmHome();
      return;
    }
    ytmRequest++; // süren yüklemeyi iptal et
    ytm.view.innerHTML = "";
    ytm.view.appendChild(ytmSaved);
    ytmSaved = null;
    ytmSetStatus("");
  }

  function ytmOnShow() {
    if (!ytmLoaded) {
      ytmLoaded = true;
      ytmHome();
    }
  }

  ytm.homeBtn.addEventListener("click", ytmHome);
  ytm.form.addEventListener("submit", function (e) {
    e.preventDefault();
    const q = (ytm.query.value || "").trim();
    if (!q) return;
    ytmSaved = null;
    ytmLoad(
      "/api/ytm/search?q=" + encodeURIComponent(q) + "&kind=" + encodeURIComponent(ytm.kind.value),
      ytmRenderResults,
      "Aranıyor…"
    );
  });

  /* —— Playlists —— */
  async function loadPlaylists() {
    try {
      const data = await api("/api/playlists");
      renderPlaylists((data && data.playlists) || []);
    } catch (err) {
      if (err.status !== 401) toastError(err);
    }
  }

  function renderPlaylists(list) {
    el.plList.innerHTML = "";
    el.plEmpty.hidden = list.length > 0;
    list.forEach(function (pl) {
      const name = pl.name || "";
      const count = pl.count != null ? pl.count : (pl.songs && pl.songs.length) || 0;
      const li = document.createElement("li");
      li.innerHTML =
        '<div class="item-main">' +
        '<div class="item-title">' +
        escapeHtml(name) +
        "</div>" +
        '<div class="item-meta">' +
        count +
        " şarkı</div></div>" +
        '<div class="item-actions">' +
        '<button type="button" class="btn btn-sm btn-green" data-act="play">Çal</button>' +
        '<button type="button" class="btn btn-sm btn-secondary" data-act="open">Düzenle</button>' +
        '<button type="button" class="btn btn-sm btn-danger" data-act="del">Sil</button>' +
        "</div>";
      li.querySelector('[data-act="play"]').addEventListener("click", async function () {
        try {
          const snap = await api(
            "/api/playlists/" + encodeURIComponent(name) + "/play",
            { method: "POST", body: "{}" }
          );
          applySnapshot(snap);
          showToast("Playlist çalınıyor", true);
        } catch (err) {
          toastError(err);
        }
      });
      li.querySelector('[data-act="open"]').addEventListener("click", async function () {
        try {
          const data = await api("/api/playlists/" + encodeURIComponent(name));
          openPlaylistDetail(name, (data && data.songs) || []);
        } catch (err) {
          toastError(err);
        }
      });
      li.querySelector('[data-act="del"]').addEventListener("click", async function () {
        if (!confirm('"' + name + '" silinsin mi?')) return;
        try {
          await api("/api/playlists/" + encodeURIComponent(name), { method: "DELETE" });
          if (selectedPlaylist === name) closePlaylistDetail();
          showToast("Playlist silindi", true);
          loadPlaylists();
        } catch (err) {
          toastError(err);
        }
      });
      el.plList.appendChild(li);
    });
  }

  function openPlaylistDetail(name, songs) {
    selectedPlaylist = name;
    el.plDetail.hidden = false;
    el.plDetailTitle.textContent = name;
    renderPlaylistSongs(songs || []);
    el.plYoutubeUrl.value = "";
  }

  function closePlaylistDetail() {
    selectedPlaylist = null;
    el.plDetail.hidden = true;
    el.plSongs.innerHTML = "";
    el.plYoutubeUrl.value = "";
  }

  function renderPlaylistSongs(songs) {
    el.plSongs.innerHTML = "";
    const list = Array.isArray(songs) ? songs : [];
    el.plSongsEmpty.hidden = list.length > 0;
    list.forEach(function (song) {
      const label = typeof song === "string" ? song : song.name || song.url || JSON.stringify(song);
      const li = document.createElement("li");
      li.innerHTML =
        '<div class="item-main"><div class="item-title">' +
        escapeHtml(label) +
        '</div></div><div class="item-actions">' +
        '<button type="button" class="btn btn-sm btn-danger">Kaldır</button></div>';
      li.querySelector("button").addEventListener("click", async function () {
        if (!selectedPlaylist) return;
        try {
          const data = await api(
            "/api/playlists/" + encodeURIComponent(selectedPlaylist) + "/remove",
            {
              method: "POST",
              body: JSON.stringify({ song: label }),
            }
          );
          renderPlaylistSongs((data && data.songs) || []);
          loadPlaylists();
        } catch (err) {
          toastError(err);
        }
      });
      el.plSongs.appendChild(li);
    });
  }

  el.plCreate.addEventListener("click", async function () {
    const name = (el.plName.value || "").trim();
    if (!name) {
      showToast("Playlist adı girin", false);
      return;
    }
    try {
      const data = await api("/api/playlists", {
        method: "POST",
        body: JSON.stringify({ name: name }),
      });
      el.plName.value = "";
      showToast("Playlist oluşturuldu", true);
      await loadPlaylists();
      openPlaylistDetail(data.name || name, (data && data.songs) || []);
    } catch (err) {
      toastError(err);
    }
  });

  el.plAdd.addEventListener("click", async function () {
    if (!selectedPlaylist) return;
    const song = (el.plSong.value || "").trim();
    if (!song) {
      showToast("Şarkı URL / adı girin", false);
      return;
    }
    try {
      const data = await api(
        "/api/playlists/" + encodeURIComponent(selectedPlaylist) + "/add",
        {
          method: "POST",
          body: JSON.stringify({ song: song }),
        }
      );
      el.plSong.value = "";
      renderPlaylistSongs((data && data.songs) || []);
      loadPlaylists();
      showToast("Şarkı eklendi", true);
    } catch (err) {
      toastError(err);
    }
  });

  async function importYoutubePlaylist() {
    const url = (el.plYoutubeUrl.value || "").trim();
    if (!selectedPlaylist || !url) {
      showToast("YouTube playlist URL girin", false);
      return;
    }
    try {
      el.plYoutubeImport.disabled = true;
      const data = await api(
        "/api/playlists/" + encodeURIComponent(selectedPlaylist) + "/import-youtube",
        {
          method: "POST",
          body: JSON.stringify({ url: url }),
        }
      );
      el.plYoutubeUrl.value = "";
      renderPlaylistSongs((data && data.songs) || []);
      await loadPlaylists();
      const added = data && data.added != null ? data.added : 0;
      const skipped = data && data.skipped != null ? data.skipped : 0;
      showToast(String(added) + " eklendi, " + String(skipped) + " atlandı", true);
    } catch (err) {
      toastError(err);
    } finally {
      el.plYoutubeImport.disabled = false;
    }
  }

  el.plYoutubeImport.addEventListener("click", importYoutubePlaylist);
  el.plYoutubeUrl.addEventListener("keydown", function (event) {
    if (event.key === "Enter") importYoutubePlaylist();
  });

  el.plDetailClose.addEventListener("click", closePlaylistDetail);
  el.plRefresh.addEventListener("click", loadPlaylists);

  /* —— Library —— */
  async function loadLibrary() {
    try {
      const data = await api("/api/library");
      renderLibrary((data && data.files) || []);
    } catch (err) {
      if (err.status !== 401) toastError(err);
    }
  }

  function renderLibrary(files) {
    el.libList.innerHTML = "";
    el.libEmpty.hidden = files.length > 0;
    files.forEach(function (f) {
      const name = f.name || f;
      const size = typeof f === "object" ? formatSize(f.size) : "";
      const li = document.createElement("li");
      li.innerHTML =
        '<div class="item-main">' +
        '<div class="item-title">' +
        escapeHtml(name) +
        "</div>" +
        (size ? '<div class="item-meta">' + escapeHtml(size) + "</div>" : "") +
        '</div><div class="item-actions">' +
        '<button type="button" class="btn btn-sm btn-green">Çal</button></div>';
      li.querySelector("button").addEventListener("click", async function () {
        try {
          const snap = await api("/api/library/play", {
            method: "POST",
            body: JSON.stringify({ name: name }),
          });
          applySnapshot(snap);
          showToast("Dosya çalınıyor", true);
        } catch (err) {
          toastError(err);
        }
      });
      el.libList.appendChild(li);
    });
  }

  el.libRefresh.addEventListener("click", loadLibrary);

  /* —— Boot —— */
  (async function init() {
    const ok = await probeAuth();
    if (ok) {
      await enterApp();
    } else {
      showLogin();
      el.token.focus();
    }
  })();
})();
