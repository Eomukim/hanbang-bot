/**
 * 봇 대 봇 벤치마크: 레벨별 승률(선공·후공 각각), 수당 판단 시간.
 *
 * 브라우저 없이 Node 에서 `js/` 의 사전·봇·엔진 쪽 로직을 그대로 불러와
 * 실제 규칙(사용 단어, 두음법칙, 미션 글자 교체, 후속 0수 패배)으로 대국한다.
 *
 * usage:
 *   /workspace/.local/node/bin/node tools/bench.mjs --games 200
 *   /workspace/.local/node/bin/node tools/bench.mjs --games 200 --openings hell --out downloads/bench-after.json
 *   옵션: --levels 4,3,random --openings all|nokill|draw|hell --seed N
 *        --hell old5  (이전 구현과 비교: `git show <rev>:js/bot.js > js/__old_bot.js` 로 두고 실행)
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// data.js 는 fetch 로 사전을 읽는다 → Node 에서는 파일을 그대로 흘려 준다.
globalThis.fetch = async (url) => {
  const p = path.join(ROOT, String(url));
  if (!fs.existsSync(p)) {
    return { ok: false, status: 404, headers: { get: () => null }, text: async () => '' };
  }
  const buf = fs.readFileSync(p);
  return {
    ok: true,
    status: 200,
    headers: { get: (k) => (String(k).toLowerCase() === 'content-length' ? String(buf.length) : null) },
    json: async () => JSON.parse(buf.toString('utf8')),
    text: async () => buf.toString('utf8'),
    body: {
      getReader() {
        let off = 0;
        return {
          async read() {
            if (off >= buf.length) return { done: true, value: undefined };
            const value = buf.subarray(off, off + 262144);
            off += 262144;
            return { done: false, value };
          },
        };
      },
    },
  };
};

const { Dictionary } = await import('../js/data.js');
const { Bot, pickHellOpening } = await import('../js/bot.js');
let OldBot = null;
try {
  ({ Bot: OldBot } = await import('../js/__old_bot.js'));
} catch {
  OldBot = null;
}
const { missionHits, MISSION_CHARS, allowedStarts } = await import('../js/rules.js');

/* ── 결정적 난수 ─────────────────────────────────────────── */

function mulberry32(a) {
  return function rng() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const args = process.argv.slice(2);
const argOf = (name, def) => {
  const i = args.indexOf(`--${name}`);
  return i !== -1 && args[i + 1] ? args[i + 1] : def;
};
const GAMES = Number(argOf('games', '200'));
const LEVELS = String(argOf('levels', '4,3,random')).split(',').map((s) => s.trim());
const OPENINGS = String(argOf('openings', 'all')); // all | nokill | draw | hell
const OUT = argOf('out', '');
const HELL = String(argOf('hell', '5')); // 측정 대상(Lv.5 지옥) 구현: 5 = 새 봇, old5 = 이전 봇
const VS_OLD = args.includes('--vs-old'); // 상대 Lv.5 도 이전 구현으로(대칭 비교용)
const START_SEED = Number(argOf('seed', '20261121'));

/* ── 봇 ─────────────────────────────────────────────────── */

class RandomBot {
  constructor(dict, rng) {
    this.name = 'random';
    this.dict = dict;
    this.rng = rng;
  }

  choose({ needChar, used }) {
    const cands = this.dict.candidatesFor(needChar, used);
    if (!cands.length) return null;
    return { word: cands[Math.floor(this.rng() * cands.length)], delay: 0, kind: 'normal' };
  }
}

const dict = new Dictionary();
const loadT0 = performance.now();
await dict.load({ wordsUrl: 'data/words.txt', statsUrl: 'data/stats.json' });
console.log(`사전 ${dict.size.toLocaleString('en-US')}단어 로드 ${Math.round(performance.now() - loadT0)}ms`);

const makeBot = (kind, rng) => {
  if (kind === 'random') return new RandomBot(dict, rng);
  if (kind === 'punish') return new Punisher(dict, rng);
  if (kind === 'old5' || (kind === 'hell' && HELL === 'old5')) {
    if (!OldBot) {
      throw new Error('이전 구현 비교에는 js/__old_bot.js 가 필요합니다: git show <rev>:js/bot.js > js/__old_bot.js');
    }
    return new OldBot({ level: 5, dict, rng });
  }
  if (kind === 'hell') return new Bot({ level: 5, dict, rng });
  if (kind === '5' && VS_OLD) {
    if (!OldBot) throw new Error('--vs-old 에는 js/__old_bot.js 가 필요합니다');
    return new OldBot({ level: 5, dict, rng });
  }
  return new Bot({ level: Number(kind), dict, rng });
};

const pickMission = (rng, exclude = null) => {
  const pool = MISSION_CHARS.filter((c) => c !== exclude);
  return pool[Math.floor(rng() * pool.length)];
};

const lastOf = (w) => w.charAt(w.length - 1);
const startsOK = (w, needChar) => allowedStarts(needChar).some((s) => w.startsWith(s));

/**
 * 한방 사냥꾼: 이번 판에서 '후속 단어가 0이 된' 자리까지 보고(동적 한방 포함) 즉시 낼 수 있는
 * 한방이 있으면 반드시 끝낸다. 없으면 후속이 가장 적은 글자로 조여 온다.
 *  — Lv.5 가 숨은 한방을 밟는지 그대로 드러내는 상대다(Lv.4는 정적 한방만 본다).
 */
class Punisher {
  constructor(dict, rng) {
    this.name = 'punish';
    this.dict = dict;
    this.rng = rng;
  }

  choose({ needChar, used }) {
    const dict = this.dict;
    const starts = startCountsOf(used);
    const cands = dict.candidatesFor(needChar, used);
    if (!cands.length) return null;
    // 1) 지금 바로 끝낼 수 있는가(동적 한방 포함)
    const kills = [];
    for (const w of cands) {
      const s = w.charAt(0);
      const st = new Map(starts);
      st.set(s, (st.get(s) || 0) + 1);
      if (liveWith(lastOf(w), st) === 0) kills.push(w);
    }
    if (kills.length) return { word: kills[Math.floor(this.rng() * kills.length)], delay: 0, kind: 'oneshot' };
    // 2) 아니면 후속이 가장 적은 글자로 몰아넣는다
    let best = null;
    let bestN = Infinity;
    for (const w of cands) {
      const n = dict.countFrom(lastOf(w));
      if (n < bestN) { bestN = n; best = w; }
      if (bestN === 1) break;
    }
    return { word: best || cands[0], delay: 0, kind: 'outer' };
  }
}

/* ── 숨은 한방 감사(독립 구현) ───────────────────────────────
 * 봇 코드를 쓰지 않고 사전만으로 '이 자리에서 상대가 한방을 낼 수 있는가'를 전수로 본다.
 *  - 시작 글자 하나가 통째로 쓰이면 그 글자로 시작해야 하는 자리는 죽는다(후속 0).
 *  - 두음법칙으로 받아 주는 글자까지 함께 본다.
 *  Lv.5 가 둔 수 직후 상대가 한방을 낼 수 있었는지, 그 수를 피할 수 있었는지를 세어
 *  '숨은 한방 허용'이 0인지 확인한다.
 */
const pairCount = new Map();   // 시작 글자 + 끝 글자 → 단어 수
for (const w of dict.words) {
  const k = w.charAt(0) + '\u0000' + lastOf(w);
  pairCount.set(k, (pairCount.get(k) || 0) + 1);
}
const allEndChars = [...new Set([...pairCount.keys()].map((k) => k.slice(2)))];

const pairKey = (s, y) => s + '\u0000' + y;
const startCountsOf = (used) => {
  const m = new Map();
  for (const w of used) m.set(w.charAt(0), (m.get(w.charAt(0)) || 0) + 1);
  return m;
};
const pairCountsOf = (used) => {
  const m = new Map();
  for (const w of used) {
    const k = pairKey(w.charAt(0), lastOf(w));
    m.set(k, (m.get(k) || 0) + 1);
  }
  return m;
};
const liveWith = (ch, starts) => {
  let n = 0;
  for (const s of allowedStarts(ch)) {
    const r = dict.rangeOf(s);
    if (r) n += Math.max(0, r[1] - r[0] - (starts.get(s) || 0));
  }
  return n;
};
const deadCharsWith = (starts) => allEndChars.filter((y) => liveWith(y, starts) === 0);

/** 이 글자에서 둘 차례인 쪽이 낼 수 있는 한방 단어가 있는가(전수 · 시작/끝 짝의 수로 판정). */
const oneShotAt = (ch, starts, pairs, dead = null) => {
  const d = dead || deadCharsWith(starts);
  if (!d.length) return false;
  for (const s of allowedStarts(ch)) {
    if (!dict.rangeOf(s)) continue;
    for (const y of d) {
      const k = pairKey(s, y);
      if ((pairCount.get(k) || 0) > (pairs.get(k) || 0)) return true;
    }
  }
  return false;
};

const addStart = (starts, ch) => {
  const m = new Map(starts);
  m.set(ch, (m.get(ch) || 0) + 1);
  return m;
};
const addPair = (pairs, s, y) => {
  const m = new Map(pairs);
  const k = pairKey(s, y);
  m.set(k, (m.get(k) || 0) + 1);
  return m;
};

/**
 * 이 자리(needChar, used)에서 수를 둔 뒤 상대가 한방으로 끝낼 수 있는지.
 * 값은 '그 수가 끝나는 글자'로만 정해지므로 끝 글자마다 한 번만 본다.
 */
function handedAudit(needChar, used, chosen) {
  const starts = startCountsOf(used);
  const pairs = pairCountsOf(used);
  const startsAfter = addStart(starts, chosen.charAt(0));
  const pairsAfter = addPair(pairs, chosen.charAt(0), lastOf(chosen));
  const handed = oneShotAt(lastOf(chosen), startsAfter, pairsAfter);
  if (!handed) return { handed: false, avoidable: false, safeMove: null };
  // 피할 수 있었는가: 이 자리의 다른 수 중 상대 한방을 주지 않는 것이 있는가
  for (const s of allowedStarts(needChar)) {
    const r = dict.rangeOf(s);
    if (!r) continue;
    const nextStarts = addStart(starts, s);
    const dead = deadCharsWith(nextStarts);
    for (let i = r[0]; i < r[1]; i += 1) {
      const w = dict.words[i];
      if (used.has(w)) continue;
      const e = lastOf(w);
      if (!oneShotAt(e, nextStarts, addPair(pairs, s, e), dead)) {
        return { handed: true, avoidable: true, safeMove: w };
      }
    }
  }
  return { handed: true, avoidable: false, safeMove: null };
}

/* ── 대국 ───────────────────────────────────────────────── */

function playGame(aKind, bKind, { startChar, seed, audit = null }) {
  // aKind/bKind 중 'hell' 은 측정 대상(Lv.5)을 뜻한다
  const A = { kind: aKind, isHell: aKind === 'hell', bot: makeBot(aKind, mulberry32(seed * 7 + 1)), name: 'A' };
  const B = { kind: bKind, isHell: bKind === 'hell', bot: makeBot(bKind, mulberry32(seed * 13 + 5)), name: 'B' };
  const rngM = mulberry32(seed * 31 + 9);

  const used = new Set();
  let needChar = startChar;
  let mission = pickMission(rngM);
  let turn = 1;
  let cur = A;
  let other = B;
  const times = { 5: [], other: [] };
  let moves = 0;

  for (let i = 0; i < 400; i += 1) {
    if (!dict.hasCandidate(needChar, used)) {
      return { winner: other.name, loser: cur.name, moves, invalid: null, times, needChar };
    }
    const t0 = performance.now();
    const mv = cur.bot.choose({ needChar, used, turn, mission });
    (cur.isHell ? times[5] : times.other).push(performance.now() - t0);
    if (!mv || !mv.word) {
      return { winner: other.name, loser: cur.name, moves, invalid: null, times, needChar };
    }
    const w = mv.word;
    if (used.has(w) || !startsOK(w, needChar) || !dict.has(w)) {
      return {
        winner: other.name, loser: cur.name, moves, times, needChar,
        invalid: { who: cur.name, word: w, needChar, used: used.has(w), known: dict.has(w) },
      };
    }
    used.add(w);
    moves += 1;
    if (cur.isHell && audit) {
      audit.moves += 1;
      const a = handedAudit(needChar, used, w);
      if (a.handed) {
        audit.handed += 1;
        if (a.avoidable) {
          audit.avoidable += 1;
          if (audit.samples.length < 6) audit.samples.push({ needChar, word: w, safe: a.safeMove });
        } else audit.unavoidable += 1;
      }
    }
    if (missionHits(w, mission) > 0) mission = pickMission(rngM, mission);
    needChar = lastOf(w);
    [cur, other] = [other, cur];
    turn += 1;
  }
  return { winner: 'draw', loser: null, moves, invalid: null, times, needChar };
}

const starts = dict.goodStartChars(120).sort();
const noKillStarts = starts.filter((ch) => !dict.candidatesFor(ch, new Set(), 4000)
  .some((w) => dict.countFrom(lastOf(w)) === 0));
// 이론상 둘째(후공)가 이길 수 있는 시작 글자 — 그래프가 무승부/미확정(D)인 자리만.
const drawStarts = starts.filter((ch) => dict.graphStatus(ch) === 'D');

const pickStart = (g, hellFirst, rng) => {
  if (OPENINGS === 'hell' && hellFirst) return pickHellOpening(dict, rng);
  if (OPENINGS === 'draw') return drawStarts[(g * 37 + 11) % drawStarts.length];
  const pool = OPENINGS === 'nokill' ? noKillStarts : starts;
  return pool[(g * 37 + 11) % pool.length];
};

const pct = (arr, p) => {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  return +s[Math.min(s.length - 1, Math.floor(p * s.length))].toFixed(2);
};

function runPairing(vsKind) {
  const rows = [];
  for (const hellFirst of [true, false]) {
    const rng = mulberry32(START_SEED + 99);
    const audit = { moves: 0, handed: 0, avoidable: 0, unavoidable: 0, samples: [] };
    let hellWins = 0;
    let oppWins = 0;
    let draws = 0;
    let invalid = 0;
    let turnsSum = 0;
    const hellTimes = [];
    const oppTimes = [];
    const lengthHist = {};
    for (let g = 0; g < GAMES; g += 1) {
      const seed = START_SEED + g * 101 + vsKind.length * 17 + (hellFirst ? 0 : 7) + OPENINGS.length;
      const startChar = pickStart(g, hellFirst, rng);
      const r = playGame(hellFirst ? 'hell' : vsKind, hellFirst ? vsKind : 'hell', { startChar, seed, audit });
      if (r.invalid) invalid += 1;
      // hellFirst 면 A 가 측정 대상
      const hellSide = hellFirst ? 'A' : 'B';
      if (r.winner === 'draw') draws += 1;
      else if (r.winner === hellSide) hellWins += 1;
      else oppWins += 1;
      if (!r.invalid) {
        turnsSum += r.moves;
        lengthHist[r.moves] = (lengthHist[r.moves] || 0) + 1;
      }
      hellTimes.push(...r.times[5]);
      oppTimes.push(...r.times.other);
    }
    rows.push({
      vs: vsKind,
      hellFirst,
      opening: OPENINGS,
      games: GAMES,
      hellWins,
      oppWins,
      draws,
      winRate: +(hellWins / GAMES).toFixed(3),
      avgTurns: +(turnsSum / GAMES).toFixed(1),
      msAvg: +(hellTimes.reduce((a, b) => a + b, 0) / Math.max(1, hellTimes.length)).toFixed(2),
      msP95: pct(hellTimes, 0.95),
      msMax: pct(hellTimes, 1),
      oppMsMax: pct(oppTimes, 1),
      invalid,
      lengthHist,
      audit,
    });
    console.log(
      `  숨은 한방 감사: Lv.5 ${audit.moves}수 중 상대 한방을 준 수 ${audit.handed}회`
      + ` (피할 수 있었는데 ${audit.avoidable}회 / 어쩔 수 없이 ${audit.unavoidable}회)`
      + (audit.samples.length ? ` 예: ${JSON.stringify(audit.samples[0])}` : ''),
    );
  }
  return rows;
}

const results = [];
const t0 = performance.now();
for (const lv of LEVELS) {
  const rows = runPairing(lv);
  results.push(...rows);
  for (const r of rows) {
    console.log(
      `Lv.5 ${r.hellFirst ? '선공' : '후공'} vs ${lv.padEnd(6)} : `
      + `${HELL === 'old5' ? 'old' : 'new'} ${r.hellWins}/${r.games} (${(r.winRate * 100).toFixed(1)}%) `
      + `· 평균 ${r.avgTurns}수 · 판단 평균 ${r.msAvg}ms / p95 ${r.msP95}ms / 최대 ${r.msMax}ms`
      + (r.invalid ? ` · 무효수 ${r.invalid}` : ''),
    );
  }
  console.log(`  누적 ${((performance.now() - t0) / 1000).toFixed(1)}s`);
}

if (OUT) {
  const outPath = path.isAbsolute(OUT) ? OUT : path.join(ROOT, OUT);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify({
    generatedAt: new Date().toISOString(), games: GAMES, openings: OPENINGS, results,
  }, null, 2));
  console.log(`저장: ${outPath}`);
}
