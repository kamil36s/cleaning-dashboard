export class AudioNotifier {
  constructor({ speechSynthesis = globalThis.speechSynthesis, Utterance = globalThis.SpeechSynthesisUtterance } = {}) {
    this.speechSynthesis = speechSynthesis;
    this.Utterance = Utterance;
    this.enabled = true;
    this.lastCadenceMessage = "";
    this.lastCadenceAt = 0;
  }

  get supported() {
    return Boolean(this.speechSynthesis && this.Utterance);
  }

  setEnabled(enabled) {
    this.enabled = Boolean(enabled);
    if (!this.enabled) this.speechSynthesis?.cancel?.();
  }

  speak(message, { priority = false } = {}) {
    if (!this.enabled || !this.supported || !message) return false;
    if (priority) this.speechSynthesis.cancel();
    const utterance = new this.Utterance(message);
    utterance.lang = "pl-PL";
    utterance.rate = 1.02;
    const polishVoice = this.speechSynthesis.getVoices?.().find((voice) => voice.lang?.toLowerCase().startsWith("pl"));
    if (polishVoice) utterance.voice = polishVoice;
    this.speechSynthesis.speak(utterance);
    return true;
  }

  announcePhase(phase) {
    if (!phase) return;
    if (phase.kind === "baseline") this.speak("Rozpoczynam pomiar wyjściowy. Nie pedałuj przez minutę.", { priority: true });
    else if (phase.kind === "warmup") this.speak("Rozgrzewka. Ustaw opór na poziom 1 i utrzymuj około 75 obrotów.", { priority: true });
    else if (phase.kind === "step") this.speak(`Ustaw opór na poziom ${phase.level}. Utrzymuj ${phase.targetRpm} obrotów na minutę.`, { priority: true });
    else if (phase.kind === "cooldown") this.speak("Schłodzenie. Ustaw opór na poziom 1 i kręć swobodnie.", { priority: true });
  }

  announceCountdown(nextPhase) {
    if (nextPhase?.kind === "step") this.speak(`Za 10 sekund zmień opór na poziom ${nextPhase.level}.`, { priority: true });
    else if (nextPhase?.kind === "cooldown") this.speak("Za 10 sekund rozpocznij schłodzenie na poziomie 1.", { priority: true });
  }

  announceSignalLost(missing = []) {
    this.speak(`Test wstrzymany. Utracono sygnał ${missing.join(" i ")}.`, { priority: true });
  }

  notifyCadence(currentRpm, targetRpm, toleranceRpm, now = Date.now()) {
    const current = Number(currentRpm);
    if (!Number.isFinite(current) || !Number.isFinite(targetRpm)) return;
    let message = "";
    if (current < targetRpm - toleranceRpm) message = `Zwiększ kadencję do ${targetRpm} obrotów.`;
    if (current > targetRpm + toleranceRpm) message = "Zwolnij.";
    if (!message || (message === this.lastCadenceMessage && now - this.lastCadenceAt < 15_000)) return;
    if (now - this.lastCadenceAt < 8_000) return;
    this.lastCadenceMessage = message;
    this.lastCadenceAt = now;
    this.speak(message);
  }
}

export class CadenceMetronome {
  constructor({
    AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext,
    setIntervalFn = globalThis.setInterval?.bind(globalThis),
    clearIntervalFn = globalThis.clearInterval?.bind(globalThis),
  } = {}) {
    this.AudioContextClass = AudioContextClass;
    this.setIntervalFn = setIntervalFn;
    this.clearIntervalFn = clearIntervalFn;
    this.context = null;
    this.enabled = false;
    this.mode = "1:2";
    this.rpm = 0;
    this.nextBeatAt = 0;
    this.beatIndex = 0;
    this.scheduler = null;
  }

  get multiplier() {
    return this.mode === "1:2" ? 2 : 1;
  }

  get bpm() {
    return Math.round(this.rpm * this.multiplier);
  }

  async setEnabled(enabled) {
    const shouldEnable = Boolean(enabled);
    if (!shouldEnable) {
      this.enabled = false;
      if (this.scheduler != null) this.clearIntervalFn?.(this.scheduler);
      this.scheduler = null;
      return false;
    }
    if (!this.AudioContextClass) throw new Error("Ta przeglądarka nie obsługuje Web Audio API.");
    if (!this.context) this.context = new this.AudioContextClass();
    if (this.context.state === "suspended") await this.context.resume();
    this.enabled = true;
    this.resetClock();
    this.schedule();
    if (this.scheduler == null) this.scheduler = this.setIntervalFn?.(() => this.schedule(), 25);
    return true;
  }

  setMode(mode) {
    const nextMode = mode === "1:1" ? "1:1" : "1:2";
    if (nextMode === this.mode) return;
    this.mode = nextMode;
    this.resetClock();
  }

  setRpm(rpm) {
    const nextRpm = Math.max(0, Math.min(250, Number(rpm) || 0));
    if (Math.abs(nextRpm - this.rpm) < 0.01) return;
    this.rpm = nextRpm;
    this.resetClock();
  }

  resetClock() {
    this.beatIndex = 0;
    this.nextBeatAt = (this.context?.currentTime || 0) + 0.05;
  }

  schedule() {
    if (!this.enabled || !this.context || this.rpm <= 0) return;
    const secondsPerBeat = 60 / Math.max(1, this.rpm * this.multiplier);
    const scheduleUntil = this.context.currentTime + 0.12;
    if (this.nextBeatAt < this.context.currentTime - 0.25) this.resetClock();
    while (this.nextBeatAt <= scheduleUntil) {
      this.scheduleClick(this.nextBeatAt, this.beatIndex);
      this.nextBeatAt += secondsPerBeat;
      this.beatIndex += 1;
    }
  }

  scheduleClick(at, beatIndex) {
    const oscillator = this.context.createOscillator();
    const gain = this.context.createGain();
    const accented = this.mode === "1:1" || beatIndex % 2 === 0;
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(accented ? 980 : 720, at);
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(accented ? 0.16 : 0.1, at + 0.004);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.045);
    oscillator.connect(gain);
    gain.connect(this.context.destination);
    oscillator.start(at);
    oscillator.stop(at + 0.05);
  }

  async destroy() {
    await this.setEnabled(false);
    if (this.context?.close) await this.context.close();
    this.context = null;
  }
}
