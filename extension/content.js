(function bootstrapContentScript() {
  const overlay = new window.BiliSubOverlay();
  const state = new window.BiliSubStateManager();
  const sourceDetector = new window.BiliSourceDetector();

  const STORAGE_KEY = "bilisub.aiSubtitleEnabled";

  let activeVideo = null;
  let routeWatcher = null;
  let pollTimer = null;
  let subtitleTimer = null;
  let sourceUnsubscribe = null;
  let bindToken = 0;
  let statusRequestId = 0;
  let subtitleRequestId = 0;
  let seekSerial = 0;
  let statusInFlight = false;
  let subtitlesInFlight = false;
  let lastLoadedSourceUrl = null;
  let aiSubtitleEnabled = false;
  let toggleButton = null;
  let toggleMountTimer = null;

  init();

  async function init() {
    aiSubtitleEnabled = await loadEnabledPreference();
    overlay.setEnabled(aiSubtitleEnabled);
    sourceDetector.injectBridge();
    sourceUnsubscribe = sourceDetector.onChange(handleSourceDetected);
    watchRouteChanges();
    startToggleMountLoop();
    bindWhenReady();
    window.addEventListener("beforeunload", endSession);
    document.addEventListener("fullscreenchange", onFullscreenChange);
  }

  function onFullscreenChange() {
    ensureToggleButtonMounted();
    if (activeVideo) {
      overlay.attachToVideo(activeVideo);
    }
  }

  async function loadEnabledPreference() {
    return new Promise((resolve) => {
      try {
        chrome.storage.local.get([STORAGE_KEY], (result) => {
          if (chrome.runtime.lastError) {
            resolve(false);
            return;
          }
          resolve(Boolean(result?.[STORAGE_KEY]));
        });
      } catch {
        resolve(false);
      }
    });
  }

  function saveEnabledPreference(value) {
    try {
      chrome.storage.local.set({ [STORAGE_KEY]: Boolean(value) });
    } catch {}
  }

  function startToggleMountLoop() {
    window.clearInterval(toggleMountTimer);
    toggleMountTimer = window.setInterval(ensureToggleButtonMounted, 1000);
    ensureToggleButtonMounted();
  }

  function ensureToggleButtonMounted() {
    if (!toggleButton) {
      toggleButton = document.createElement("button");
      toggleButton.type = "button";
      toggleButton.className = "bilisub-toggle-button";
      toggleButton.addEventListener("click", onToggleClick);
    }

    syncToggleButton();

    const target = findToggleMountTarget();
    if (!target || target.contains(toggleButton)) {
      return;
    }
    target.appendChild(toggleButton);
  }

  function findToggleMountTarget() {
    const root = document.fullscreenElement || document;
    const selectors = [
      ".bpx-player-control-bottom-right",
      ".bpx-player-ctrl-right",
      ".squirtle-controller-wrap .squirtle-video-control-wrap .squirtle-video-control-right",
      ".bilibili-player-video-control-right",
      "#bilibili-player .bpx-player-control-wrap"
    ];

    for (const selector of selectors) {
      const match = root.querySelector(selector);
      if (match) {
        return match;
      }
    }

    return root.querySelector("#bilibili-player") || root.querySelector("#playerWrap");
  }

  function syncToggleButton() {
    if (!toggleButton) {
      return;
    }
    toggleButton.textContent = "AI字幕";
    toggleButton.classList.toggle("is-active", aiSubtitleEnabled);
    toggleButton.setAttribute("aria-pressed", aiSubtitleEnabled ? "true" : "false");
    toggleButton.title = aiSubtitleEnabled ? "关闭 AI字幕" : "开启 AI字幕";
  }

  async function onToggleClick() {
    aiSubtitleEnabled = !aiSubtitleEnabled;
    saveEnabledPreference(aiSubtitleEnabled);
    syncToggleButton();
    overlay.setEnabled(aiSubtitleEnabled);

    if (!aiSubtitleEnabled) {
      stopPolling();
      overlay.setSubtitle("");
      overlay.setStatus("");
      await endSession();
      state.sessionId = null;
      state.subtitles = [];
      state.lastError = null;
      state.currentEpoch = 0;
      state.bufferedUntil = state.currentTime || 0;
      render();
      return;
    }

    if (!activeVideo) {
      return;
    }

    state.currentTime = activeVideo.currentTime || 0;
    await ensureSession();
    startPolling();
    sourceDetector.requestRefresh();
    render();
  }

  async function bindWhenReady() {
    const token = ++bindToken;
    const video = await waitForVideoElement();
    if (token !== bindToken) {
      return;
    }

    if (activeVideo === video) {
      ensureToggleButtonMounted();
      return;
    }

    if (activeVideo) {
      detachVideoListeners(activeVideo);
    }

    activeVideo = video;
    overlay.attachToVideo(video);
    overlay.setEnabled(aiSubtitleEnabled);
    state.videoId = extractVideoId();
    state.pageUrl = location.href;
    state.currentTime = video.currentTime || 0;
    state.playbackRate = video.playbackRate || 1;
    attachVideoListeners(video);
    ensureToggleButtonMounted();

    if (!aiSubtitleEnabled) {
      overlay.setSubtitle("");
      overlay.setStatus("");
      return;
    }

    overlay.setStatus("Creating subtitle session");
    await ensureSession();
    startPolling();
    sourceDetector.requestRefresh();
  }

  function waitForVideoElement() {
    return new Promise((resolve) => {
      const readyVideo = document.querySelector("video");
      if (readyVideo) {
        resolve(readyVideo);
        return;
      }

      const observer = new MutationObserver(() => {
        const video = document.querySelector("video");
        if (video) {
          observer.disconnect();
          resolve(video);
        }
      });

      observer.observe(document.documentElement, {
        childList: true,
        subtree: true
      });
    });
  }

  async function ensureSession() {
    if (!aiSubtitleEnabled || state.sessionId) {
      return;
    }

    const response = await callServer("/session/start", "POST", {
      page_url: location.href,
      video_id: state.videoId
    });
    state.setSession(response);
  }

  async function handleSourceDetected(sourcePayload) {
    const hasAudioSource = Boolean(sourcePayload?.audioSource?.url);
    const nextSourceUrl = hasAudioSource ? sourcePayload.audioSource.url : null;
    if (hasAudioSource) {
      state.setSource(sourcePayload.audioSource);
    } else if (!state.source) {
      state.setSource(null);
    }
    if (!aiSubtitleEnabled || !state.sessionId) {
      return;
    }

    if (!hasAudioSource) {
      if (!state.source) {
        overlay.setStatus(sourcePayload?.fallback?.reason || "Original audio source not found");
      }
      return;
    }

    if (nextSourceUrl && nextSourceUrl === lastLoadedSourceUrl) {
      render();
      return;
    }

    state.status = "loading-source";
    overlay.setStatus("Loading original audio source");

    try {
      const response = await callServer("/session/load-source", "POST", {
        session_id: state.sessionId,
        audio_source: {
          url: sourcePayload.audioSource.url,
          backup_urls: sourcePayload.audioSource.backup_urls || [],
          type: sourcePayload.sourceType || "direct",
          headers: sourcePayload.audioSource.headers || {},
          meta: sourcePayload.pageMeta || {}
        }
      });
      lastLoadedSourceUrl = nextSourceUrl;
      state.setServerStatus(response);
      render();
    } catch (error) {
      state.lastError = error.message;
      render();
    }
  }

  function attachVideoListeners(video) {
    video.__bilisubHandlers = {
      play: () => onPlay(),
      pause: () => onPause(),
      seeking: () => onSeeking(),
      seeked: () => onSeeked(),
      ratechange: () => onRateChange(),
      timeupdate: () => onTimeUpdate()
    };

    Object.entries(video.__bilisubHandlers).forEach(([eventName, handler]) => {
      video.addEventListener(eventName, handler);
    });
  }

  function detachVideoListeners(video) {
    const handlers = video.__bilisubHandlers || {};
    Object.entries(handlers).forEach(([eventName, handler]) => {
      video.removeEventListener(eventName, handler);
    });
    delete video.__bilisubHandlers;
  }

  async function onPlay() {
    if (!aiSubtitleEnabled || !state.sessionId || !activeVideo) {
      return;
    }
    state.currentTime = activeVideo.currentTime;
    await callServer("/session/play", "POST", {
      session_id: state.sessionId,
      current_time: activeVideo.currentTime
    }).catch((error) => {
      state.lastError = error.message;
    });
    render();
  }

  async function onPause() {
    if (!aiSubtitleEnabled || !state.sessionId || !activeVideo) {
      return;
    }
    state.currentTime = activeVideo.currentTime;
    await callServer("/session/pause", "POST", {
      session_id: state.sessionId,
      current_time: activeVideo.currentTime
    }).catch((error) => {
      state.lastError = error.message;
    });
    render();
  }

  function onSeeking() {
    if (!aiSubtitleEnabled || !activeVideo) {
      return;
    }
    state.resetForSeek(activeVideo.currentTime);
    render();
  }

  async function onSeeked() {
    if (!aiSubtitleEnabled || !state.sessionId || !activeVideo) {
      return;
    }
    const currentSeekSerial = ++seekSerial;
    await callServer("/session/seek", "POST", {
      session_id: state.sessionId,
      target_time: activeVideo.currentTime
    }).then((response) => {
      state.setServerStatus(response);
    }).catch((error) => {
      state.lastError = error.message;
    });
    statusRequestId += 1;
    subtitleRequestId += 1;
    statusInFlight = false;
    subtitlesInFlight = false;
    await Promise.all([
      fetchStatus({ force: true }),
      fetchSubtitles({ force: true, seekSerial: currentSeekSerial })
    ]);
    render();
  }

  async function onRateChange() {
    if (!aiSubtitleEnabled || !state.sessionId || !activeVideo) {
      return;
    }
    state.playbackRate = activeVideo.playbackRate || 1;
    await callServer("/session/rate", "POST", {
      session_id: state.sessionId,
      playback_rate: state.playbackRate
    }).catch((error) => {
      state.lastError = error.message;
    });
    render();
  }

  function onTimeUpdate() {
    if (!activeVideo) {
      return;
    }
    state.currentTime = activeVideo.currentTime;
    render();
  }

  function startPolling() {
    if (!aiSubtitleEnabled) {
      return;
    }

    window.clearInterval(pollTimer);
    window.clearInterval(subtitleTimer);
    statusInFlight = false;
    subtitlesInFlight = false;

    pollTimer = window.setInterval(fetchStatus, 1200);
    subtitleTimer = window.setInterval(fetchSubtitles, 900);
    fetchStatus();
    fetchSubtitles();
  }

  function stopPolling() {
    window.clearInterval(pollTimer);
    window.clearInterval(subtitleTimer);
    pollTimer = null;
    subtitleTimer = null;
    statusInFlight = false;
    subtitlesInFlight = false;
  }

  async function fetchStatus(options = {}) {
    if (!aiSubtitleEnabled || !state.sessionId || !activeVideo || (statusInFlight && !options.force)) {
      return;
    }
    if (!state.source) {
      sourceDetector.requestRefresh();
    }
    statusInFlight = true;
    const requestId = ++statusRequestId;
    const localEpoch = state.currentEpoch;
    state.currentTime = activeVideo.currentTime;
    const status = await callServer(`/session/status?session_id=${encodeURIComponent(state.sessionId)}&current_time=${encodeURIComponent(activeVideo.currentTime)}`, "GET").catch((error) => {
      state.lastError = error.message;
      return null;
    });
    statusInFlight = false;
    if (!status || requestId !== statusRequestId) {
      render();
      return;
    }
    if (typeof status.current_epoch === "number" && status.current_epoch < localEpoch) {
      render();
      return;
    }
    state.setServerStatus(status);
    render();
  }

  async function fetchSubtitles(options = {}) {
    if (!aiSubtitleEnabled || !state.sessionId || !activeVideo || (subtitlesInFlight && !options.force)) {
      return;
    }
    if (!state.source) {
      sourceDetector.requestRefresh();
    }
    state.currentTime = activeVideo.currentTime;
    subtitlesInFlight = true;
    const requestId = ++subtitleRequestId;
    const localEpoch = state.currentEpoch;
    const requestTime = activeVideo.currentTime;
    const data = await callServer(`/subtitles?session_id=${encodeURIComponent(state.sessionId)}&current_time=${encodeURIComponent(requestTime)}&window_after=35`, "GET").catch((error) => {
      state.lastError = error.message;
      return null;
    });
    subtitlesInFlight = false;
    if (!data) {
      render();
      return;
    }
    if (requestId !== subtitleRequestId) {
      render();
      return;
    }
    if (typeof options.seekSerial === "number" && options.seekSerial !== seekSerial) {
      render();
      return;
    }
    if (typeof data.current_epoch === "number" && data.current_epoch < localEpoch) {
      render();
      return;
    }
    if (typeof data.current_epoch === "number") {
      state.currentEpoch = data.current_epoch;
    }
    state.setSubtitles(data.items || [], data.current_epoch);
    state.bufferedUntil = data.buffered_until ?? state.bufferedUntil;
    render();
  }

  function render() {
    if (!aiSubtitleEnabled) {
      overlay.setSubtitle("");
      overlay.setStatus("");
      return;
    }

    const current = state.getCurrentSubtitle();
    overlay.setSubtitle(current?.text || "");
    overlay.setStatus(state.getStatusLabel());
  }

  function watchRouteChanges() {
    let lastHref = location.href;
    routeWatcher = window.setInterval(() => {
      if (location.href === lastHref) {
        return;
      }

      lastHref = location.href;
      resetForRouteChange();
      bindWhenReady();
    }, 500);
  }

  async function resetForRouteChange() {
    stopPolling();
    if (activeVideo) {
      detachVideoListeners(activeVideo);
    }
    activeVideo = null;
    lastLoadedSourceUrl = null;
    await endSession();
    state.sessionId = null;
    state.subtitles = [];
    state.source = null;
    state.sourceLocked = false;
    state.lastError = null;
    state.currentEpoch = 0;
    overlay.setSubtitle("");
    overlay.setStatus("");
    ensureToggleButtonMounted();
  }

  async function endSession() {
    if (!state.sessionId) {
      return;
    }
    const sessionId = state.sessionId;
    state.sessionId = null;
    await callServer("/session/end", "POST", { session_id: sessionId }).catch(() => null);
  }

  function extractVideoId() {
    const match = location.pathname.match(/\/video\/([^/?]+)/);
    return match ? match[1] : location.pathname;
  }

  function callServer(path, method, body) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        {
          type: "bilisub:api-request",
          payload: {
            path,
            method,
            body,
            baseUrl: state.serverBaseUrl
          }
        },
        (response) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }
          if (!response?.ok) {
            reject(new Error(response?.error || "Unknown local server error"));
            return;
          }
          resolve(response.data);
        }
      );
    });
  }
})();
