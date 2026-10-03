import { describe, expect, it, vi } from 'vitest';
import { createClozeAudioPlayer } from '../js/language/cloze-audio.js';

describe('Language Cloze cached audio player', () => {
  it('plays a returned local URL and reports playing/ended states', async () => {
    const instances = [];
    class FakeAudio {
      constructor(url) { this.url = url; this.play = vi.fn(async () => {}); this.pause = vi.fn(); instances.push(this); }
    }
    const playing = vi.fn();
    const ended = vi.fn();
    const player = createClozeAudioPlayer({ AudioClass: FakeAudio });
    await player.play('/api/language/cloze/audio/a.mp3', { onPlaying: playing, onEnded: ended });
    expect(instances[0].url).toBe('/api/language/cloze/audio/a.mp3');
    expect(instances[0].play).toHaveBeenCalledOnce();
    expect(playing).toHaveBeenCalledOnce();
    instances[0].onended();
    expect(ended).toHaveBeenCalledOnce();
  });

  it('stops previous playback and reports browser playback failures', async () => {
    const instances = [];
    class FakeAudio {
      constructor() { this.pause = vi.fn(); this.play = vi.fn(async () => { throw new Error('blocked'); }); instances.push(this); }
    }
    const error = vi.fn();
    const player = createClozeAudioPlayer({ AudioClass: FakeAudio });
    await expect(player.play('/cached.mp3', { onError: error })).rejects.toThrow('blocked');
    expect(error).toHaveBeenCalledOnce();
    player.stop();
    expect(createClozeAudioPlayer({ AudioClass: null }).available()).toBe(false);
  });

  it('supports explicit pause, resume and stop controls for generated Reader audio', async () => {
    const instances = [];
    class FakeAudio {
      constructor() { this.currentTime = 7; this.pause = vi.fn(); this.play = vi.fn(async () => {}); instances.push(this); }
    }
    const player = createClozeAudioPlayer({ AudioClass: FakeAudio });
    await player.play('/api/language/audio/generated.mp3');
    player.pause();
    await player.resume();
    player.stop();
    expect(instances[0].pause).toHaveBeenCalledTimes(2);
    expect(instances[0].play).toHaveBeenCalledTimes(2);
    expect(instances[0].currentTime).toBe(0);
  });
});
