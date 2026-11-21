/**
 * 5단계 봇. 난이도마다 단어를 고르는 방식과 반응이 다르다.
 *
 * Lv.5 지옥은 페널티 없이 순수하게 세게 둔다.
 *  - 빌드 타임(`build/build_data.py`)에 796,750단어 음절 그래프를 역방향 분석해 둔
 *    승리/패배/무승부 상태(`dict.graphStatus`)와 한방 단어 목록(`dict.shotWords`)을 읽고,
 *  - 실제로 이미 나온 단어(`used`)를 반영해 수를 검증한 뒤
 *    한방 즉사 → 강제 필승 → 위험한 수 배제 → 압박·미션·장문 순으로 고른다.
 */

import { allowedStarts, missionHits as countMission, missionMultiplier } from './rules.js';

export const LEVELS = [
  {
    id: 1,
    name: '쉬움',
    face: '🙂',
    label: 'Lv.1 순한 봇',
    desc: '한방 단어는 절대 안 씀 · 쉬운 2~3글자',
    botName: '한방봇 주니어',
  },
  {
    id: 2,
    name: '보통',
    face: '😐',
    label: 'Lv.2 보통',
    desc: '가끔 긴 단어 · 초반엔 한방 금지',
    botName: '한방봇',
  },
  {
    id: 3,
    name: '어려움',
    face: '😏',
    label: 'Lv.3 어려움',
    desc: '외통수로 몰아넣고 결정타',
    botName: '한방봇 X',
  },
  {
    id: 4,
    name: '극악',
    face: '😈',
    label: 'Lv.4 극악',
    desc: '한방 단어가 있으면 100% 즉사',
    botName: '한방봇 극악',
  },
  {
    id: 5,
    name: '지옥',
    face: '💀',
    label: 'Lv.5 지옥',
    desc: '필승 경로·수읽기로 도망칠 곳을 지움',
    botName: '한방봇 지옥',
  },
];

export function levelInfo(level) {
  return LEVELS.find((l) => l.id === level) || LEVELS[1];
}

const LINES = {
  1: {
    start: ['시작해요! 어렵지 않게 갈게요.', '끝말잇기 좋아해요. 가볍게 해요!'],
    good: ['오, 그 단어 알아요!', '좋아요, 계속해 봐요.', '음… 생각했어요.'],
    long: ['긴 단어네요! 대단해요.', '와, 그건 몰랐어요.'],
    combo: ['계속 맞히시네요…', '저 좀 도와주세요…'],
    bad: ['어? 그건 사전에 없어요.', '앗, 다시 해봐요!'],
    blocked: ['앗… 제가 막혔어요.', '단어가 안 떠올라요…'],
    win: ['제가 이겼어요!', '이겼다!'],
    lose: ['졌어요… 다음엔 더 잘할게요.'],
    timeout: ['시간이 다 됐어요…'],
  },
  2: {
    start: ['좋아, 시작하지.', '한 판 붙자고.'],
    good: ['나쁘지 않은데.', '그 정도야 뭐.', '계속 가 보자.'],
    long: ['긴 걸 갖고 왔네.', '제법인데.'],
    combo: ['흐름을 타고 있네.', '슬슬 집중해야겠어.'],
    bad: ['그건 없어.', '사전을 다시 봐.'],
    blocked: ['…막혔나?', '여기서 막히면 안 되는데.'],
    win: ['내 승리야.', '이번엔 나였다.'],
    lose: ['…인정하지.', '한 수 배웠네.'],
    timeout: ['시간 초과. 게임 끝이야.'],
  },
  3: {
    start: ['어디, 얼마나 버티는지 볼까.', '시작해 볼까.'],
    good: ['예상했어.', '그걸 피해 가네.', '아직이야.'],
    long: ['길게 가는군.', '좋아, 그 길로 가자.'],
    combo: ['제법인데? 슬슬 위험해.', '흐름 좋네. 곧 끊길 거야.'],
    bad: ['그건 안 돼.', '아깝게 빗나갔네.'],
    blocked: ['…여기서 막혔어? 아쉽네.', '막혔네.'],
    win: ['예정된 결말이야.', '내가 이겼어.'],
    lose: ['…이건 예상 밖이네.', '네가 한 수 위였어.'],
    timeout: ['시간이 없어. 끝.'],
  },
  4: {
    start: ['시작해. 오래 버텨 봐.', '한 방이면 충분해.', '준비됐어?'],
    good: ['…그 정도?', '한 번 더.'],
    long: ['길어도 소용없어.', '그래서?'],
    combo: ['재밌어. 곧 끝나.'],
    bad: ['틀렸어.', '그런 단어는 없어.'],
    blocked: ['막혔지.', '끝이야.'],
    oneShot: ['한방.', '끝.', '이게 지옥이야.', '잘 가.'],
    win: ['다음엔 오지 마.', '한 방이면 충분했지.'],
    lose: ['…말이 안 되는데.', '…….'],
    timeout: ['시간. 끝.'],
  },
  5: {
    start: ['길은 이미 계산해 뒀어.', '여기서 끝내자.', '도망칠 곳은 없어.'],
    good: ['…그 수였나.', '한 칸 더.', '그래도 이 길이야.'],
    long: ['길어도 같은 결말이야.', '점수는 가져가.'],
    combo: ['좋아. 조금만 더.', '버티는군.'],
    bad: ['그건 없어.', '사전에 없어.'],
    blocked: ['막혔어?', '…….'],
    oneShot: ['한방.', '계산대로.', '여기까지야.', '끝.'],
    win: ['처음부터 정해진 판이야.', '다음엔 각을 봐.'],
    lose: ['…이건 계산 밖이야.', '한 수 인정해.'],
    timeout: ['시간. 끝.'],
  },
};

export function botLine(level, event, rng = Math.random) {
  const table = LINES[level] || LINES[2];
  const list = table[event];
  if (!list || !list.length) return '';
  return list[Math.floor(rng() * list.length)];
}

const pick = (arr, rng) => arr[Math.floor(rng() * arr.length)];

const delayBetween = (a, b, rng) => a + rng() * (b - a);

const lastOf = (w) => w.charAt(w.length - 1);

const pressureTier = (n) => (n <= 1 ? 0 : n <= 3 ? 1 : n <= 10 ? 2 : n <= 40 ? 3 : n <= 200 ? 4 : 5);

/**
 * Lv.5 지옥의 수읽기.
 * 후보 목록·사용된 단어·빌드 타임 그래프를 함께 보면서, 실제 판(used)에서 검증한 수만 둔다.
 */
class Duel {
  constructor(dict, used) {
    this.dict = dict;
    this.used = new Set(used);
    this.starts = new Map();
    for (const w of this.used) this.bump(w.charAt(0), 1);
    this.visits = 0;
    this.budget = 0;
    this.deadline = 0;
  }

  bump(ch, d) {
    const n = (this.starts.get(ch) || 0) + d;
    if (n > 0) this.starts.set(ch, n);
    else this.starts.delete(ch);
  }

  add(word) {
    if (this.used.has(word)) return false;
    this.used.add(word);
    this.bump(word.charAt(0), 1);
    return true;
  }

  remove(word) {
    if (!this.used.delete(word)) return false;
    this.bump(word.charAt(0), -1);
    return true;
  }

  outOfTime() {
    return this.visits > this.budget || performance.now() > this.deadline;
  }

  /** 이 글자로 아직 낼 수 있는 단어 수(내 단어장 포함, 이미 나온 단어 제외). */
  liveCount(ch) {
    let n = 0;
    for (const s of allowedStarts(ch)) {
      n += this.dict.dictStartCount(s) + this.dict.customStartCount(s) - (this.starts.get(s) || 0);
    }
    return n > 0 ? n : 0;
  }

  /** 이 글자에서 바로 낼 수 있는 한방 단어(상대 후보 0). */
  killAt(ch) {
    const shots = this.dict.shotWords(ch);
    if (shots) {
      for (const w of shots) {
        this.visits += 1;
        if (!this.used.has(w) && this.dict.countFrom(lastOf(w)) === 0) return w;
      }
    }
    // 한방 목록에 없는 경우(내 단어장, 후속 단어가 모두 소진된 자리)는 후보가 적을 때만 직접 확인
    if (this.liveCount(ch) <= 40) {
      for (const w of this.dict.candidatesFor(ch, this.used)) {
        this.visits += 1;
        const end = lastOf(w);
        if (this.dict.countFrom(end) === 0) return w;
        if (this.dict.countFrom(end) <= 4) {
          this.add(w);
          const left = this.liveCount(end);
          this.remove(w);
          if (!left) return w;
        }
      }
    }
    return null;
  }

  /** 지는 자리(패배 노드)로 보내는 수. 필승 경로의 후보. */
  winMoves(ch) {
    if (this.liveCount(ch) > 140) return [];
    const dict = this.dict;
    const out = [];
    for (const w of dict.candidatesFor(ch, this.used)) {
      this.visits += 1;
      const end = lastOf(w);
      if (dict.graphStatus(end) === 'L' || this.liveCount(end) <= 3) out.push(w);
    }
    out.sort((a, b) => {
      const da = dict.graphStatus(lastOf(a)) === 'L' ? dict.graphDepth(lastOf(a)) : 9;
      const db = dict.graphStatus(lastOf(b)) === 'L' ? dict.graphDepth(lastOf(b)) : 9;
      return da - db || b.length - a.length;
    });
    return out.slice(0, 64);
  }

  /** 이 글자에서 plies 수 안에 강제로 이길 수 있는 수(모든 상대 응수를 실제로 확인). */
  findWin(ch, plies) {
    if (this.outOfTime()) return null;
    const kill = this.killAt(ch);
    if (kill) return kill;
    if (plies <= 1) return null;
    for (const w of this.winMoves(ch)) {
      if (this.outOfTime()) return null;
      this.add(w);
      const end = lastOf(w);
      let ok = true;
      const replies = this.dict.candidatesFor(end, this.used);
      if (replies.length) {
        for (const r of replies) {
          this.add(r);
          const next = this.findWin(lastOf(r), plies - 2);
          this.remove(r);
          if (!next) {
            ok = false;
            break;
          }
        }
      }
      this.remove(w);
      if (ok) return w;
    }
    return null;
  }

  /** findWin 의 참/거짓 판. */
  winIn(ch, plies) {
    return this.findWin(ch, plies) !== null;
  }
}

export class Bot {
  constructor({ level, dict, rng = Math.random }) {
    this.level = level;
    this.dict = dict;
    this.rng = rng;
  }

  /**
   * @returns {{word: string, delay: number, kind: string} | null}
   */
  choose({ needChar, used, turn, mission = null }) {
    const cands = this.dict.candidatesFor(needChar, used);
    if (!cands.length) return null;
    if (this.level === 5) return this.chooseHell({ needChar, used, cands, mission });

    const dict = this.dict;
    const rng = this.rng;
    const endCount = (w) => dict.countFrom(w.charAt(w.length - 1));
    const oneShot = cands.filter((w) => endCount(w) === 0);

    if (this.level === 4) {
      if (oneShot.length) {
        return { word: pick(oneShot, rng), delay: delayBetween(200, 480, rng), kind: 'oneshot' };
      }
      // 한방이 없으면: 상대가 받아치기 가장 어려운 최소 후속 단어, 길이 우선
      let best = null;
      let bestKey = Infinity;
      for (const w of cands) {
        const key = endCount(w) * 100 - w.length;
        if (key < bestKey) {
          bestKey = key;
          best = w;
        }
      }
      return { word: best, delay: delayBetween(200, 500, rng), kind: 'outer' };
    }

    if (this.level === 3) {
      if (turn >= 4 && oneShot.length && rng() < 0.85) {
        return { word: pick(oneShot, rng), delay: delayBetween(700, 1300, rng), kind: 'oneshot' };
      }
      const induced = cands.filter((w) => {
        const n = endCount(w);
        return n >= 1 && n <= 3;
      });
      if (induced.length && rng() < 0.7) {
        return { word: pick(induced, rng), delay: delayBetween(700, 1400, rng), kind: 'press' };
      }
      const tough = cands.filter((w) => {
        const n = endCount(w);
        return n > 0 && n <= 30;
      });
      const pool = tough.length ? tough : cands.filter((w) => endCount(w) > 0);
      return { word: pick(pool.length ? pool : cands, rng), delay: delayBetween(750, 1400, rng), kind: 'press' };
    }

    if (this.level === 2) {
      if (turn > 3 && oneShot.length && rng() < 0.1) {
        return { word: pick(oneShot, rng), delay: delayBetween(1000, 1700, rng), kind: 'oneshot' };
      }
      const longWords = cands.filter((w) => w.length >= 4 && endCount(w) > 5);
      if (longWords.length && rng() < 0.22) {
        return { word: pick(longWords, rng), delay: delayBetween(1000, 1800, rng), kind: 'long' };
      }
      const easy = cands.filter((w) => w.length <= 3 && endCount(w) >= 25);
      const pool = easy.length ? easy : cands.filter((w) => endCount(w) > 0);
      return {
        word: pick(pool.length ? pool : cands, rng),
        delay: delayBetween(1000, 1800, rng),
        kind: 'normal',
      };
    }

    // 레벨 1: 한방 금지, 후속 단어가 많은 2~3글자
    const safe = cands.filter((w) => {
      const n = endCount(w);
      return n >= 40 && w.length <= 3;
    });
    if (safe.length) return { word: pick(safe, rng), delay: delayBetween(1500, 2500, rng), kind: 'normal' };

    const safer = cands.filter((w) => {
      const n = endCount(w);
      return n >= 15 && w.length <= 4;
    });
    if (safer.length) return { word: pick(safer, rng), delay: delayBetween(1500, 2500, rng), kind: 'normal' };

    const notDead = cands.filter((w) => endCount(w) > 0);
    return {
      word: pick(notDead.length ? notDead : cands, rng),
      delay: delayBetween(1500, 2500, rng),
      kind: 'normal',
    };
  }

  /* ── Lv.5 지옥 ──────────────────────────────────────────── */

  chooseHell({ needChar, used, cands, mission }) {
    const dict = this.dict;
    const rng = this.rng;
    const duel = new Duel(dict, used);
    duel.budget = 80_000;
    duel.deadline = performance.now() + 120;

    const valueOf = (w) => {
      const len = w.length;
      const hits = mission ? countMission(w, mission) : 0;
      return (len * len + 4 * len) * missionMultiplier(hits);
    };

    const kills = [];
    const endBest = new Map();   // 끝 글자별 최고 점수 단어
    const winEndBest = new Map();

    // 한 번 훑으면서 후보를 성격별로 나눈다 (비용 상수: 후보 수 × O(1))
    for (const w of cands) {
      const end = lastOf(w);
      const val = valueOf(w);
      const staticDead = dict.countFrom(end) === 0;
      const live = duel.liveCount(end);
      if (staticDead || (live === 0 && dict.countFrom(end) <= 6)) {
        kills.push({ w, val });
        continue;
      }
      const status = dict.graphStatus(end);
      if (status === 'L') {
        const prev = winEndBest.get(end);
        if (!prev || val > prev.val) {
          winEndBest.set(end, { w, end, val, depth: dict.graphDepth(end), live });
        }
      }
      const prev = endBest.get(end);
      if (!prev || val > prev.val) {
        endBest.set(end, { w, end, val, live, status, depth: dict.graphDepth(end) });
      }
    }
    const winning = [...winEndBest.values()];
    const safe = [...endBest.values()];

    // 1) 한방 즉사 — 미션 중첩·장문 우선
    if (kills.length) {
      let best = kills[0];
      for (const k of kills) if (k.val > best.val) best = k;
      return { word: best.w, delay: delayBetween(150, 400, rng), kind: 'oneshot' };
    }

    // 2) 강제 필승 — 상대가 무엇을 받아쳐도 다음에 한방/필승으로 끝난다
    if (winning.length) {
      winning.sort((a, b) => a.depth - b.depth || b.val - a.val);
      let best = null;
      let tested = 0;
      for (const cand of winning) {
        if (tested >= 14 || duel.outOfTime()) break;
        tested += 1;
        const w = cand.w;
        duel.add(w);
        const replies = dict.candidatesFor(cand.end, duel.used);
        let ok = replies.length === 0;
        if (!ok) {
          ok = true;
          for (const r of replies) {
            duel.add(r);
            const good = duel.winIn(lastOf(r), 3);
            duel.remove(r);
            if (!good) {
              ok = false;
              break;
            }
          }
        }
        duel.remove(w);
        if (ok && (!best || cand.val > best.val)) best = cand;
      }
      if (best) return { word: best.w, delay: delayBetween(150, 400, rng), kind: 'outer', proven: true };
    }

    // 3) 안전 수읽기 — 상대 한방·필승 각을 주는 글자는 배제, 그중 압박·미션·장문
    //    이론적으로 좋은 자리(승리 L > 무승부 D > 이기는 자리 W) 순으로 보되,
    //    실제로 위험한 수는 건너뛰고 가장 먼저 확인된 안전한 수를 둔다.
    const statusRank = (c) => (c.status === 'L' ? 0 : c.status === 'D' ? 1 : 2);
    const ranked = safe.map((c) => ({ ...c, rank: statusRank(c) }))
      .sort((a, b) => a.rank - b.rank
        || pressureTier(a.live) - pressureTier(b.live)
        || b.val - a.val);

    let safePick = null;
    let bestFallback = null;
    let checked = 0;
    for (const cand of ranked) {
      if (checked >= 160 || duel.outOfTime()) break;
      checked += 1;
      const { w, end } = cand;
      duel.add(w);
      const dangerKill = duel.killAt(end) !== null;
      const replies = duel.liveCount(end);
      let exact = 0;
      if (dangerKill) exact = 3;
      else if (replies <= 60 && duel.winIn(end, 3)) exact = 2;
      else if (replies <= 16 && duel.winIn(end, 5)) exact = 2;
      duel.remove(w);
      const entry = { ...cand, exact, replies };
      if (!bestFallback || exact < bestFallback.exact
        || (exact === bestFallback.exact && (entry.rank < bestFallback.rank
          || (entry.rank === bestFallback.rank
            && pressureTier(entry.replies) < pressureTier(bestFallback.replies))))) {
        bestFallback = entry;
      }
      if (exact === 0) {
        safePick = entry;
        break;
      }
    }

    const best = safePick || bestFallback || safe[0] || winning[0] || { w: cands[0], val: 0, exact: 0 };
    return {
      word: best.w,
      delay: delayBetween(150, 400, rng),
      kind: best.exact >= 3 ? 'normal' : best.rank === 0 ? 'route' : 'press',
      proven: false,
    };
  }
}
