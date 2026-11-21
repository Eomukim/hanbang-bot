/** Web Audio 로 만드는 효과음. 음원 파일 없이 오실레이터만 쓴다. */

export class Sfx {
  constructor(enabled = true) {
    this.enabled = enabled;
    this.ctx = null;
    this.master = null;
  }

  unlock() {
    if (this.ctx) {
      if (this.ctx.state === 'suspended') this.ctx.resume();
      return;
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    this.ctx = new AC();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.5;
    this.master.connect(this.ctx.destination);
  }

  setEnabled(on) {
    this.enabled = on;
    if (this.master) this.master.gain.value = on ? 0.5 : 0;
  }

  now() {
    return this.ctx ? this.ctx.currentTime : 0;
  }

  tone({ freq, to = null, type = 'sine', dur = 0.12, gain = 0.2, delay = 0, attack = 0.008 }) {
    if (!this.ctx || !this.enabled) return;
    const t0 = this.now() + delay;
    const osc = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (to) osc.frequency.exponentialRampToValueAtTime(Math.max(30, to), t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(gain, t0 + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g).connect(this.master);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  }

  noise({ dur = 0.25, gain = 0.16, delay = 0, from = 1800, to = 200 }) {
    if (!this.ctx || !this.enabled) return;
    const rate = this.ctx.sampleRate;
    const len = Math.floor(rate * dur);
    const buffer = this.ctx.createBuffer(1, len, rate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < len; i += 1) data[i] = (Math.random() * 2 - 1) * (1 - i / len);
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    const filter = this.ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.setValueAtTime(from, this.now() + delay);
    filter.frequency.exponentialRampToValueAtTime(to, this.now() + delay + dur);
    filter.Q.value = 0.9;
    const g = this.ctx.createGain();
    g.gain.value = gain;
    src.connect(filter).connect(g).connect(this.master);
    src.start(this.now() + delay);
  }

  play(name, opts = {}) {
    if (!this.enabled || !this.ctx) return;
    switch (name) {
      case 'tap':
        this.tone({ freq: 640, type: 'triangle', dur: 0.05, gain: 0.08 });
        break;
      case 'ok': {
        const step = Math.min(opts.combo || 0, 8) * 40;
        this.tone({ freq: 523 + step, type: 'sine', dur: 0.1, gain: 0.16 });
        this.tone({ freq: 784 + step, type: 'sine', dur: 0.16, gain: 0.13, delay: 0.06 });
        break;
      }
      case 'bot':
        this.tone({ freq: 330, type: 'triangle', dur: 0.09, gain: 0.08 });
        break;
      case 'error':
        this.tone({ freq: 190, to: 120, type: 'sawtooth', dur: 0.18, gain: 0.1 });
        break;
      case 'tick':
        this.tone({ freq: 980, type: 'square', dur: 0.035, gain: 0.05 });
        break;
      case 'kill':
        this.noise({ dur: 0.5, gain: 0.2, from: 2600, to: 180 });
        this.tone({ freq: 220, to: 55, type: 'sawtooth', dur: 0.55, gain: 0.14 });
        this.tone({ freq: 90, to: 40, type: 'sine', dur: 0.7, gain: 0.22 });
        break;
      case 'win':
        [523, 659, 784, 1046].forEach((f, i) => this.tone({ freq: f, type: 'sine', dur: 0.18, gain: 0.13, delay: i * 0.09 }));
        break;
      case 'lose':
        [392, 330, 262].forEach((f, i) => this.tone({ freq: f, type: 'triangle', dur: 0.26, gain: 0.12, delay: i * 0.13 }));
        break;
      case 'start':
        [392, 523, 659].forEach((f, i) => this.tone({ freq: f, type: 'sine', dur: 0.12, gain: 0.1, delay: i * 0.06 }));
        break;
      case 'mission': {
        // 미션이 겹친 만큼 음을 더 쌓아 올린다
        const stack = Math.min(opts.stack || 1, 4);
        const notes = [660, 880, 1100, 1320, 1760].slice(0, 2 + stack);
        notes.forEach((f, i) => this.tone({ freq: f, type: 'triangle', dur: 0.14, gain: 0.13, delay: i * 0.055 }));
        break;
      }
      default:
        break;
    }
  }
}
