/**
 * 5단계 봇. 난이도마다 단어를 고르는 방식과 반응이 다르다.
 *
 * Lv.1~4 는 각 단계가 원래 고르던 후보 풀(후속 단어 수·글자 수 한계)을 그대로 두고,
 * **그 풀 안에서만** 미션 중첩·글자 수 점수(`wordValue`)를 챙긴다.
 *  - Lv.1: 가끔 가장 높은 점수의 단어, 나머지는 점수 가중 (한방·4글자 초과 금지)
 *  - Lv.2: 한방(5글자 이하)·장문(4~5글자)·쉬운 단어 풀 안에서 점수 가중
 *  - Lv.3: 한방·유도·압박 풀 유지, 괴물 장문 배제, 유도 풀 안에서 점수 상위 가중
 *  - Lv.4: 한방이면 최고점 한방, 아니면 최소 후속 수가 최우선이고 동률에서만 점수 비교
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

/**
 * 단어 하나의 점수 가치: 글자 수 점수 × 미션 중첩 배율.
 * (엔진의 점수식과 같은 모양 — 길수록, 미션 글자가 겹칠수록 높다)
 */
export function wordValue(w, mission) {
  const len = w.length;
  const hits = mission ? countMission(w, mission) : 0;
  return (len * len + 4 * len) * missionMultiplier(hits);
}

/** 점수가 가장 높은 단어 하나(동률이면 먼저 만난 단어). */
function bestByValue(pool, mission) {
  let best = pool[0];
  let bestVal = wordValue(best, mission);
  for (let i = 1; i < pool.length; i += 1) {
    const val = wordValue(pool[i], mission);
    if (val > bestVal) {
      bestVal = val;
      best = pool[i];
    }
  }
  return best;
}

/**
 * 풀 안에서만 점수·미션 의지를 갖고 고른다.
 *  - 풀은 그대로 두므로 난이도(후속 단어 수) 등급은 바뀌지 않는다.
 *  - 점수가 낮은 단어도 strength 만큼은 남겨 두어, 늘 같은 최고점만 쓰지는 않는다.
 *    strength 0 = 완전 무작위.
 */
function pickByValue(pool, mission, rng, strength = 2) {
  if (pool.length <= 1) return pool[0];
  const vals = new Array(pool.length);
  let min = Infinity;
  let max = -Infinity;
  for (let i = 0; i < pool.length; i += 1) {
    const val = wordValue(pool[i], mission);
    vals[i] = val;
    if (val < min) min = val;
    if (val > max) max = val;
  }
  if (max === min || strength <= 0) return pick(pool, rng);
  const span = max - min;
  let total = 0;
  for (let i = 0; i < vals.length; i += 1) {
    const weight = 1 + strength * ((vals[i] - min) / span);
    vals[i] = weight;
    total += weight;
  }
  let r = rng() * total;
  for (let i = 0; i < pool.length; i += 1) {
    r -= vals[i];
    if (r <= 0) return pool[i];
  }
  return pool[pool.length - 1];
}

/**
 * 길이 상한을 지키는 풀. 상한 이하 단어가 하나라도 있으면 그 안에서만 고르고,
 * 그 글자로 낼 수 있는 단어가 전부 장문일 때만 가장 짧은 것을 쓴다.
 */
function fitPool(pool, limit) {
  const short = pool.filter((w) => w.length <= limit);
  if (short.length) return short;
  let best = pool[0];
  for (const w of pool) if (w.length < best.length) best = w;
  return [best];
}

/**
 * 한방(즉사) 후보 고르기.
 * 어느 것을 써도 그 판은 바로 끝나므로 난이도는 같다 — 그러니 점수·미션을 챙긴다.
 */
function killByValue(pool, mission, limit) {
  return bestByValue(fitPool(pool, limit), mission);
}

const pressureTier = (n) => (n <= 1 ? 0 : n <= 3 ? 1 : n <= 10 ? 2 : n <= 40 ? 3 : n <= 200 ? 4 : 5);

/**
 * Lv.5 지옥의 수읽기 예산.
 * 노드 수(budget)와 시간(deadline)을 함께 두어, 모바일에서도 응답 텀이 끊기지 않게 한다.
 */
const HELL = {
  budget: 200_000,      // 한 수에 허용하는 탐색 노드 수
  deadlineMs: 220,      // 시간 상한(모바일 포함 안전선)
  winCandidates: 56,    // 강제 필승 후보 검증 상한 (14 → 56)
  winPlies: 5,          // 강제 필승 탐색 깊이
  winPliesDeep: 7,      // 상대 응수가 적은 분기는 더 깊게
  deepLive: 14,         // 이 수 이하로 좁아진 자리는 깊게 본다
  safeCandidates: 240,  // 안전 후보 전수 평가 상한
  replyLimit: 96,       // 독배 평가에서 뜯어보는 상대 응수 수
};

/** 응수가 적을수록 숨통이 조여진다. */
const squeezeBonus = (n) => (n <= 1 ? 30 : n <= 3 ? 24 : n <= 10 ? 14 : n <= 40 ? 6 : 0);

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
    this.version = 0;
    this.killCache = new Map();
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
    this.version += 1;
    return true;
  }

  remove(word) {
    if (!this.used.delete(word)) return false;
    this.bump(word.charAt(0), -1);
    this.version += 1;
    return true;
  }

  outOfTime() {
    return this.visits > this.budget || performance.now() > this.deadline;
  }

  /** 이 글자로 아직 낼 수 있는 단어 수(이미 나온 단어 제외). */
  liveCount(ch) {
    let n = 0;
    for (const s of allowedStarts(ch)) {
      n += this.dict.dictStartCount(s) - (this.starts.get(s) || 0);
    }
    return n > 0 ? n : 0;
  }

  /** 이 글자에서 바로 낼 수 있는 한방 단어(상대 후보 0). */
  killAt(ch) {
    const hit = this.killCache.get(ch);
    if (hit && hit.v === this.version) {
      this.visits += 1;
      return hit.res;
    }
    const res = this.killAtSlow(ch);
    this.killCache.set(ch, { v: this.version, res });
    return res;
  }

  killAtSlow(ch) {
    const shots = this.dict.shotWords(ch);
    if (shots) {
      for (const w of shots) {
        this.visits += 1;
        if (!this.used.has(w) && this.dict.countFrom(lastOf(w)) === 0) return w;
      }
    }
    // 한방 목록에 없는 경우(후속 단어가 모두 소진된 자리)는 후보가 적을 때만 직접 확인
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

  /**
   * 이 글자에서 plies 수 안에 강제로 이길 수 있는 수.
   * 상대 응수를 하나도 빼먹지 않고 실제로 확인하며, 응수가 적은 분기는 더 깊게 본다.
   */
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
          if (this.outOfTime()) { ok = false; break; }
          this.add(r);
          const e2 = lastOf(r);
          const next = this.findWin(
            e2,
            this.liveCount(e2) <= HELL.deepLive ? plies : Math.min(plies, 3),
          );
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

  /**
   * 독배 점수: 내가 이 수를 두고 상대가 최선으로 받아쳤을 때 봇에게 남는 이득(미니맥스 최악값).
   *  상대 응수가 적을수록, 그리고 그 응수들이 전부 봇에게 유리한 자리로 돌아올수록 높다.
   *   100 = 상대가 무엇을 두든 봇에게 즉사 한방이 생긴다
   *    80 = 봇이 이기는 자리(W)로 돌아온다 · 40 = 무승부(D) · 0 = 지는 자리(L)
   *  -100 = 상대 응수 하나로 봇이 막힌다 → 이 수는 지는 수
   */
  /**
   * 응수 평가용 빠른 한방 판정. 후속이 아주 좁을 때만 후보를 직접 훑는다.
   * (위험한 수 배제는 killAt 으로 정확히 하고, 여기서는 모양만 본다)
   */
  quickKill(ch) {
    const shots = this.dict.shotWords(ch);
    if (shots) {
      for (const w of shots) {
        this.visits += 1;
        if (!this.used.has(w) && this.dict.countFrom(lastOf(w)) === 0) return w;
      }
    }
    if (this.liveCount(ch) <= 8) {
      for (const w of this.dict.candidatesFor(ch, this.used, 8)) {
        this.visits += 1;
        const end = lastOf(w);
        if (this.dict.countFrom(end) === 0) return w;
        this.add(w);
        const left = this.liveCount(end);
        this.remove(w);
        if (!left) return w;
      }
    }
    return null;
  }

  worstReplyScore(ch) {
    const n = this.liveCount(ch);
    if (!n) return { score: 160, worstWord: null, replies: 0 };
    const replies = this.dict.candidatesFor(ch, this.used, Math.min(n, HELL.replyLimit));
    let worst = Infinity;
    let worstWord = null;
    for (let i = 0; i < replies.length; i += 1) {
      const r = replies[i];
      const e2 = lastOf(r);
      this.visits += 1;
      let v;
      if (this.liveCount(e2) === 0) v = -100;
      else if (this.quickKill(e2)) v = 100;
      else {
        const status = this.dict.graphStatus(e2);
        v = status === 'W' ? 80 : status === 'D' ? 40 : 0;
        const mine = this.liveCount(e2);
        if (mine <= 3) v -= 12;
        else if (mine <= 12) v -= 6;
      }
      if (v < worst) {
        worst = v;
        worstWord = r;
      }
      if (worst <= -100) break;
    }
    return { score: worst + squeezeBonus(n), worstWord, replies: n };
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
      // 한방이 여러 개면 무작위가 아니라 미션 중첩·점수가 가장 높은 한방을 쓴다.
      // (한방이면 어느 것이든 즉사라서 난이도는 그대로다)
      if (oneShot.length) {
        return { word: bestByValue(oneShot, mission), delay: delayBetween(200, 480, rng), kind: 'oneshot' };
      }
      // 한방이 없으면: 상대가 받아치기 가장 어려운 최소 후속 단어가 여전히 최우선.
      // 같은 최소 후속 수(동률) 안에서만 미션 중첩·글자 수 점수로 고득점 단어를 고른다.
      let minEnd = Infinity;
      for (const w of cands) {
        const n = endCount(w);
        if (n < minEnd) minEnd = n;
      }
      const tight = [];
      for (const w of cands) if (endCount(w) === minEnd) tight.push(w);
      return { word: bestByValue(tight, mission), delay: delayBetween(200, 500, rng), kind: 'outer' };
    }

    if (this.level === 3) {
      if (turn >= 4 && oneShot.length && rng() < 0.85) {
        return { word: killByValue(oneShot, mission, 6), delay: delayBetween(700, 1300, rng), kind: 'oneshot' };
      }
      const induced = cands.filter((w) => {
        const n = endCount(w);
        return n >= 1 && n <= 3;
      });
      if (induced.length && rng() < 0.7) {
        return {
          word: pickByValue(fitPool(induced, 6), mission, rng, 3),
          delay: delayBetween(700, 1400, rng),
          kind: 'press',
        };
      }
      const tough = cands.filter((w) => {
        const n = endCount(w);
        return n > 0 && n <= 30;
      });
      const pool = tough.length ? tough : cands.filter((w) => endCount(w) > 0);
      return {
        word: pickByValue(fitPool(pool.length ? pool : cands, 6), mission, rng, 3),
        delay: delayBetween(750, 1400, rng),
        kind: 'press',
      };
    }

    if (this.level === 2) {
      // 한방은 5글자 이하일 때만 — 그런 한방이 없으면 이 턴은 한방 없이 간다(보통 난이도는 장문 금지)
      const kills = oneShot.filter((w) => w.length <= 5);
      if (turn > 3 && kills.length && rng() < 0.1) {
        return { word: bestByValue(kills, mission), delay: delayBetween(1000, 1700, rng), kind: 'oneshot' };
      }
      // 장문은 4~5글자까지만 — 보통 난이도가 16글자 같은 초장문을 쓰지 않게 한다
      const longWords = cands.filter((w) => w.length >= 4 && w.length <= 5 && endCount(w) > 5);
      if (longWords.length && rng() < 0.22) {
        return {
          word: pickByValue(longWords, mission, rng, 2),
          delay: delayBetween(1000, 1800, rng),
          kind: 'long',
        };
      }
      const easy = cands.filter((w) => w.length <= 3 && endCount(w) >= 25);
      const pool = easy.length ? easy : cands.filter((w) => endCount(w) > 0);
      return {
        word: pickByValue(fitPool(pool.length ? pool : cands, 5), mission, rng, 2),
        delay: delayBetween(1000, 1800, rng),
        kind: 'normal',
      };
    }

    // 레벨 1: 한방 금지, 후속 단어가 많은 2~3글자.
    // 쉬움답게 풀은 그대로 두고, 그 안에서 미션 글자·3글자를 가끔 더 챙기는 정도만.
    const spare = (pool) => (rng() < 0.2 ? bestByValue(pool, mission) : pickByValue(pool, mission, rng, 1.5));

    const safe = cands.filter((w) => {
      const n = endCount(w);
      return n >= 40 && w.length <= 3;
    });
    if (safe.length) {
      return { word: spare(safe), delay: delayBetween(1500, 2500, rng), kind: 'normal' };
    }

    const safer = cands.filter((w) => {
      const n = endCount(w);
      return n >= 15 && w.length <= 4;
    });
    if (safer.length) {
      return { word: spare(safer), delay: delayBetween(1500, 2500, rng), kind: 'normal' };
    }

    const notDead = cands.filter((w) => endCount(w) > 0);
    return {
      word: spare(fitPool(notDead.length ? notDead : cands, 4)),
      delay: delayBetween(1500, 2500, rng),
      kind: 'normal',
    };
  }

  /* ── Lv.5 지옥 ──────────────────────────────────────────── */

  /**
   * Lv.5 지옥.
   *  1) 한방 즉사 → 2) 강제 필승(3~7수, used 로 새로 좁아진 함정 포함) →
   *  3) 안전 후보 전수 평가(독배 점수) → 4) 그래도 없으면 가장 덜 나쁜 수.
   */
  chooseHell({ needChar, used, cands, mission }) {
    const dict = this.dict;
    const rng = this.rng;
    const duel = new Duel(dict, used);
    duel.budget = HELL.budget;
    duel.deadline = performance.now() + HELL.deadlineMs;

    const valueOf = (w) => wordValue(w, mission);

    const kills = [];
    const traps = new Map();     // 끝 글자별: 상대가 죽는 자리로 보내는 최고 점수 단어
    const endBest = new Map();   // 끝 글자별 최고 점수 단어

    // 한 번 훑으면서 후보를 성격별로 나눈다 (후보 수 × O(1))
    for (const w of cands) {
      const end = lastOf(w);
      const val = valueOf(w);
      const live = duel.liveCount(end);
      if (live === 0) {                       // used 를 반영해도 상대가 낼 단어가 없다
        kills.push({ w, val });
        continue;
      }
      const status = dict.graphStatus(end);
      const depth = dict.graphDepth(end);
      // 정적 패배 노드 + 이미 나온 단어 때문에 1~2수로 좁아진 함정 음절
      if (status === 'L' || live <= 2) {
        const prev = traps.get(end);
        if (!prev || val > prev.val) traps.set(end, { w, end, val, live, status, depth });
      }
      const prev = endBest.get(end);
      if (!prev || val > prev.val) endBest.set(end, { w, end, val, live, status, depth });
    }
    const safe = [...endBest.values()];

    // 1) 한방 즉사 — 미션 중첩·장문 우선
    if (kills.length) {
      let best = kills[0];
      for (const k of kills) if (k.val > best.val) best = k;
      return { word: best.w, delay: delayBetween(150, 400, rng), kind: 'oneshot' };
    }

    // 2) 강제 필승 — 상대의 모든 응수를 실제 수로 확인한다.
    //    함정(응수 1~2개)부터, 깊이는 3수 → 5수 → 7수까지.
    if (traps.size) {
      const list = [...traps.values()].sort((a, b) => a.live - b.live
        || (a.status === 'L' ? 0 : 1) - (b.status === 'L' ? 0 : 1)
        || a.depth - b.depth
        || b.val - a.val);
      let pick = null;
      let tested = 0;
      for (const cand of list) {
        if (tested >= HELL.winCandidates || duel.outOfTime()) break;
        tested += 1;
        duel.add(cand.w);
        const replies = dict.candidatesFor(cand.end, duel.used);
        const verifyAt = (plies) => {
          for (const r of replies) {
            if (duel.outOfTime()) return false;
            duel.add(r);
            const e2 = lastOf(r);
            const win = duel.findWin(e2, plies);
            duel.remove(r);
            if (!win) return false;
          }
          return true;
        };
        let proof = 0;
        if (!replies.length) proof = 3;
        else {
          for (const plies of [3, HELL.winPlies, HELL.winPliesDeep]) {
            if (verifyAt(plies)) { proof = plies; break; }
            if (duel.outOfTime()) break;
          }
        }
        duel.remove(cand.w);
        if (!proof) continue;
        const entry = { ...cand, proof, replies: replies.length };
        if (!pick || entry.proof < pick.proof
          || (entry.proof === pick.proof && entry.val > pick.val)) {
          pick = entry;
        }
      }
      if (pick) {
        return {
          word: pick.w,
          delay: delayBetween(150, 400, rng),
          kind: 'outer',
          proof: pick.proof,
          proven: pick.proof === 3,
        };
      }
    }

    // 3) 안전 후보 전수 평가 — 첫 안전 수에서 멈추지 않고, 상대의 모든 응수를 뜯어
    //    가장 숨통을 조이는 '독배'를 고른다.
    const statusRank = (c) => (c.status === 'L' ? 0 : c.status === 'D' ? 1 : 2);
    const ranked = safe.map((c) => ({ ...c, rank: statusRank(c) }))
      .sort((a, b) => a.rank - b.rank
        || pressureTier(a.live) - pressureTier(b.live)
        || b.val - a.val);

    const safeScored = [];
    const unsafe = [];
    let checked = 0;
    for (const cand of ranked) {
      if (checked >= HELL.safeCandidates || duel.outOfTime()) break;
      checked += 1;
      const { w, end } = cand;
      duel.add(w);
      const live = duel.liveCount(end);
      let exact = 0;
      if (duel.killAt(end)) exact = 3;
      else if (live <= 60 && duel.winIn(end, 3)) exact = 2;
      else if (live <= HELL.deepLive && duel.winIn(end, HELL.winPlies)) exact = 2;
      let devious = null;
      if (exact === 0 && live && live <= HELL.replyLimit) {
        devious = duel.worstReplyScore(end);
        // 상대 응수 하나가 봇을 끝내는 수 → 실제로는 안전하지 않다
        if (devious.score <= -100 + squeezeBonus(live)) exact = 4;
      }
      duel.remove(w);
      const entry = {
        ...cand, exact, replies: live, devious,
        mate: devious ? devious.score : 30 + squeezeBonus(live),
        checked,
      };
      if (exact === 0) safeScored.push(entry);
      else unsafe.push(entry);
    }

    if (safeScored.length) {
      // 그래프 상태(이론적 승패)를 먼저 보고, 같은 등급 안에서 독배 점수를 쓴다.
      safeScored.sort((a, b) => a.rank - b.rank
        || b.mate - a.mate
        || a.replies - b.replies
        || b.val - a.val);
      const best = safeScored[0];
      return {
        word: best.w,
        delay: delayBetween(150, 400, rng),
        kind: best.rank === 0 ? 'route' : 'press',
        proven: false,
      };
    }

    // 4) 안전한 수가 하나도 없는 자리 — 가장 덜 나쁜 수
    let fallback = null;
    const pool = unsafe.length ? unsafe : ranked.map((c) => ({ ...c, exact: 0, replies: c.live }));
    for (const entry of pool) {
      if (!fallback || entry.exact < fallback.exact
        || (entry.exact === fallback.exact && entry.rank < fallback.rank)
        || (entry.exact === fallback.exact && entry.rank === fallback.rank
          && pressureTier(entry.replies) < pressureTier(fallback.replies))) {
        fallback = entry;
      }
    }
    const best = fallback || { w: cands[0], exact: 4, rank: 2, replies: 0 };
    return {
      word: best.w,
      delay: delayBetween(150, 400, rng),
      kind: 'normal',
      proven: false,
    };
  }
}

/**
 * Lv.5 지옥의 선공 오프닝.
 * 봇이 먼저 두는 판에서 아무 글자나 잡지 않고, 봇이 유리한 자리로 시작을 끊는다.
 *  - 그 글자로 낼 단어가 있어야 한다(countFrom > 0).
 *  - 봇이 0수 한방으로 1초 만에 끝내는 자리(W1)는 피한다.
 *  - 봇이 이기는 자리(W3·W5·W7) → 무승부(D) → 지는 자리(L) 순으로 고른다.
 *  - 같은 등급이면 더 빨리 끝나는 자리, 그다음 봇이 고를 수 있는 수가 많은 자리.
 */
export function pickHellOpening(dict, rng = Math.random) {
  const starts = dict.goodStartChars(60);
  if (!starts.length) return null;
  const tiers = [[], [], []]; // 봇이 이기는 자리 / 무승부 / 지는 자리
  for (const ch of starts) {
    const live = dict.countFrom(ch);
    if (live <= 0) continue;
    const status = dict.graphStatus(ch);
    const depth = dict.graphDepth(ch);
    if (status === 'W') {
      if (depth <= 1) continue; // 즉사 한방으로 1초 만에 끝나는 판은 피한다
      tiers[0].push({ ch, live, depth });
    } else if (status === 'D') {
      tiers[1].push({ ch, live, depth: 99 });
    } else {
      tiers[2].push({ ch, live, depth: 99 });
    }
  }
  const pool = tiers.find((t) => t.length);
  if (!pool) return starts[Math.floor(rng() * starts.length)] || null;
  pool.sort((a, b) => a.depth - b.depth || b.live - a.live);
  const top = pool.filter((c) => c.depth === pool[0].depth);
  return top[Math.floor(rng() * top.length)].ch;
}
