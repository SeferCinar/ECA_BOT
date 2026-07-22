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
  }

  function applyNow(now) {
    if (!now || !now.name) {
      el.npTitle.textContent = "Çalmıyor";
      el.npSub.textContent = "—";
      el.playerNowTitle.textContent = "Çalmıyor";
      el.playerNowMeta.textContent = "—";
      return;
    }
    const src = now.is_stream ? "Stream" : "Yerel";
    const user = now.user || "—";
    el.npTitle.textContent = now.name;
    el.npSub.textContent = src + " · " + user;
    el.playerNowTitle.textContent = now.name;
    el.playerNowMeta.textContent =
      src + " · İsteyen: " + user + (now.webpage_url ? " · " + now.webpage_url : "");
  }

  function applyQueue(queue) {
    const items = Array.isArray(queue) ? queue : [];
    el.queueList.innerHTML = "";
    el.queueCount.textContent = String(items.length);
    el.queueEmpty.hidden = items.length > 0;
    items.forEach(function (song, i) {
      const li = document.createElement("li");
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
        "</div>";
      el.queueList.appendChild(li);
    });
  }

  function applySnapshot(snap) {
    if (!snap || snap.error) return;
    if (snap.status) applyStatus(snap.status);
    applyNow(snap.now);
    applyQueue(snap.queue);
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
  }

  function closePlaylistDetail() {
    selectedPlaylist = null;
    el.plDetail.hidden = true;
    el.plSongs.innerHTML = "";
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
