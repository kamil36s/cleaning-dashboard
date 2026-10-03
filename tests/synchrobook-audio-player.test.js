import { beforeEach, describe, expect, it, vi } from "vitest";
import { SynchrobookAudioPlayer } from "../js/synchrobook/audio-player.js";

function createPlayer() {
  document.body.innerHTML = `
    <audio id="audio"></audio>
    <button id="play"><span></span></button>
    <button id="back"></button><button id="forward"></button>
    <input id="seek" type="range"><span id="current"></span><span id="duration"></span>
    <select id="speed"><option value="1">1.0×</option><option value="1.5">1.5×</option><option value="2">2.0×</option></select>`;
  const audio = document.querySelector("#audio");
  Object.defineProperty(audio, "duration", { configurable: true, value: 600 });
  audio.load = vi.fn();
  const onFrame = vi.fn();
  const onPersist = vi.fn();
  const player = new SynchrobookAudioPlayer({
    audio,
    playButton: document.querySelector("#play"),
    seekBar: document.querySelector("#seek"),
    currentTime: document.querySelector("#current"),
    duration: document.querySelector("#duration"),
    speed: document.querySelector("#speed"),
    back: document.querySelector("#back"),
    forward: document.querySelector("#forward"),
  }, { onFrame, onPersist });
  return { audio, player, onFrame, onPersist, speed: document.querySelector("#speed") };
}

describe("Synchrobook audio playback rate", () => {
  beforeEach(() => document.body.replaceChildren());

  it("restores the saved rate after metadata loads", () => {
    const { audio, player, speed } = createPlayer();
    player.load("/book.m4a", { timestamp: 120, speed: 1.5 });
    audio.playbackRate = 1;
    audio.dispatchEvent(new Event("loadedmetadata"));

    expect(audio.playbackRate).toBe(1.5);
    expect(audio.defaultPlaybackRate).toBe(1.5);
    expect(speed.value).toBe("1.5");
    expect(audio.currentTime).toBe(120);
    expect(document.querySelector("#seek").style.getPropertyValue("--synchrobook-seek-progress")).toBe("20%");
  });

  it("uses and displays the actual changed rate immediately", () => {
    const { audio, speed, onFrame, onPersist } = createPlayer();
    speed.value = "2";
    speed.dispatchEvent(new Event("change"));

    expect(audio.playbackRate).toBe(2);
    expect(audio.defaultPlaybackRate).toBe(2);
    expect(speed.value).toBe("2");
    expect(onFrame).toHaveBeenCalled();
    expect(onPersist).toHaveBeenCalledOnce();
  });
});
