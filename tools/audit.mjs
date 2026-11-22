/**
 * 봇이 실제로 고르는 단어 품질 감사.
 *
 * 브라우저 없이 Node 에서 사전·봇 로직을 그대로 불러와 판을 돌리고, 봇이 낸 단어를
 * 모아 "동사(~다) 편중", "일상어 비율", "긴 단어/어인정 남발", "같은 글자에서 같은 단어 반복",
 * "상대에게 남기는 후속 단어 수(압박)" 를 난이도별로 센다.
 *
 * usage:
 *   /workspace/.local/node/bin/node tools/audit.mjs --games 30
 *   /workspace/.local/node/bin/node tools/audit.mjs --games 30 --json out.json
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

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
const { missionHits, MISSION_CHARS, allowedStarts } = await import('../js/rules.js');

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
const GAMES = Number(argOf('games', '20'));
const PLAYER = argOf('player', 'mixed');
const LEVELS = String(argOf('levels', '1,2,3,4,5')).split(',').map(Number);
const JSON_OUT = argOf('json', '');
const VERBOSE = args.includes('--verbose');

const dict = new Dictionary();
const t0 = performance.now();
await dict.load({ wordsUrl: 'data/words.txt', statsUrl: 'data/stats.json' });
console.log(`사전 ${dict.size.toLocaleString('en-US')}단어 / 일상어 ${dict.easy.size.toLocaleString('en-US')}개 로드 ${Math.round(performance.now() - t0)}ms`);

const lastOf = (w) => w.charAt(w.length - 1);
const NOT_EVERYDAY = 2 | 8 | 16 | 32;
const SENTENCE_HINT = /(습니다|해요|어요|아요|거야|지요|네요|니까|지만|면서|려고|한다|된다|했다|였다|이다|같다|보면|하면|라고|다고)$/;

const isVerbish = (w) => /다$/.test(w) && w.length >= 2;
const isFlagged = (w) => (dict.flagOf(w) & NOT_EVERYDAY) !== 0;
const isSentencey = (w) => w.length >= 8 && SENTENCE_HINT.test(w);

const pickMission = (rng, exclude = null) => {
  const pool = MISSION_CHARS.filter((c) => c !== exclude);
  return pool[Math.floor(rng() * pool.length)];
};

/** 상대역: 합법 단어 중 하나를 고르는 '사람'.
 *  - random   : 사전 전체에서 무작위(기계에 가까움)
 *  - everyday : 일상 어휘 목록 안에서만
 *  - casual   : 자주 쓰는 단어(빈도 목록 + 일상 어휘)만 아는 사람 — 모르는 글자가 오면 막힌다
 */
const FREQ_PATH = path.join(ROOT, 'build/tmp/ko_50k.txt');
let FREQ = null;
if (fs.existsSync(FREQ_PATH)) {
  FREQ = new Set();
  for (const line of fs.readFileSync(FREQ_PATH, 'utf8').split('\n')) {
    const w = line.split(/\s+/)[0];
    if (w) FREQ.add(w);
  }
}

function randomPlayer(rng, dict, quality = 'random') {
  const knows = (w) => (dict.easyTier(w) || (FREQ && FREQ.has(w)));
  const lastOf = (w) => w.charAt(w.length - 1);
  return {
    choose({ needChar, used }) {
      const cands = dict.candidatesFor(needChar, used);
      if (!cands.length) return null;
      let pool = cands;
      if (quality === 'everyday') {
        const easy = cands.filter((w) => dict.easyTier(w));
        if (easy.length) pool = easy;
      } else if (quality === 'casual' || quality === 'sharp') {
        const known = cands.filter(knows);
        if (!known.length) return null;   // 아는 단어가 없다 = 사람은 막힌다
        // 사람은 상대가 답할 만한 글자로 끝나는 단어를 고른다(자멸 방지).
        const kind = known.filter((w) => {
          const end = lastOf(w);
          return dict.candidatesFor(end, used, 12).filter(knows).length >= 8;
        });
        pool = kind.length ? kind : known;
        if (quality === 'sharp') {
          // 끝말잇기 고수는 한방 단어를 먼저 본다.
          const shots = cands.filter((w) => dict.countFrom(lastOf(w)) === 0);
          if (shots.length && rng() < 0.6) pool = shots;
        }
      }
      return { word: pool[Math.floor(rng() * pool.length)] };
    },
  };
}

/** 한 판: bot(측정) vs player(상대). 봇이 먼저 두는 판/나중에 두는 판 모두. */
function playGame(level, { startChar, seed, botFirst, playerQuality }) {
  const rngB = mulberry32(seed * 7 + 1);
  const rngP = mulberry32(seed * 13 + 5);
  const rngM = mulberry32(seed * 31 + 9);
  const bot = new Bot({ level, dict, rng: rngB });
  const player = randomPlayer(rngP, dict, playerQuality);

  const used = new Set();
  let needChar = startChar;
  let mission = pickMission(rngM);
  let turn = 1;
  const words = [];
  const times = [];
  let ended = null;

  for (let i = 0; i < 300; i += 1) {
    const botTurn = botFirst ? turn % 2 === 1 : turn % 2 === 0;
    if (!botTurn) {
      const mv = player.choose({ needChar, used });
      if (!mv) { ended = { winner: 'bot', reason: 'player-stuck' }; break; }
      used.add(mv.word);
      if (missionHits(mv.word, mission) > 0) mission = pickMission(rngM, mission);
      needChar = lastOf(mv.word);
      turn += 1;
      continue;
    }
    if (!dict.hasCandidate(needChar, used)) { ended = { winner: 'player', reason: 'bot-stuck' }; break; }
    const t = performance.now();
    const mv = bot.choose({ needChar, used, turn, mission });
    times.push(performance.now() - t);
    if (!mv || !mv.word) { ended = { winner: 'player', reason: 'bot-null' }; break; }
    if (used.has(mv.word) || !allowedStarts(needChar).some((s) => mv.word.startsWith(s)) || !dict.has(mv.word)) {
      ended = { winner: 'player', reason: 'invalid', word: mv.word, needChar };
      break;
    }
    words.push({ word: mv.word, needChar, kind: mv.kind, endCount: dict.countFrom(lastOf(mv.word)) });
    used.add(mv.word);
    if (missionHits(mv.word, mission) > 0) mission = pickMission(rngM, mission);
    needChar = lastOf(mv.word);
    turn += 1;
  }
  if (!ended) ended = { winner: 'draw', reason: 'limit' };
  return { words, ended, times };
}

const starts = dict.goodStartChars(120).sort();
const results = [];

for (const level of LEVELS) {
  const agg = {
    level, games: 0, moves: 0, botWins: 0, playerWins: 0, draws: 0,
    verbish: 0, easy: 0, flagged: 0, sentencey: 0, long8: 0, long6: 0,
    endCountSum: 0, endCount1: 0, endCount0: 0,
    topWords: new Map(), samples: [], kinds: new Map(), repeatStartSame: 0, startsSeen: new Map(),
    lossReasons: new Map(), movesPerGame: 0,
    msAvg: 0, msMax: 0,
  };
  const allTimes = [];
  for (let g = 0; g < GAMES; g += 1) {
    const rng = mulberry32(1000 + g * 37 + level);
    const botFirst = g % 2 === 0;
    const startChar = botFirst && level === 5
      ? pickHellOpening(dict, rng)
      : starts[(g * 53 + level * 11) % starts.length];
    const r = playGame(level, {
      startChar, seed: 5000 + g * 101 + level, botFirst,
      playerQuality: PLAYER === 'mixed' ? (g % 3 === 1 ? 'casual' : g % 3 === 2 ? 'everyday' : 'random') : PLAYER,
    });
    agg.games += 1;
    if (r.ended.winner === 'bot') agg.botWins += 1;
    else if (r.ended.winner === 'player') { agg.playerWins += 1; agg.lossReasons.set(r.ended.reason, (agg.lossReasons.get(r.ended.reason) || 0) + 1); }
    else agg.draws += 1;
    allTimes.push(...r.times);
    for (const w of r.words) {
      agg.moves += 1;
      if (isVerbish(w.word)) agg.verbish += 1;
      if (dict.easyTier(w.word)) agg.easy += 1;
      if (isFlagged(w.word)) agg.flagged += 1;
      if (isSentencey(w.word)) agg.sentencey += 1;
      if (w.word.length >= 8) agg.long8 += 1;
      if (w.word.length >= 6) agg.long6 += 1;
      agg.endCountSum += w.endCount;
      if (w.endCount === 1) agg.endCount1 += 1;
      if (w.endCount === 0) agg.endCount0 += 1;
      agg.topWords.set(w.word, (agg.topWords.get(w.word) || 0) + 1);
      agg.kinds.set(w.kind, (agg.kinds.get(w.kind) || 0) + 1);
      const key = `${w.needChar}>${w.word}`;
      agg.startsSeen.set(key, (agg.startsSeen.get(key) || 0) + 1);
      if (agg.samples.length < 40) agg.samples.push(`${w.needChar}→${w.word}`);
    }
  }
  allTimes.sort((a, b) => a - b);
  agg.msAvg = +(allTimes.reduce((a, b) => a + b, 0) / Math.max(1, allTimes.length)).toFixed(1);
  agg.msMax = +(allTimes[allTimes.length - 1] || 0).toFixed(1);
  const top = [...agg.topWords.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const repeat = [...agg.startsSeen.entries()].filter(([, n]) => n >= 3).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const pct = (n) => (agg.moves ? +((100 * n) / agg.moves).toFixed(1) : 0);

  console.log(`\n── Lv.${level} · ${agg.games}판 / 봇 ${agg.moves}수 · 봇승 ${agg.botWins} · 사람승 ${agg.playerWins} · 무승부 ${agg.draws}`);
  console.log(`   ~다 동사·형용사 ${pct(agg.verbish)}% · 일상어 ${pct(agg.easy)}% · 방언·옛말·어인정 ${pct(agg.flagged)}% · 문장형 ${pct(agg.sentencey)}% · 8자+ ${pct(agg.long8)}% · 6자+ ${pct(agg.long6)}%`);
  console.log(`   남기는 후속 평균 ${(agg.endCountSum / Math.max(1, agg.moves)).toFixed(1)} · 후속1 ${pct(agg.endCount1)}% · 후속0(한방) ${pct(agg.endCount0)}% · 판단 ${agg.msAvg}ms / 최대 ${agg.msMax}ms`);
  console.log(`   종류 ${JSON.stringify(Object.fromEntries(agg.kinds))} · 봇이 막힌 까닭 ${JSON.stringify(Object.fromEntries(agg.lossReasons))}`);
  console.log(`   자주 쓴 단어 ${top.map(([w, n]) => `${w}×${n}`).join(' ')}`);
  if (repeat.length) console.log(`   같은 자리 반복 ${repeat.map(([k, n]) => `${k}×${n}`).join(' ')}`);
  console.log(`   표본 ${agg.samples.slice(0, 24).join(' · ')}`);
  results.push({
    level, ...agg, movesPerGame: +(agg.moves / agg.games).toFixed(1),
    lossReasons: Object.fromEntries(agg.lossReasons),
    topWords: top, repeat, samples: agg.samples,
    kinds: Object.fromEntries(agg.kinds),
    pct: { verbish: pct(agg.verbish), easy: pct(agg.easy), flagged: pct(agg.flagged), sentencey: pct(agg.sentencey), long8: pct(agg.long8), long6: pct(agg.long6), endCount1: pct(agg.endCount1), endCount0: pct(agg.endCount0) },
    avgEndCount: +(agg.endCountSum / Math.max(1, agg.moves)).toFixed(2),
  });
}

/* ── 같은 자리에서 같은 단어만 고르는지(고착) ───────────────── */
console.log('\n── 같은 자리·같은 조건에서 단어가 섮이는가 (needChar 별 6판)');
const VARIETY_CHARS = ['가', '다', '리', '사', '수', '이', '기', '관', '스', '나'];
for (const level of LEVELS) {
  const rows = [];
  for (const ch of VARIETY_CHARS) {
    const seen = new Map();
    for (let s = 0; s < 6; s += 1) {
      const bot = new Bot({ level, dict, rng: mulberry32(900 + s * 37 + level * 7) });
      const mv = bot.choose({ needChar: ch, used: new Set(), turn: 4 });
      const w = mv && mv.word ? mv.word : '(막힘)';
      seen.set(w, (seen.get(w) || 0) + 1);
    }
    rows.push(`${ch}:${seen.size}종(${[...seen.entries()].map(([w, n]) => `${w}${n > 1 ? '×' + n : ''}`).join(',')})`);
  }
  console.log(`  Lv.${level} ` + rows.join(' · '));
}

if (JSON_OUT) {
  const p = path.isAbsolute(JSON_OUT) ? JSON_OUT : path.join(ROOT, JSON_OUT);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(results, null, 2));
  console.log(`\n저장: ${p}`);
}
