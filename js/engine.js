/** 게임 진행. 규칙 판정 · 점수 · 타이머 · 봇 턴을 맡는다. */

import { normalizeWord, HANGUL_ONLY, twoeumOf, ERR } from './rules.js';
import { Bot, botLine } from './bot.js';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

export class Engine {
  constructor({ dict, level = 2, timeLimit = 15, first = 'me', startChar = null, mission = null, rng = Math.random, on = {} }) {
    this.dict = dict;
    this.level = level;
    this.timeLimit = timeLimit;
    this.first = first;
    this.rng = rng;
    this.on = on;
    this.bot = new Bot({ level, dict, rng });

    this.phase = 'idle'; // idle | me | bot | over
    this.chain = [];
    this.used = new Set();
    this.scores = { me: 0, bot: 0 };
    this.combo = 0;
    this.bestCombo = 0;
    this.round = 1;
    this.wordsPlayed = { me: 0, bot: 0 };

    const starts = dict.goodStartChars(60);
    this.startChar = startChar || starts[Math.floor(rng() * starts.length)] || '가';
    this.missionChar = mission || this.pickMission();
    this.needChar = this.startChar;

    this.deadline = 0;
    this.turnTimer = null;
    this.botTimer = null;
    this.hinted = false;
    this.finished = false;
  }

  pickMission() {
    const pool = this.dict.goodStartChars(40).filter((ch) => ch !== this.startChar);
    if (!pool.length) return null;
    return pool[Math.floor(this.rng() * pool.length)];
  }

  snapshot() {
    return {
      phase: this.phase,
      level: this.level,
      first: this.first,
      startChar: this.startChar,
      needChar: this.needChar,
      needAlt: twoeumOf(this.needChar),
      missionChar: this.missionChar,
      scoreMe: this.scores.me,
      scoreBot: this.scores.bot,
      combo: this.combo,
      bestCombo: this.bestCombo,
      round: this.round,
      chain: this.chain,
      timeLeft: this.timeLeft(),
      timeLimit: this.timeLimit,
      candidateCount: this.phase === 'me' ? this.candidateCount() : null,
      turn: this.round,
    };
  }

  timeLeft() {
    if (this.phase !== 'me') return this.timeLimit;
    return clamp((this.deadline - performance.now()) / 1000, 0, this.timeLimit);
  }

  candidateCount() {
    const cands = this.dict.candidatesFor(this.needChar, this.used);
    return cands.length;
  }

  /* ── 시작 ───────────────────────────────────────────────── */

  start() {
    this.on.start?.(this.snapshot());
    if (this.first === 'bot') this.botTurn();
    else this.playerTurn();
  }

  playerTurn() {
    if (this.finished) return;
    this.phase = 'me';
    this.hinted = false;
    this.deadline = performance.now() + this.timeLimit * 1000;
    clearTimeout(this.turnTimer);
    this.turnTimer = setTimeout(() => {
      if (this.phase === 'me') this.finish('bot', 'timeout');
    }, this.timeLimit * 1000 + 40);
    this.on.turn?.(this.snapshot());
  }

  botTurn() {
    if (this.finished) return;
    this.phase = 'bot';
    clearTimeout(this.turnTimer);
    this.on.botThinking?.(this.snapshot());

    const move = this.bot.choose({ needChar: this.needChar, used: this.used, turn: this.round });
    if (!move) {
      this.botTimer = setTimeout(() => this.finish('me', 'bot-stuck'), 420);
      return;
    }
    this.botTimer = setTimeout(() => this.applyBotMove(move), move.delay);
  }

  applyBotMove(move) {
    if (this.finished) return;
    const word = move.word;
    const score = this.scoreFor(word, 0, this.missionChar && word.includes(this.missionChar));
    this.scores.bot += score;
    this.used.add(word);
    this.wordsPlayed.bot += 1;
    this.chain.push({ who: 'bot', word, score, kind: move.kind, at: Date.now() });
    this.needChar = word.charAt(word.length - 1);

    this.on.botWord?.({
      word,
      score,
      kind: move.kind,
      oneShot: this.dict.isOneShot(word),
      line: this.lineFor(move.kind, 'bot'),
      state: this.snapshot(),
    });

    if (!this.dict.hasCandidate(this.needChar, this.used)) {
      this.finish('bot', this.dict.isOneShot(word) ? 'one-shot' : 'blocked');
      return;
    }
    this.round += 1;
    this.playerTurn();
  }

  lineFor(kind, who) {
    const event = kind === 'oneshot' ? 'oneShot' : kind === 'press' || kind === 'outer' ? 'good' : 'good';
    return botLine(this.level, event, this.rng);
  }

  /* ── 내 차례 ─────────────────────────────────────────────── */

  validate(raw) {
    const word = normalizeWord(raw);
    if (!word) return { ok: false, error: ERR.EMPTY };
    if (word.length < 2) return { ok: false, error: ERR.TOO_SHORT };
    if (!HANGUL_ONLY.test(word)) return { ok: false, error: ERR.NOT_HANGUL };
    const starts = this.dictStartVariants();
    if (!starts.some((s) => word.startsWith(s))) return { ok: false, error: ERR.WRONG_START };
    if (this.used.has(word)) return { ok: false, error: ERR.USED };
    if (!this.dict.has(word) && !this.dict.custom.has(word)) return { ok: false, error: ERR.NOT_FOUND };
    return { ok: true, word };
  }

  dictStartVariants() {
    const alt = twoeumOf(this.needChar);
    return alt ? [this.needChar, alt] : [this.needChar];
  }

  playMe(raw) {
    if (this.finished || this.phase !== 'me') {
      return { ok: false, error: { code: 'phase', message: '지금은 내 차례가 아니에요.' } };
    }
    const result = this.validate(raw);
    if (!result.ok) {
      this.combo = 0;
      this.on.error?.({ ...result.error, input: normalizeWord(raw), state: this.snapshot() });
      return result;
    }

    const word = result.word;
    clearTimeout(this.turnTimer);
    this.combo += 1;
    this.bestCombo = Math.max(this.bestCombo, this.combo);
    const mission = Boolean(this.missionChar && word.includes(this.missionChar));
    const score = this.scoreFor(word, this.combo - 1, mission);

    this.scores.me += score;
    this.used.add(word);
    this.wordsPlayed.me += 1;
    this.chain.push({ who: 'me', word, score, kind: 'normal', at: Date.now() });
    this.needChar = word.charAt(word.length - 1);
    this.phase = 'bot';

    const state = this.snapshot();
    this.on.meWord?.({ word, score, combo: this.combo, mission, state });
    this.on.turn?.(state);
    // 4단계는 즉사 봇이라 텀을 거의 두지 않는다
    const pause = this.level === 4 ? 40 + this.rng() * 60 : 180 + this.rng() * 160;
    this.botTimer = setTimeout(() => this.botTurn(), pause);
    return { ok: true, word, score, combo: this.combo, mission };
  }

  scoreFor(word, combo, mission) {
    const len = word.length;
    const base = len * len + 4 * len;
    const comboMul = Math.min(2.5, 1 + 0.1 * combo);
    const missionMul = mission ? 1.5 : 1;
    return Math.round(base * comboMul * missionMul);
  }

  /* ── 힌트 ───────────────────────────────────────────────── */

  hint() {
    if (this.phase !== 'me') return null;
    const cands = this.dict.candidatesFor(this.needChar, this.used);
    if (!cands.length) return { count: 0, sample: null };
    const sample = cands[Math.floor(this.rng() * cands.length)];
    const mask = sample.charAt(0) + '○'.repeat(Math.max(0, sample.length - 1));
    this.hinted = true;
    return { count: cands.length, sample, mask, length: sample.length };
  }

  /* ── 종료 ───────────────────────────────────────────────── */

  finish(winner, reason) {
    if (this.finished) return;
    this.finished = true;
    this.phase = 'over';
    clearTimeout(this.turnTimer);
    clearTimeout(this.botTimer);
    this.on.end?.({
      winner,
      reason,
      win: winner === 'me',
      scoreMe: this.scores.me,
      scoreBot: this.scores.bot,
      round: this.round,
      turns: this.chain.length,
      words: this.wordsPlayed.me,
      bestCombo: this.bestCombo,
      chain: this.chain,
      state: this.snapshot(),
    });
  }

  quit() {
    if (this.finished) return;
    this.finish('bot', 'quit');
  }

  destroy() {
    clearTimeout(this.turnTimer);
    clearTimeout(this.botTimer);
    this.finished = true;
    this.phase = 'over';
  }
}
