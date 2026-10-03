import { formatTime } from "./utils.js";

export class SynchrobookAudioPlayer {
  constructor(elements, { onFrame, onPersist }) {
    this.audio = elements.audio;
    this.playButton = elements.playButton;
    this.seekBar = elements.seekBar;
    this.currentTime = elements.currentTime;
    this.duration = elements.duration;
    this.speed = elements.speed;
    this.onFrame = onFrame;
    this.onPersist = onPersist;
    this.frame = null;
    this.loaded = false;
    this.loading = false;
    this.requestedPlaybackRate = 1;
    this.playButton.addEventListener("click", () => this.toggle());
    elements.back.addEventListener("click", () => this.seek(this.audio.currentTime - 10, true));
    elements.forward.addEventListener("click", () => this.seek(this.audio.currentTime + 10, true));
    this.seekBar.addEventListener("input", () => this.seek(Number(this.seekBar.value), false));
    this.seekBar.addEventListener("change", () => this.onPersist());
    this.speed.addEventListener("change", () => {
      this.setPlaybackRate(this.speed.value);
      this.update();
      this.onPersist();
    });
    this.audio.addEventListener("ratechange", () => {
      const actualRate = this.actualPlaybackRate();
      if (!this.loading) this.requestedPlaybackRate = actualRate;
      this.speed.value = String(actualRate);
      this.update();
    });
    this.audio.addEventListener("loadedmetadata", () => this.updateDuration());
    this.audio.addEventListener("durationchange", () => this.updateDuration());
    this.audio.addEventListener("play", () => { this.playButton.firstElementChild.textContent = "❚❚"; this.loop(); });
    this.audio.addEventListener("pause", () => { this.playButton.firstElementChild.textContent = "▶"; this.stopLoop(); this.onPersist(); });
    this.audio.addEventListener("ended", () => { this.stopLoop(); this.onPersist(); });
    this.audio.addEventListener("seeked", () => { this.update(); this.onPersist(); });
  }

  load(url, { timestamp = 0, speed = 1 } = {}) {
    this.stopLoop();
    this.loading = true;
    this.audio.src = url;
    this.setPlaybackRate(speed);
    this.audio.addEventListener("loadedmetadata", () => {
      // Calling audio.load() may restore playbackRate to defaultPlaybackRate
      // in some browsers, so enforce the saved rate once metadata is ready.
      this.setPlaybackRate(this.requestedPlaybackRate);
      this.loading = false;
      this.audio.currentTime = Math.min(Math.max(0, Number(timestamp) || 0), this.audio.duration || Infinity);
      this.update();
    }, { once: true });
    this.loaded = true;
    for (const control of [this.playButton, this.seekBar, this.speed]) control.disabled = false;
    this.audio.load();
  }

  actualPlaybackRate() {
    const rate = Number(this.audio.playbackRate);
    return Number.isFinite(rate) && rate > 0 ? rate : 1;
  }

  setPlaybackRate(value) {
    const rate = Number(value);
    this.requestedPlaybackRate = Number.isFinite(rate) && rate > 0 ? rate : 1;
    this.audio.defaultPlaybackRate = this.requestedPlaybackRate;
    this.audio.playbackRate = this.requestedPlaybackRate;
    this.speed.value = String(this.requestedPlaybackRate);
  }

  unload() {
    this.stopLoop();
    this.loading = false;
    this.audio.pause();
    this.audio.removeAttribute("src");
    this.audio.load();
    this.loaded = false;
    for (const control of [this.playButton, this.seekBar, this.speed]) control.disabled = true;
    this.seekBar.value = "0";
    this.seekBar.max = "0";
    this.seekBar.style.setProperty("--synchrobook-seek-progress", "0%");
    this.currentTime.textContent = "0:00";
    this.duration.textContent = "0:00";
    if (this.playButton.firstElementChild) this.playButton.firstElementChild.textContent = "▶";
  }

  async toggle() {
    if (!this.loaded) return;
    if (this.audio.paused) await this.audio.play();
    else this.audio.pause();
  }

  seek(timestamp, persist = true) {
    if (!this.loaded) return;
    this.audio.currentTime = Math.min(Math.max(0, Number(timestamp) || 0), this.audio.duration || Infinity);
    this.update();
    if (persist) this.onPersist();
  }

  updateDuration() {
    const duration = Number.isFinite(this.audio.duration) ? this.audio.duration : 0;
    this.seekBar.max = String(duration);
    this.duration.textContent = formatTime(duration);
    this.update();
  }

  update() {
    const currentTime = Number(this.audio.currentTime) || 0;
    const duration = Number(this.audio.duration);
    const progress = Number.isFinite(duration) && duration > 0
      ? Math.min(100, Math.max(0, currentTime / duration * 100))
      : 0;
    this.seekBar.value = String(currentTime);
    this.seekBar.style.setProperty("--synchrobook-seek-progress", `${progress}%`);
    this.currentTime.textContent = formatTime(currentTime);
    this.onFrame(currentTime);
  }

  loop() {
    this.stopLoop();
    const tick = () => {
      this.update();
      if (!this.audio.paused && !this.audio.ended) this.frame = requestAnimationFrame(tick);
    };
    this.frame = requestAnimationFrame(tick);
  }

  stopLoop() {
    if (this.frame != null) cancelAnimationFrame(this.frame);
    this.frame = null;
  }
}
