(function bilisubPageBridge() {
  const EVENT_NAME = "bilisub:playinfo";
  const REQUEST_EVENT = "bilisub:request-playinfo";
  let refreshTimer = null;

  function emitPayload() {
    const video = document.querySelector("video");
    const payload = {
      playInfo: readPlayInfo(),
      initialState: window.__INITIAL_STATE__ || null,
      location: location.href,
      resources: summarizeResources(),
      video: video
        ? {
            currentSrc: video.currentSrc || video.src || null,
            src: video.src || null
          }
        : null
    };

    window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: payload }));
    window.postMessage({ source: "bilisub-page", type: EVENT_NAME, payload }, "*");
  }

  function readPlayInfo() {
    if (window.__playinfo__) {
      return window.__playinfo__;
    }

    const scripts = Array.from(document.scripts || []);
    for (const script of scripts) {
      const content = script.textContent || "";
      const marker = "window.__playinfo__=";
      const startIndex = content.indexOf(marker);
      if (startIndex === -1) {
        continue;
      }

      const candidate = content.slice(startIndex + marker.length);
      const jsonText = extractAssignedJson(candidate);
      if (!jsonText) {
        continue;
      }
      try {
        return JSON.parse(jsonText);
      } catch {
        continue;
      }
    }

    return null;
  }

  function extractAssignedJson(content) {
    let depth = 0;
    let inString = false;
    let stringQuote = "";
    let escaped = false;
    let started = false;
    let startOffset = -1;

    for (let index = 0; index < content.length; index += 1) {
      const char = content[index];
      if (!started) {
        if (char === "{" || char === "[") {
          started = true;
          depth = 1;
          startOffset = index;
        } else {
          continue;
        }
      } else if (inString) {
        if (escaped) {
          escaped = false;
        } else if (char === "\\") {
          escaped = true;
        } else if (char === stringQuote) {
          inString = false;
          stringQuote = "";
        }
      } else if (char === '"' || char === "'") {
        inString = true;
        stringQuote = char;
      } else if (char === "{" || char === "[") {
        depth += 1;
      } else if (char === "}" || char === "]") {
        depth -= 1;
        if (depth === 0) {
          return content.slice(startOffset, index + 1).trim();
        }
      }
    }

    return null;
  }

  function summarizeResources() {
    return performance
      .getEntriesByType("resource")
      .filter((entry) => /bilivideo|m4s|\.mp4|\.mp3/i.test(entry.name))
      .slice(-20)
      .map((entry) => ({
        name: entry.name,
        initiatorType: entry.initiatorType,
        duration: entry.duration
      }));
  }

  function handleRefreshRequest(event) {
    const data = event?.data || null;
    if (event?.type === "message") {
      if (event.source !== window || !data || data.source !== "bilisub-content" || data.type !== REQUEST_EVENT) {
        return;
      }
    }
    emitPayload();
  }

  window.addEventListener(REQUEST_EVENT, handleRefreshRequest);
  window.addEventListener("message", handleRefreshRequest);

  refreshTimer = window.setInterval(() => {
    const playInfo = readPlayInfo();
    if (playInfo?.data?.dash || playInfo?.dash) {
      emitPayload();
      window.clearInterval(refreshTimer);
      refreshTimer = null;
      return;
    }
    emitPayload();
  }, 1500);

  emitPayload();
})();
