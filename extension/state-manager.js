(function bootstrapStateManager() {
  class BiliSubStateManager {
    constructor() {
      this.serverBaseUrl = "http://127.0.0.1:8765";
      this.sessionId = null;
      this.videoId = null;
      this.pageUrl = location.href;
      this.currentEpoch = 0;
      this.playbackRate = 1;
      this.currentTime = 0;
      this.bufferedUntil = 0;
      this.status = "idle";
      this.statusDetail = "Waiting for subtitle session";
      this.source = null;
      this.subtitles = [];
      this.lastError = null;
      this.sourceLocked = false;
    }

    setSession(data) {
      this.sessionId = data?.session_id || null;
      this.currentEpoch = data?.current_epoch || 0;
      if (typeof data?.buffered_until === "number") {
        this.bufferedUntil = data.buffered_until;
      }
      if (data?.status) {
        this.status = data.status;
      }
      if (data?.status_detail) {
        this.statusDetail = data.status_detail;
      }
    }

    resetForSeek(targetTime) {
      this.currentTime = targetTime;
      this.bufferedUntil = targetTime;
      this.subtitles = this.subtitles.filter((item) => item.end >= targetTime - 2 && item.start <= targetTime + 35);
      this.currentEpoch += 1;
      this.status = "seeking";
      this.statusDetail = `Seeking to ${targetTime.toFixed(1)}s and refreshing subtitles`;
    }

    setServerStatus(data) {
      if (!data) {
        return;
      }

      this.currentEpoch = data.current_epoch ?? this.currentEpoch;
      this.bufferedUntil = data.buffered_until ?? this.bufferedUntil;
      this.status = data.status || this.status;
      this.statusDetail = data.status_detail || this.statusDetail;
      this.lastError = data.last_error || null;
    }

    setSubtitles(items, epoch) {
      if (typeof epoch === "number" && epoch !== this.currentEpoch) {
        return;
      }
      this.subtitles = Array.isArray(items) ? items.slice().sort((left, right) => left.start - right.start) : [];
    }

    setSource(source) {
      if (source?.url) {
        this.source = source;
        this.sourceLocked = true;
        return;
      }

      if (!this.sourceLocked) {
        this.source = null;
      }
    }

    getLeadSeconds() {
      return (this.bufferedUntil || 0) - (this.currentTime || 0);
    }

    getCurrentSubtitle() {
      const now = this.currentTime;
      const active = this.subtitles.find((item) => now >= item.start && now <= item.end);
      if (active) {
        return active;
      }
      return this.subtitles.find((item) => item.start >= now && item.start - now <= 0.18) || null;
    }

    getStatusLabel() {
      if (this.lastError) {
        return `Error: ${this.lastError}`;
      }

      const lead = this.getLeadSeconds();
      const safety = this.getSafetyWindow();

      if (!this.source && this.bufferedUntil <= 0) {
        return "Detecting original audio source";
      }
      if (this.status === "loading-source") {
        return "Loading original audio source";
      }
      if (this.status === "buffering") {
        return this.statusDetail || "Building subtitle buffer";
      }
      if (this.status === "ready" || this.status === "playing" || this.status === "paused") {
        if (lead <= 0) {
          return "Subtitle buffer exhausted";
        }
        if (lead < Math.min(5, safety / 2)) {
          return "Low subtitle buffer";
        }
        if (lead < safety) {
          return "Catching up";
        }
        return "";
      }
      if (this.status === "seeking") {
        return this.statusDetail;
      }
      if (lead <= 0) {
        return "Subtitle buffer exhausted";
      }
      if (lead < Math.min(5, safety / 2)) {
        return "Low subtitle buffer";
      }
      if (lead < safety) {
        return "Catching up";
      }
      return "";
    }

    getSafetyWindow() {
      return Math.min(20, Math.max(10, this.playbackRate * 6));
    }
  }

  window.BiliSubStateManager = BiliSubStateManager;
})();
