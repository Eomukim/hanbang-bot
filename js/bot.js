/**
 * 5단계 봇. 난이도마다 단어를 고르는 방식과 반응이 다르다.
 *
 * Lv.5 지옥은 페널티 없이 순수하게 세게 둔다.
 *  - 빌드 타임(`build/build_data.py`)에 715,715단어 음절 그래프를 역방향 분석해 둔
 *    승리/패배/무승부 상태(`dict.graphStatus`)와 한방 단어 목록(`dict.shotWords`)을 읽고,
 *  - 실제로 이미 나온 단어(`used`)를 반영해 수를 검증한 뒤
 *    한방 즉사 → 강제 필승 → 위험한 수 배제 → 압박·미션·장문 순으로 고른다.
 */

import {
  allowedStarts, missionHits as countMission, missionMultiplier,
  decompose, compose, twoeumOf,
} from './rules.js';

export const LEVELS = [
  {
    id: 1,
    name: '쉬움',
    face: '🙂',
    label: 'Lv.1 순한 봇',
    desc: '한방 금지 · 일상 단어 2~3글자',
    botName: '잇다 주니어',
  },
  {
    id: 2,
    name: '보통',
    face: '😐',
    label: 'Lv.2 보통',
    desc: '일상 단어 위주 · 가끔 긴 단어',
    botName: '잇다 루키',
  },
  {
    id: 3,
    name: '어려움',
    face: '😏',
    label: 'Lv.3 어려움',
    desc: '외통수로 몰아넣고 결정타',
    botName: '잇다 마스터',
  },
  {
    id: 4,
    name: '극악',
    face: '😈',
    label: 'Lv.4 극악',
    desc: '한방 단어가 있으면 100% 즉사',
    botName: '잇다 극악',
  },
  {
    id: 5,
    name: '지옥',
    face: '💀',
    label: 'Lv.5 지옥',
    desc: '필승 경로·수읽기로 도망칠 곳을 지움',
    botName: '잇다 지옥',
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

/** 어인정 2 · 방언 8 · 옛말 16 · 문화어 32 — 일상어로 치지 않는 표제어 비트 */
const NOT_EVERYDAY = 2 | 8 | 16 | 32;

/**
 * 문장 조각처럼 생긴 표제어(오픈DB에는 띄어쓰기를 지운 문장·대사가 섮여 있다).
 *  예: 다시해줘 · 관둬 · 가슴은아니까 · 빵만으로는살수없다
 *  사전에서 지우지는 않는다(플레이어가 직접 내면 그대로 인정) — 봇이 먼저 꺼내지만 않게 한다.
 */
const SENTENCE_END = /(해줘|해봐|해요|어요|아요|네요|지요|니까|지만|면서|려고|습니다|한다|된다|했다|였다|이다|인데|라고|다고|구나|더라|거야|볼래|줄래|줘|둬)$/;
/** 같은 글자만 되풀이된 표제어(가가가·둬둬둬). */
const SAME_CHAR = /^(.)\1{2,}$/;

/**
 * 단어가 사람에게 얼마나 '보통 말'인가. 낮을수록 자연스럽다.
 *  0 = 일상 명사(1~3단계)   1 = 일상 외래어(5~7단계)   2 = 표준어 2~4자
 *  3 = 표준어 5~6자 또는 어인정·방언·옛말·문화어   4 = 문장형·되풀이·7~9자   5 = 10자 이상
 *
 * 난이도는 '상대에게 남기는 후속 단어 수'로 만들고, 같은 자리에서 고를 수 있으면
 * 언제나 이 등급이 낮은 쪽을 먼저 고른다. 그래서 79만 단어 가운데 낯선 어인정
 * 고유명사·문장형 표제어가 먼저 튀어나오지 않는다(사전에서는 빼지 않는다).
 */
export function naturalness(dict, word) {
  const tier = dict.easyTier(word);
  if (tier) return tier <= 3 ? 0 : 1;
  if (dict.flagOf(word) & NOT_EVERYDAY) return 4;
  const n = word.length;
  if (n <= 6 && (SENTENCE_END.test(word) || SAME_CHAR.test(word))) return 4;
  if (n <= 4) return 2;
  if (n <= 6) return 3;
  if (n <= 9) return 4;
  return 5;
}

/**
 * 후보 중 가장 자연스러운 등급의 무리만 남긴다.
 * 무리가 너무 좁으면(2개 미만) 한 등급 넓혀 매 판 같은 단어에 고정되지 않게 한다.
 */
function naturalBand(dict, list, maxRank = 2) {
  if (list.length <= 1) return list;
  const scored = [];
  let best = 9;
  for (const w of list) {
    const r = naturalness(dict, w);
    if (r < best) best = r;
    scored.push({ w, r });
  }
  let band = scored.filter((c) => c.r === best);
  if (band.length < 2) band = scored.filter((c) => c.r <= Math.min(best + 1, Math.max(best, maxRank)));
  if (!band.length) band = scored;
  return band.map((c) => c.w);
}

/**
 * 일상어 점수(낮을수록 쉬움). Lv.1·Lv.2 가 같은 기준을 쓴다.
 *  - 표준어 단계(1~3) → 외래어 단계(5~7)
 *  - 끝 글자에 일상 단어가 많이 이어지는 쪽(사·수·리·다처럼 다음 단어를 떠올리기 쉬운 글자)
 *  - 후속 단어가 많은 글자(300 / 100 / 40 이상)
 *  - 2~3글자 우선
 */
function easyScore(dict, word) {
  const tier = dict.easyTier(word);
  const end = lastOf(word);
  const n = dict.countFrom(end);
  const bucket = n >= 300 ? 0 : n >= 100 ? 1 : n >= 40 ? 2 : 3;
  const tierRank = tier <= 3 ? (tier - 1) * 0.5 : 4 + (tier - 5) * 0.5;
  const easyNext = dict.easyCountFrom(end);
  const flow = easyNext >= 12 ? 0 : easyNext >= 6 ? 0.5 : easyNext >= 3 ? 1.5 : easyNext >= 1 ? 3 : 5;
  return tierRank + flow + bucket + (word.length <= 3 ? 0 : 1);
}

const pressureTier = (n) => (n <= 1 ? 0 : n <= 3 ? 1 : n <= 10 ? 2 : n <= 40 ? 3 : n <= 200 ? 4 : 5);

/**
 * Lv.5 지옥의 수읽기 예산.
 * 노드 수(budget)와 시간(deadline)을 함께 두어, 모바일에서도 응답 텀이 끊기지 않게 한다.
 *
 * 안전(상대 한방) 판정은 표본 없이 전수로 한다 — `killAt` 이 그 자리의 단어를 끝까지 훑어
 * 상대가 낼 수 있는 한방이 하나라도 있는지 본다. `replyLimit` 은 위험 수를 '점수로 매기는'
 * 독배 평가에서만 쓰는 표본 수다(전수로 늘리면 넓은 자리의 점수가 모두 바닥에 붙어
 * 후보 구분이 사라지고, 400판 맞대결에서 승률이 떨어졌다).
 */
const HELL = {
  budget: 900_000,      // 한 수에 허용하는 탐색 노드 수
  deadlineMs: 700,      // 시간 상한(모바일 포함 안전선)
  winCandidates: 140,   // 강제 필승 후보 검증 상한
  winPlies: 5,          // 강제 필승 탐색 깊이
  winPliesDeep: 9,      // 상대 응수가 적은 분기는 더 깊게
  deepLive: 14,         // 이 수 이하로 좁아진 자리는 깊게 본다
  safeCandidates: 320,  // 안전 후보 전수 평가 상한
  replyLimit: 96,       // 독배 평가에서 뜯어보는 상대 응수 수
};

/** 응수가 적을수록 숨통이 조여진다. */
const squeezeBonus = (n) => (n <= 1 ? 30 : n <= 3 ? 24 : n <= 10 ? 14 : n <= 40 ? 6 : 0);

/** 초성 인덱스(한글 음절 분해). */
const IEUNG = 11;
const RIEUL = 5;
const NIEUN = 2;

/**
 * 이 글자로 시작하는 단어를 낼 수 있는 '이어야 할 글자'들(두음법칙 포함, 최대 3개).
 *  예: '이'로 시작하는 단어는 '이'·'리'·'니' 뒤에서 모두 낼 수 있다.
 *  거꾸로 '리'가 소진되면 '이'·'니'로 끝난 자리도 함께 막힌다.
 */
function acceptingNodes(ch) {
  const out = [ch];
  const parts = decompose(ch);
  if (!parts) return out;
  const [cho, jung, jong] = parts;
  if (cho === IEUNG) {
    for (const c of [RIEUL, NIEUN]) {
      const y = compose(c, jung, jong);
      if (twoeumOf(y) === ch) out.push(y);
    }
  } else if (cho === NIEUN) {
    const y = compose(RIEUL, jung, jong);
    if (twoeumOf(y) === ch) out.push(y);
  }
  return out;
}

/**
 * Lv.5 지옥의 수읽기.
 * 후보 목록·사용된 단어·빌드 타임 그래프를 함께 보면서, 실제 판(used)에서 검증한 수만 둔다.
 */
class Duel {
  constructor(dict, used) {
    this.dict = dict;
    this.used = new Set(used);
    this.starts = new Map();
    this.exhausted = new Set();
    for (const w of this.used) this.bump(w.charAt(0), 1);
    this.visits = 0;
    this.budget = 0;
    this.deadline = 0;
    this.version = 0;
    this.killCache = new Map();
    this.deadSet = new Set();
    this.deadVersion = -1;
  }

  bump(ch, d) {
    const n = (this.starts.get(ch) || 0) + d;
    if (n > 0) this.starts.set(ch, n);
    else this.starts.delete(ch);
    // 그 글자로 시작하는 단어를 이번 판에서 다 썼는가
    if (n >= this.dict.dictStartCount(ch)) this.exhausted.add(ch);
    else this.exhausted.delete(ch);
  }

  /**
   * 판에서 단어가 다 나가 새로 막힌 글자(후속 단어 0).
   * 시작 글자 하나가 통째로 소진되면 그 글자로 시작해야 하는 자리도 함께 죽는다.
   * (두음법칙으로 받아 주는 글자까지 본다)
   */
  liveDead() {
    if (this.deadVersion === this.version) return this.deadSet;
    const out = this.deadSet;
    out.clear();
    for (const s of this.exhausted) {
      for (const y of acceptingNodes(s)) {
        if (this.liveCount(y) === 0) out.add(y);
      }
    }
    this.deadVersion = this.version;
    return out;
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

  /** 이 글자에서 둘 차례인 쪽이 낼 수 있는 한방 단어(없으면 null) — 전수 확인. */
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
    const dict = this.dict;
    const shots = dict.shotWords(ch);
    if (shots) {
      for (const w of shots) {
        this.visits += 1;
        if (!this.used.has(w)) return w;
      }
    }
    // 판에서 새로 막힌 글자로 끝나는 단어는 목록에 없다 → 그 자리의 단어를 전수로 훑는다
    const dead = this.liveDead();
    if (!dead.size) return null;
    for (const s of allowedStarts(ch)) {
      const r = dict.rangeOf(s);
      if (!r) continue;
      for (let i = r[0]; i < r[1]; i += 1) {
        const w = dict.words[i];
        this.visits += 1;
        if (this.used.has(w)) continue;
        if (dead.has(lastOf(w))) return w;
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
  choose({ needChar, used, turn, mission = null, guard = false }) {
    const all = this.dict.candidatesFor(needChar, used);
    if (!all.length) return null;
    // 배려모드: 첫 5수 동안은 한방 단어를 고르지 않는다. 고를 수 있는 수가 없으면
    // 규칙대로 막힌 것으로 둔다(한방을 쓰지 않는다).
    const cands = guard ? this.guardedWords(all, used) : all;
    if (!cands.length) return null;
    if (this.level === 5) return this.chooseHell({ needChar, used, cands, mission });

    const dict = this.dict;
    const rng = this.rng;
    const endCount = (w) => dict.countFrom(w.charAt(w.length - 1));
    const oneShot = cands.filter((w) => endCount(w) === 0);

    if (this.level === 4) {
      // 한방이 있으면 100% 즉사(기존 강도 유지). 다만 무엇이든 되는 경우에는
      // 관싕·다봊 같은 낯선 표제어 대신 보통 말을 먼저 쓴다.
      if (oneShot.length) {
        return { word: pick(naturalBand(dict, oneShot, 3), rng), delay: delayBetween(200, 480, rng), kind: 'oneshot' };
      }
      // 한방이 없으면: 상대 후속 단어가 가장 적은 자리로 몰아넣는다.
      // 같은 최소 후속 수(모자라면 한 단계 위) 안에서 자연스러운 단어를 골라
      // 매 판 다른 수를 둔다. 강도는 끝 글자의 후속 수가 결정하므로 그대로다.
      let minEnd = Infinity;
      for (const w of cands) {
        const n = endCount(w);
        if (n < minEnd) minEnd = n;
      }
      let pool = cands.filter((w) => endCount(w) === minEnd);
      if (pool.length < 3) pool = cands.filter((w) => endCount(w) <= minEnd + 2);
      return { word: pick(naturalBand(dict, this.flowing(pool), 2), rng), delay: delayBetween(200, 500, rng), kind: 'outer' };
    }

    if (this.level === 3) {
      // 어려움: 보통 말로 두면서 판이 길어질수록 점점 조여 온다.
      //  1~3수는 넉넉한 자리(후속 25~200), 4~6수는 6~60, 7수부터 1~25로 좁힌다.
      //  8수 이후에야 확률적으로 한방으로 마무리한다. 예전에는 4수부터 85% 확률로
      //  한방·후속 1~3 자리를 써서 3수 만에 끝났고, 그 단어도 관싕·곰븨님븨 같은
      //  괴상한 표제어였다.
      const clean = this.noVerb(this.plain(cands)).filter((w) => endCount(w) > 0);
      const natural = clean.length ? clean : cands.filter((w) => endCount(w) > 0);

      const cap = turn <= 2 ? 200 : turn <= 5 ? 60 : 25;
      const floor = turn <= 2 ? 30 : turn <= 5 ? 8 : 1;
      if (turn >= 10 && rng() < 0.25) {
        // 마무리 한방. natural 은 '후속이 남은 단어'만 남긴 목록이라 여기서 쓰면
        // 늘 비어 있었다(한방 분기가 한 번도 실행되지 않던 자리). 원래 후보에서 고른다.
        const shots = naturalBand(dict, this.noVerb(this.plain(oneShot)), 3);
        if (shots.length) {
          return { word: pick(shots, rng), delay: delayBetween(700, 1300, rng), kind: 'oneshot' };
        }
      }
      // 6수부터는 가끔 가장 좁은 자리(후속 1~4)를 골라 외통수로 몰아넣는다.
      // 나머지는 4~25로 넓게 둬서 Lv.4·5처럼 숨 막히지는 않게 한다.
      const tight = turn >= 6 && rng() < 0.55
        ? natural.filter((w) => {
          const n = endCount(w);
          return n >= 1 && n <= 4 && naturalness(dict, w) <= 2;
        })
        : [];
      if (tight.length) return { word: pick(tight, rng), delay: delayBetween(700, 1400, rng), kind: 'press' };

      // 기본은 '압박 가중 추첨': 후속이 적은 글자로 끝나는 단어일수록 자주 뽑는다.
      // 어떤 무리에서 뽑을지는 먼저 정한다 — 65%는 일상 단어, 나머지는 일반 표준어.
      // (사전 전체에서 무게만 주면 30만 개의 낯선 4글자 단어가 일상 단어를 덮어 버린다.)
      // 판이 길어질수록(sharp↑) 조여 오고, 같은 자리에서도 매번 다른 단어가 나온다.
      const sharp = turn <= 2 ? 0.25 : turn <= 5 ? 0.4 : 0.55;
      const useEveryday = rng() < 0.75;
      const list = [];
      const weights = [];
      let total = 0;
      for (const w of natural) {
        const n = endCount(w);
        if (n < floor || n > Math.max(cap, 400)) continue;
        const rank = naturalness(dict, w);
        if (useEveryday ? rank > 1 : rank !== 2) continue;
        // 일반 표준어는 '다음 수로 일상 단어를 댈 수 있는 글자'로 끝나는 것만 고른다.
        // (브랜드·어인정 이름은 드문 글자로 끝나서 여기서 걸러진다)
        if (!useEveryday && dict.easyCountFrom(w.charAt(w.length - 1)) < 1) continue;
        total += 1 / Math.pow(n + 40, sharp);
        list.push(w);
        weights.push(total);
      }
      if (!list.length) {
        const fallback = naturalBand(dict, natural, 3);
        return { word: pick(fallback.length ? fallback : cands, rng), delay: delayBetween(700, 1400, rng), kind: 'press' };
      }
      let roll = rng() * total;
      let idx = 0;
      while (idx < list.length - 1 && weights[idx] < roll) idx += 1;
      return { word: list[idx], delay: delayBetween(700, 1400, rng), kind: 'press' };
    }

    if (this.level === 2) {
      // 초반(3턴 이하)에는 한방을 두지 않는다. 이후에도 10% 정도만, 그것도 짧고 일상적인 단어로.
      if (turn > 3 && oneShot.length && rng() < 0.1) {
        const shots = this.calmShots(oneShot);
        if (shots.length) return { word: pick(shots, rng), delay: delayBetween(1000, 1700, rng), kind: 'oneshot' };
      }
      // 가끔 장문(4~6글자): 낯선 표제어 대신 일상 명사를 먼저 본다.
      const longEasy = cands.filter((w) => dict.easyTier(w) && w.length >= 4 && w.length <= 6 && endCount(w) > 5);
      const longPool = longEasy.length
        ? longEasy
        : naturalBand(dict, this.noVerb(this.plain(cands.filter((w) => w.length >= 4 && w.length <= 6 && endCount(w) > 5))), 2);
      if (longPool.length && rng() < 0.22) {
        return { word: pick(longPool, rng), delay: delayBetween(1000, 1800, rng), kind: 'long' };
      }
      // 본 수: 일상 명사 2~4글자, 후속 단어가 남아 있는 쪽
      const everyday = cands.filter((w) => dict.easyTier(w) && w.length <= 4 && endCount(w) >= 25);
      if (everyday.length) return this.everydayMove(everyday, rng, 'normal', 1000, 1800);
      const everydayThin = cands.filter((w) => dict.easyTier(w) && w.length <= 4 && endCount(w) > 0);
      if (everydayThin.length) return this.everydayMove(everydayThin, rng, 'normal', 1000, 1800);
      const plain = this.noVerb(this.plain(cands.filter((w) => w.length <= 4 && endCount(w) >= 25)));
      if (plain.length) {
        return { word: pick(naturalBand(dict, this.flowing(plain), 2), rng), delay: delayBetween(1000, 1800, rng), kind: 'normal' };
      }
      const thin = this.noVerb(this.plain(cands.filter((w) => w.length <= 4 && endCount(w) > 0)));
      const pool = thin.length ? thin : this.noVerb(this.plain(cands.filter((w) => endCount(w) > 0)));
      return {
        word: pick(naturalBand(dict, this.flowing(pool.length ? pool : cands), 2), rng),
        delay: delayBetween(1000, 1800, rng),
        kind: 'normal',
      };
    }

    // 레벨 1: 한방 금지 · 일상 명사 2~3글자 우선.
    //  일상 명사 풀이 비어 있을 때만 표준어 일반 풀 → 일반 비한방 풀로 내려간다.
    //  '~다'로 끝나는 서술어는 일상 명사가 아니면 쓰지 않는다(다·하다에서 맴도는 판 방지).
    const everyday = cands.filter((w) => dict.easyTier(w) && w.length <= 3 && endCount(w) > 0);
    if (everyday.length) return this.everydayMove(everyday, rng, 'normal', 1500, 2500);

    const everydayAny = cands.filter((w) => dict.easyTier(w) && endCount(w) > 0);
    if (everydayAny.length) return this.everydayMove(everydayAny, rng, 'normal', 1500, 2500);

    const plain = this.noVerb(this.plain(cands.filter((w) => endCount(w) > 0)));
    const safe = plain.filter((w) => {
      const n = endCount(w);
      return n >= 40 && w.length <= 3;
    });
    if (safe.length) {
      return { word: pick(naturalBand(dict, this.flowing(safe), 2), rng), delay: delayBetween(1500, 2500, rng), kind: 'normal' };
    }

    const safer = plain.filter((w) => {
      const n = endCount(w);
      return n >= 15 && w.length <= 4;
    });
    if (safer.length) {
      return { word: pick(naturalBand(dict, this.flowing(safer), 2), rng), delay: delayBetween(1500, 2500, rng), kind: 'normal' };
    }

    if (plain.length) {
      return { word: pick(naturalBand(dict, this.flowing(plain), 2), rng), delay: delayBetween(1500, 2500, rng), kind: 'normal' };
    }

    const notDead = cands.filter((w) => endCount(w) > 0);
    if (notDead.length) {
      return { word: pick(naturalBand(dict, this.flowing(notDead), 2), rng), delay: delayBetween(1500, 2500, rng), kind: 'normal' };
    }

    // 남은 후보가 전부 한방 단어뿐 → 순한 봇은 그런 수를 두지 않는다(막힌 것으로 처리).
    return null;
  }

  /**
   * 배려모드 보호(첫 5수) 중 고를 수 있는 수만 남긴다.
   *  - 사전에 후속 단어가 남아 있어야 한다(끝 글자 후속 0 = 한방 단어 제외).
   *  - 이번 판에서 이미 다 써 버려 상대가 낼 수가 없는 글자도 즉시 한방이므로 제외한다.
   */
  guardedWords(list, used) {
    const dict = this.dict;
    let usedStarts = null;
    const liveAt = (ch) => {
      if (!usedStarts) {
        usedStarts = new Map();
        for (const w of used) {
          const s = w.charAt(0);
          usedStarts.set(s, (usedStarts.get(s) || 0) + 1);
        }
      }
      let n = 0;
      for (const s of allowedStarts(ch)) {
        n += Math.max(0, dict.dictStartCount(s) - (usedStarts.get(s) || 0));
      }
      return n;
    };
    return list.filter((w) => {
      const end = lastOf(w);
      return dict.countFrom(end) > 0 && liveAt(end) > 0;
    });
  }

  /** 방언·옛말·문화어·어인정 표제어를 뺀 표준어 후보만 남긴다. */
  plain(list) {
    const dict = this.dict;
    return list.filter((w) => (dict.flagOf(w) & NOT_EVERYDAY) === 0);
  }

  /**
   * '~다'로 끝나는 서술어를 뺀다(일상 명사는 남긴다).
   * 동사·형용사만 이어 받으면 '두껍다 → 다하다 → 다가가다'처럼 판이 '다'에서 맴돈다.
   */
  noVerb(list) {
    const dict = this.dict;
    return list.filter((w) => !w.endsWith('다') || dict.easyTier(w));
  }

  /**
   * 끝 글자에 일상 단어가 이어지는 후보만 남긴다(없으면 그대로).
   * 낯선 글자에서 어쩔 수 없이 표준어로 내려갈 때, 다음 수는 쉬운 자리로 돌아오게 한다.
   */
  flowing(list) {
    const dict = this.dict;
    const out = list.filter((w) => dict.easyCountFrom(w.charAt(w.length - 1)) >= 3);
    return out.length ? out : list;
  }

  /**
   * Lv.2 가 가끔 쓸 한방 단어: 일상 목록에 있는 짧은(2~3글자) 단어만.
   *  한방 단어는 태생이 ‘끝 글자에 후속 단어가 없는’ 낯선 표제어라(“가녘”·“나노뿝”),
   *  일상 목록에 있는 것만 쓴다. 없으면 한방을 두지 않고 보통 수로 넘긴다.
   */
  calmShots(list) {
    const dict = this.dict;
    return list.filter((w) => w.length <= 3 && dict.easyTier(w));
  }

  /**
   * 일상 어휘 후보 중 가장 쉬운 무리에서 하나를 고른다.
   * 1등 점수 무리가 너무 좁으면(4개 미만) 한 단계씩 넓혀 매 판 단어가 달라지게 한다.
   */
  everydayMove(pool, rng, kind = 'normal', minDelay = 1500, maxDelay = 2500) {
    const dict = this.dict;
    const scored = pool.map((w) => ({ w, s: easyScore(dict, w) }));
    let best = Infinity;
    for (const c of scored) if (c.s < best) best = c.s;
    let band = scored.filter((c) => c.s <= best);
    for (const step of [0.5, 1, 2]) {
      if (band.length >= 4) break;
      band = scored.filter((c) => c.s <= best + step);
    }
    if (!band.length) band = scored;
    return { word: pick(band, rng).w, delay: delayBetween(minDelay, maxDelay, rng), kind };
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

    const valueOf = (w) => {
      // 장문을 좇지 않는다: 6글자를 넘으면 점수를 더 주지 않는다(예전에는 20~30글자
      // 어인정 표제어가 점수 1등이라 늘 그런 단어만 나왔다).
      const len = Math.min(w.length, 6);
      const hits = mission ? countMission(w, mission) : 0;
      return (len * len + 4 * len) * missionMultiplier(hits);
    };

    // 같은 끝 글자 안에서는 자연스러운 단어를 먼저, 그다음 점수(미션·길이) 순으로 고른다.
    const natOf = (w) => naturalness(dict, w);
    const better = (cand, prev) => !prev
      || natOf(cand.w) < natOf(prev.w)
      || (natOf(cand.w) === natOf(prev.w) && cand.val > prev.val);

    const kills = [];
    const traps = new Map();     // 끝 글자별: 상대가 죽는 자리로 보내는 최고 점수 단어
    const endBest = new Map();   // 끝 글자별 최고 점수 단어

    // 한 번 훑으면서 후보를 성격별로 나눈다 (후보 수 × O(1))
    for (const w of cands) {
      const end = lastOf(w);
      const val = valueOf(w);
      const live = duel.liveCount(end);
      if (live === 0) {                       // used 를 반영해도 상대가 낼 단어가 없다
        kills.push({ w, end, val });
        continue;
      }
      const status = dict.graphStatus(end);
      const depth = dict.graphDepth(end);
      const cand = { w, end, val, live, status, depth };
      // 정적 패배 노드 + 이미 나온 단어 때문에 1~2수로 좁아진 함정 음절
      if (status === 'L' || live <= 2) {
        const prev = traps.get(end);
        if (better(cand, prev)) traps.set(end, cand);
      }
      const prev = endBest.get(end);
      if (better(cand, prev)) endBest.set(end, cand);
    }
    const safe = [...endBest.values()];

    // 1) 한방 즉사 — 어떤 한방이든 즉시 승리다. 매번 같은 1등 단어 대신
    //    같은 끝 글자 안에서는 보통 말을 우선하고, 그 무리 안에서 골라 매 판 달라지게 한다.
    if (kills.length) {
      const byEnd = new Map();
      for (const k of kills) {
        const prev = byEnd.get(k.end);
        if (better(k, prev)) byEnd.set(k.end, k);
      }
      const uniq = [...byEnd.values()];
      const pool = naturalBand(dict, uniq.map((k) => k.w), 3);
      const chosen = pick(pool, rng);
      return { word: chosen, delay: delayBetween(150, 400, rng), kind: 'oneshot' };
    }

    // 2) 강제 필승 — 상대의 모든 응수를 실제 수로 확인한다.
    //    함정(응수 1~2개)부터, 깊이는 3수 → 5수 → 7수까지.
    if (traps.size) {
      const list = [...traps.values()].sort((a, b) => a.live - b.live
        || (a.status === 'L' ? 0 : 1) - (b.status === 'L' ? 0 : 1)
        || a.depth - b.depth
        || b.val - a.val);
      // 같은 최단 proof(=같은 깊이의 필승) 후보를 모아 두고 그 안에서 고른다.
      // proof 가 같으면 승리까지의 수가 같으니 강도도 같다.
      const proven = [];
      let bestProof = Infinity;
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
        if (proof < bestProof) {
          bestProof = proof;
          proven.length = 0;
        }
        if (proof === bestProof) proven.push({ ...cand, proof, replies: replies.length });
      }
      if (proven.length) {
        // 같은 필승이라도 상대 응수가 적은 쪽이 더 조인다 → 좁은 쪽을 우선하되,
        // 후보가 너무 적으면 한 단계 넓혀 매 판 달라지게 한다.
        const byReplies = [...proven].sort((a, b) => a.replies - b.replies);
        let band = byReplies.filter((c) => c.replies <= 3);
        if (band.length < 3) band = byReplies.filter((c) => c.replies <= 10);
        if (!band.length) band = byReplies;
        const chosen = pick(band, rng);
        return {
          word: chosen.w,
          delay: delayBetween(150, 400, rng),
          kind: 'outer',
          proof: chosen.proof,
          proven: chosen.proof === 3,
        };
      }
    }

    // 3) 안전 후보 전수 평가 — 첫 안전 수에서 멈추지 않고, 상대의 모든 응수를 뜯어
    //    가장 숨통을 조이는 '독배'를 고른다.
    const statusRank = (c) => (c.status === 'L' ? 0 : c.status === 'D' ? 1 : 2);
    const ranked = safe.map((c) => ({ ...c, rank: statusRank(c), nat: natOf(c.w) }))
      .sort((a, b) => a.rank - b.rank
        || pressureTier(a.live) - pressureTier(b.live)
        || a.nat - b.nat
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
      else if (live <= 400 && duel.winIn(end, 3)) exact = 2;
      else if (live <= 120 && duel.winIn(end, HELL.winPlies)) exact = 2;
      else if (live <= 40 && duel.winIn(end, HELL.winPliesDeep)) exact = 2;
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
      // 안전한 수 중 최상위권(최고 rank · 독배 점수 4점 이내)에서 골라 매 판 달라지게 하고,
      // 같은 조건이면 보통 말(자연스러운 등급이 낮은 쪽)을 먼저 둔다.
      // 안전성(exact === 0: 상대 한방 각 없음)은 후보 조건 자체가 보장한다.
      safeScored.sort((a, b) => a.rank - b.rank
        || b.mate - a.mate
        || a.nat - b.nat
        || a.replies - b.replies
        || b.val - a.val);
      const best = safeScored[0];
      const pool = safeScored.filter((c) => c.rank === best.rank
        && c.mate >= best.mate - 4 && c.nat <= best.nat);
      const chosen = pick(pool.length ? pool : safeScored, rng);
      return {
        word: chosen.w,
        delay: delayBetween(150, 400, rng),
        kind: chosen.rank === 0 ? 'route' : 'press',
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

/** 한글 음절의 초성 자모 19개(쌍자음 포함). */
const CHOSEONG = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'];

/** 끄투가 라운드 첫 초성을 고를 때 쓰는 기본 초성 14개(쌍자음 제외). */
const BASIC_INITIALS = new Set(['ㄱ', 'ㄴ', 'ㄷ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅅ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']);

/** 음절의 초성 자모. 한글이 아니면 null. */
export function initialOf(ch) {
  const k = ch.charCodeAt(0) - 0xac00;
  if (k < 0 || k >= 11172) return null;
  return CHOSEONG[Math.floor(k / 588)];
}

/**
 * 끄투식 첫 제시 글자.
 *
 * 끄투는 라운드를 열 때 (1) 기본 초성 하나를 뽑고, (2) 그 초성으로 시작하는 라운드 길이(2~3글자)
 * 단어를 사전에서 하나 고른 뒤, (3) 그 단어의 모든 글자가 다음 단어로 이어질 수 있는지(한방 글자
 * 없음)를 확인하고, (4) 그 단어의 첫 글자를 첫 차례 참가자에게 넘긴다.
 * 잇다도 같은 순서로 고른다 — 다만 대국이 한 라운드뿐이라 제시어 자체는 화면에 내보내지 않고
 * 그 첫 글자만 '이어야 할 글자'로 쓴다.
 *
 * 지금까지처럼 시작 음절을 사전 구간에서 무작위로 뽑으면 '츱'처럼 사전에만 있는 희귀 글자가
 * 나와 첫 수부터 막힌다. 그래서 기준 단어를 일상 명사 2~3글자에서만 고르고, 그 첫 글자가
 * 일상 단어로 충분히 이어지는지까지 확인한다.
 *
 * @returns {{ title: string, char: string }|null} 기준 단어와 제시 글자
 */
export function pickStartTitle(dict, { level = 2, rng = Math.random } = {}) {
  const easyFirst = level <= 2;                        // Lv.1·2는 일상 표준어(1~3단계)만
  const minEasy = easyFirst ? 20 : 10;                 // 제시 글자로 이어갈 일상 단어 수
  const minDict = easyFirst ? 120 : 200;               // 제시 글자로 이어갈 사전 단어 수

  const collect = (tierLimit, easyLimit, dictLimit) => {
    const pool = [];
    for (const [word, tier] of dict.easy) {
      if (!tier || tier > tierLimit) continue;
      if (word.length < 2 || word.length > 3) continue;   // 끄투의 라운드 길이
      if (!BASIC_INITIALS.has(initialOf(word.charAt(0)))) continue;
      // 기준 단어의 모든 글자가 이어질 수 있어야 한다(한방 글자가 낀 단어는 제외)
      let ok = true;
      for (const ch of word) {
        if (dict.countFrom(ch) <= 0) { ok = false; break; }
      }
      if (!ok) continue;
      const first = word.charAt(0);
      if (dict.countFrom(first) < dictLimit) continue;
      if (dict.easyCountFrom(first) < easyLimit) continue;
      pool.push(word);
    }
    return pool;
  };

  const tiers = easyFirst ? [3, 7] : [7];
  let pool = [];
  for (const tierLimit of tiers) {
    pool = collect(tierLimit, minEasy, minDict);
    if (pool.length) break;
  }
  if (!pool.length) pool = collect(7, 5, 60);   // 마지막 완화: 일상 단어 5개 이상
  if (!pool.length) return null;

  // 기준 단어를 고르면 초성도 그 단어 수만큼 자연스럽게 가중된다(끄투와 같은 방식).
  const title = pool[Math.floor(rng() * pool.length)] || pool[0];
  return { title, char: title.charAt(0) };
}

/**
 * Lv.5 지옥의 선공 오프닝.
 * 봇이 먼저 두는 판에서 아무 글자나 잡지 않고, 봇이 유리한 자리로 시작을 끊는다.
 *  - 그 글자로 낼 단어가 있어야 한다(countFrom > 0).
 *  - 봇이 0수 한방으로 1초 만에 끝내는 자리(W1)는 피한다.
 *  - 봇이 이기는 자리(W3·W5·W7) → 무승부(D) → 지는 자리(L) 순으로 고른다.
 *  - 같은 등급이면 더 빨리 끝나는 자리, 그다음 봇이 고를 수 있는 수가 많은 자리.
 *  - 최단 깊이 하나로 고정하지 않고, 그로부터 2수 안쪽(최대 7수)의 승리 오프닝
 *    안에서 고른다 → 매 판 다른 글자로 시작하되 여전히 봇이 이기는 자리다.
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
  const depthLimit = Math.min(pool[0].depth + 2, 7);
  const top = pool.filter((c) => c.depth <= depthLimit);
  return top[Math.floor(rng() * top.length)].ch;
}
