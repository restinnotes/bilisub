(function bootstrapOverlay() {
  class SubtitleOverlay {
    constructor() {
      this.root = document.createElement("div");
      this.root.className = "bilisub-overlay-root";

      this.box = document.createElement("div");
      this.box.className = "bilisub-overlay-box";

      this.subtitleText = document.createElement("div");
      this.subtitleText.className = "bilisub-subtitle-text bilisub-hidden";

      this.statusPill = document.createElement("div");
      this.statusPill.className = "bilisub-status-pill";
      this.statusPill.textContent = "Waiting for video";

      this.box.appendChild(this.statusPill);
      this.box.appendChild(this.subtitleText);
      this.root.appendChild(this.box);
      document.documentElement.appendChild(this.root);

      this.video = null;
      this.rafId = null;
      this.enabled = true;
      this.mountNode = null;
      this.ensureLoop();
    }

    attachToVideo(video) {
      this.video = video || null;
      this.syncMountNode();
      this.ensureLoop();
      this.position();
    }

    setSubtitle(text) {
      if (!text) {
        this.subtitleText.textContent = "";
        this.subtitleText.classList.add("bilisub-hidden");
        return;
      }

      this.subtitleText.textContent = text;
      this.subtitleText.classList.remove("bilisub-hidden");
    }

    setStatus(text) {
      this.statusPill.textContent = text || "";
      this.statusPill.classList.toggle("bilisub-hidden", !text);
    }

    setEnabled(enabled) {
      this.enabled = Boolean(enabled);
      this.root.classList.toggle("bilisub-overlay-disabled", !this.enabled);
      if (!this.enabled) {
        this.setSubtitle("");
        this.setStatus("");
      }
    }

    ensureLoop() {
      if (this.rafId) {
        return;
      }

      const tick = () => {
        this.position();
        this.rafId = window.requestAnimationFrame(tick);
      };

      this.rafId = window.requestAnimationFrame(tick);
    }

    position() {
      if (!this.enabled || !this.video || !document.contains(this.video)) {
        return;
      }

      this.syncMountNode();

      const rect = this.video.getBoundingClientRect();
      if (!rect.width || !rect.height) {
        return;
      }

      const centerX = rect.left + rect.width / 2;
      const bottomOffset = Math.max(18, rect.height * 0.028) + Math.max(8, rect.height * 0.01);
      const viewportBottom = Math.max(0, window.innerHeight - rect.bottom);
      const horizontalPadding = Math.max(24, rect.width * 0.045);
      const overlayWidth = Math.max(320, rect.width - horizontalPadding * 2);

      this.box.style.left = `${centerX}px`;
      this.box.style.bottom = `${viewportBottom + bottomOffset}px`;
      this.box.style.width = `${overlayWidth}px`;
      this.subtitleText.style.fontSize = `${Math.max(18, Math.min(34, rect.width * 0.034))}px`;
    }

    syncMountNode() {
      const fullscreenRoot = document.fullscreenElement;
      const preferredMount = fullscreenRoot && fullscreenRoot.contains(this.video)
        ? fullscreenRoot
        : document.documentElement;

      if (this.mountNode === preferredMount && preferredMount.contains(this.root)) {
        return;
      }

      this.mountNode = preferredMount;
      this.mountNode.appendChild(this.root);
    }
  }

  window.BiliSubOverlay = SubtitleOverlay;
})();
