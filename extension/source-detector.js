(function bootstrapSourceDetector() {
  class BiliSourceDetector {
    constructor() {
      this.listeners = new Set();
      this.bridgeInjected = false;
      this.latestPayload = null;
      this.boundBridgeHandler = this.onBridgeEvent.bind(this);
      this.boundWindowMessageHandler = this.onWindowMessage.bind(this);
      window.addEventListener("bilisub:playinfo", this.boundBridgeHandler);
      window.addEventListener("message", this.boundWindowMessageHandler);
    }

    destroy() {
      window.removeEventListener("bilisub:playinfo", this.boundBridgeHandler);
      window.removeEventListener("message", this.boundWindowMessageHandler);
      this.listeners.clear();
    }

    onChange(listener) {
      this.listeners.add(listener);
      if (this.latestPayload) {
        listener(this.latestPayload);
      }
      return () => this.listeners.delete(listener);
    }

    injectBridge() {
      if (this.bridgeInjected) {
        this.requestRefresh();
        return;
      }

      const script = document.createElement("script");
      script.src = chrome.runtime.getURL("page-bridge.js");
      script.async = false;
      script.onload = () => script.remove();
      (document.head || document.documentElement).appendChild(script);
      this.bridgeInjected = true;
      window.setTimeout(() => this.requestRefresh(), 0);
    }

    requestRefresh() {
      window.dispatchEvent(new CustomEvent("bilisub:request-playinfo"));
      window.postMessage({ source: "bilisub-content", type: "bilisub:request-playinfo" }, "*");
    }

    onBridgeEvent(event) {
      this.consumePayload(event.detail || null);
    }

    onWindowMessage(event) {
      if (event.source !== window) {
        return;
      }
      const data = event.data || null;
      if (!data || data.source !== "bilisub-page" || data.type !== "bilisub:playinfo") {
        return;
      }
      this.consumePayload(data.payload || null);
    }

    consumePayload(detail) {
      const source = this.normalize(detail || {});
      this.latestPayload = source;
      this.listeners.forEach((listener) => {
        listener(source);
      });
    }

    normalize(detail) {
      const playInfo = detail.playInfo || {};
      const initialState = detail.initialState || {};
      const dash = playInfo?.data?.dash || playInfo?.dash || null;
      const audios = Array.isArray(dash?.audio) ? dash.audio : [];
      const videos = Array.isArray(dash?.video) ? dash.video : [];
      const currentVideoAudio = findAudioFromVideo(detail.video || null);
      const resourceAudio = findAudioFromResources(detail.resources || []);
      const bestAudio = audios
        .slice()
        .sort((left, right) => (right.bandwidth || 0) - (left.bandwidth || 0))[0] || resourceAudio || currentVideoAudio || null;
      const bestVideo = videos
        .slice()
        .sort((left, right) => (right.bandwidth || 0) - (left.bandwidth || 0))[0] || null;

      const headers = {
        Referer: location.href,
        Origin: location.origin,
        "User-Agent": navigator.userAgent,
        "Accept-Language": navigator.language || "zh-CN,zh;q=0.9"
      };

      return {
        sourceType: bestAudio ? "direct" : "fallback",
        audioSource: bestAudio
          ? {
              url: bestAudio.baseUrl || bestAudio.base_url || bestAudio.url,
              backup_urls: bestAudio.backupUrl || bestAudio.backup_url || [],
              codec: bestAudio.codecs || null,
              bandwidth: bestAudio.bandwidth || null,
              headers
            }
          : null,
        videoSource: bestVideo
          ? {
              url: bestVideo.baseUrl || bestVideo.base_url || bestVideo.url,
              headers
            }
          : null,
        pageMeta: {
          bvid: initialState?.bvid || null,
          aid: initialState?.aid || null,
          cid: initialState?.cidMap ? extractFirstCid(initialState.cidMap) : initialState?.cid || null,
          title: initialState?.videoData?.title || document.title,
          playInfoAvailable: Boolean(detail.playInfo)
        },
        fallback: {
          captureStreamSupported: Boolean(document.querySelector("video")?.captureStream),
          reason: bestAudio ? null : "Failed to find audio URL in page playinfo"
        },
        raw: detail
      };
    }
  }

  function extractFirstCid(cidMap) {
    const firstKey = Object.keys(cidMap || {})[0];
    const firstEntry = firstKey ? cidMap[firstKey] : null;
    return firstEntry?.cid || null;
  }

  function findAudioFromResources(resources) {
    if (!Array.isArray(resources)) {
      return null;
    }

    const candidates = resources
      .filter((entry) => isLikelyAudioResource(entry?.name || ""))
      .slice()
      .reverse();

    const audioEntry = candidates[0] || null;
    if (!audioEntry?.name) {
      return null;
    }

    return {
      url: audioEntry.name,
      backup_url: [],
      bandwidth: 0,
      codecs: null
    };
  }

  function isLikelyAudioResource(url) {
    if (!url) {
      return false;
    }

    const normalized = String(url).toLowerCase();
    const looksAudio = /audio|mime_type=audio|type=audio|\.mp3|\.m4a/.test(normalized);
    const genericM4s = /\.m4s/.test(normalized);
    const looksVideo = /mime_type=video|type=video|video|avc|hev|h264|h265/.test(normalized);

    if (looksAudio) {
      return true;
    }

    return genericM4s && !looksVideo;
  }

  function findAudioFromVideo(video) {
    const currentSrc = video?.currentSrc || video?.src || null;
    if (!currentSrc || currentSrc.startsWith("blob:")) {
      return null;
    }

    return {
      url: currentSrc,
      backup_url: [],
      bandwidth: 0,
      codecs: null
    };
  }

  window.BiliSourceDetector = BiliSourceDetector;
})();
