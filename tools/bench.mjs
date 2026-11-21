/**
 * 봇 대 봇 벤치마크: 레벨별 승률(선공·후공 각각), 수당 판단 시간.
 *
 * 브라우저 없이 Node 에서 `js/` 의 사전·봇·엔진 쪽 로직을 그대로 불러와
 * 실제 규칙(사용 단어, 두음법칙, 미션 글자 교체, 후속 0수 패배)으로 대국한다.
 *
 * usage:
 *   /workspace/.local/node/bin/node tools/bench.mjs --games 200
 *   /workspace/.local/node/bin/node tools/bench.mjs --games 200 --openings hell --out downloads/bench-after.json
 *   옵션: --levels 4,3,random --openings all|nokill|hell --seed N
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
const OPENINGS = String(argOf('openings', 'all')); // all | nokill | hell
const OUT = argOf('out', '');
const HELL = String(argOf('hell', '5')); // 측정 대상(Lv.5 지옥) 구현: 5 = 새 봇, old5 = 이전 봇
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
  if (kind === 'old5') return new OldBot({ level: 5, dict, rng });
  if (kind === 'hell') {
    return HELL === 'old5' ? new OldBot({ level: 5, dict, rng }) : new Bot({ level: 5, dict, rng });
  }
  return new Bot({ level: Number(kind), dict, rng });
};

const pickMission = (rng, exclude = null) => {
  const pool = MISSION_CHARS.filter((c) => c !== exclude);
  return pool[Math.floor(rng() * pool.length)];
};

const lastOf = (w) => w.charAt(w.length - 1);
const startsOK = (w, needChar) => allowedStarts(needChar).some((s) => w.startsWith(s));

/* ── 대국 ───────────────────────────────────────────────── */

function playGame(aKind, bKind, { startChar, seed }) {
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

const pickStart = (g, hellFirst, rng) => {
  if (OPENINGS === 'hell' && hellFirst) return pickHellOpening(dict, rng);
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
      const r = playGame(hellFirst ? 'hell' : vsKind, hellFirst ? vsKind : 'hell', { startChar, seed });
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
    });
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
