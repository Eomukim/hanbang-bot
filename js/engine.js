/** 게임 진행. 규칙 판정 · 점수 · 타이머 · 봇 턴을 맡는다. */

import {
  normalizeWord, WORD_PATTERN, twoeumOf, ERR, MISSION_CHARS, missionHits, missionMultiplier,
} from './rules.js';
import { Bot, botLine, pickHellOpening, pickStartTitle } from './bot.js';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/** 배려모드가 한방 단어를 막는 첫 수의 수(1~5수). 6수부터는 풀린다. */
export const MERCY_TURNS = 5;

export class Engine {
  constructor({ dict, level = 2, timeLimit = 15, first = 'me', mercy = false, startChar = null, mission = null, rng = Math.random, on = {} }) {
    this.dict = dict;
    this.level = level;
    // 배려모드: 대국 시작 후 첫 5수(chain.length 0~4)는 나도 봇도 한방 단어를 쓰지 않는다.
    this.mercy = Boolean(mercy);
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
    // Lv.5 지옥에서 봇이 선공이면, 무작위 글자 대신 봇이 유리한 시작 글자로 연다.
    const hellOpening = !startChar && level >= 5 && this.first === 'bot'
      ? pickHellOpening(dict, rng)
      : null;
    // 나머지는 끄투식으로 기준 단어(일상 명사 2~3글자)를 뽑고 그 첫 글자를 제시한다.
    // 직접 startChar를 넘긴 시험·재현 경로는 그대로 존중한다.
    const opening = startChar || hellOpening ? null : pickStartTitle(dict, { level, rng });
    this.startChar = startChar || hellOpening || opening?.char || starts[Math.floor(rng() * starts.length)] || '가';
    /** 끄투식으로 고른 기준 단어(제시어). 직접 startChar를 받았거나 Lv.5 오프닝이면 null. */
    this.startTitle = opening?.title ?? null;
    this.missionChar = mission || this.pickMission(this.startChar);
    this.needChar = this.startChar;

    this.deadline = 0;
    this.turnTimer = null;
    this.botTimer = null;
    this.finished = false;
  }

  /** 미션 글자 14종 중 하나를 고른다. exclude 와는 다른 글자를 고른다. */
  pickMission(exclude = null) {
    const pool = MISSION_CHARS.filter((ch) => ch !== exclude);
    const list = pool.length ? pool : MISSION_CHARS.slice();
    return list[Math.floor(this.rng() * list.length)];
  }

  /** 미션 성공: 직전 글자와 다른 다음 미션 글자로 즉시 넘긴다. */
  rotateMission() {
    const prev = this.missionChar;
    this.missionChar = this.pickMission(prev);
    return { prev, next: this.missionChar };
  }

  snapshot() {
    return {
      phase: this.phase,
      level: this.level,
      mercy: this.mercy,
      mercyGuard: this.mercyGuard(),
      mercyTurn: Math.min(this.chain.length + 1, MERCY_TURNS),
      mercyTurns: MERCY_TURNS,
      first: this.first,
      startChar: this.startChar,
      startTitle: this.startTitle,
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

  /** 지금 이을 수가 배려모드 보호(첫 5수 · 한방 금지) 안에 있는가. */
  mercyGuard() {
    return this.mercy && this.chain.length < MERCY_TURNS;
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

    const move = this.bot.choose({
      needChar: this.needChar, used: this.used, turn: this.round, mission: this.missionChar, guard: this.mercyGuard(),
    });
    if (!move) {
      this.botTimer = setTimeout(() => this.finish('me', 'bot-stuck'), 420);
      return;
    }
    this.botTimer = setTimeout(() => this.applyBotMove(move), move.delay);
  }

  applyBotMove(move) {
    if (this.finished) return;
    const word = move.word;
    const missionChar = this.missionChar;
    const hits = missionHits(word, missionChar);
    const score = this.scoreFor(word, 0, hits);
    this.scores.bot += score;
    this.used.add(word);
    this.wordsPlayed.bot += 1;
    this.chain.push({ who: 'bot', word, score, kind: move.kind, missionHits: hits, at: Date.now() });
    this.needChar = word.charAt(word.length - 1);
    const rotated = hits > 0 ? this.rotateMission() : null;

    this.on.botWord?.({
      word,
      score,
      kind: move.kind,
      mission: { char: missionChar, hits, mul: missionMultiplier(hits), next: rotated?.next ?? null },
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
    if (!WORD_PATTERN.test(word)) return { ok: false, error: ERR.NOT_HANGUL };
    const starts = this.dictStartVariants();
    if (!starts.some((s) => word.startsWith(s))) return { ok: false, error: ERR.WRONG_START };
    if (this.used.has(word)) return { ok: false, error: ERR.USED };
    if (!this.dict.has(word)) return { ok: false, error: ERR.NOT_FOUND };
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
    // 배려모드: 첫 5수 동안은 후속 단어가 없는 한방 단어를 거부한다. 타이머는 그대로 흐른다.
    if (this.mercyGuard() && this.dict.isOneShot(word)) {
      const error = {
        code: 'mercy',
        message: `배려모드: 첫 ${MERCY_TURNS}턴은 한방 단어를 쓸 수 없어요`,
      };
      this.on.error?.({ ...error, input: word, state: this.snapshot() });
      return { ok: false, error, word };
    }
    clearTimeout(this.turnTimer);
    this.combo += 1;
    this.bestCombo = Math.max(this.bestCombo, this.combo);
    const missionChar = this.missionChar;
    const hits = missionHits(word, missionChar);
    const missionMul = missionMultiplier(hits);
    const mission = hits > 0;
    const score = this.scoreFor(word, this.combo - 1, hits);

    this.scores.me += score;
    this.used.add(word);
    this.wordsPlayed.me += 1;
    this.chain.push({ who: 'me', word, score, kind: 'normal', missionHits: hits, at: Date.now() });
    this.needChar = word.charAt(word.length - 1);
    this.phase = 'bot';
    // 미션 성공 → 곧바로 다음 미션 글자로. 실패했으면 그대로 유지된다.
    const rotated = mission ? this.rotateMission() : null;

    const state = this.snapshot();
    this.on.meWord?.({
      word, score, combo: this.combo, mission, missionHits: hits, missionChar, missionMul, nextMission: rotated?.next ?? null, state,
    });
    this.on.turn?.(state);
    // 4단계·5단계는 즉사·수읽기 봇이라 텀을 거의 두지 않는다
    const pause = this.level >= 4 ? 40 + this.rng() * 60 : 180 + this.rng() * 160;
    this.botTimer = setTimeout(() => this.botTurn(), pause);
    return {
      ok: true, word, score, combo: this.combo, mission, missionHits: hits, missionMul, missionChar, nextMission: rotated?.next ?? null,
    };
  }

  scoreFor(word, combo, hits = 0) {
    const len = word.length;
    const base = len * len + 4 * len;
    const comboMul = Math.min(2.5, 1 + 0.1 * combo);
    return Math.round(base * comboMul * missionMultiplier(hits));
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
      mercy: this.mercy,
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
