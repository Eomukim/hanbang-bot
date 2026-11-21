/**
 * 단어 사전.
 *
 * data/words.txt 는 코드 포인트 순으로 정렬되어 있어서, 시작 음절마다 한 덩어리의
 * 연속 구간을 이룬다. 그래서 '시작 글자 → 단어 목록' 색인을 따로 저장할 필요 없이
 * 구간(ranges)만 들고 있으면 되고, 두음법칙 변환 글자의 구간까지 더하면 후속 단어
 * 수(nextCount)가 바로 나온다.
 */

import { twoeumOf, allowedStarts } from './rules.js';

const FLAG_TAGS = [
  [1, '외래어'],
  [2, '사전 인정'],
  [8, '방언'],
  [16, '옛말'],
  [32, '문화어'],
];

const nextFrame = () => new Promise((resolve) => setTimeout(resolve, 0));

export class Dictionary {
  constructor() {
    /** @type {string[]} 코드 포인트 순 단어 */
    this.words = [];
    /** @type {Uint8Array} 단어별 원본 사전 flag 비트 */
    this.flags = new Uint8Array(0);
    /** @type {Map<string, [number, number]>} 시작 음절 → [시작, 끝) */
    this.ranges = new Map();
    /** @type {Map<string, number>} 일상 어휘 → 단계(1~3 표준어, 5~7 외래어). 없으면 0 */
    this.easy = new Map();
    /** @type {Map<string, number>} 시작 음절 → 그 글자로 시작하는 일상 어휘 수 */
    this.easyStarts = new Map();
    this.stats = null;
    /** 빌드 타임 음절 대전 그래프: 승리·패배 노드의 깊이와 한방 단어 */
    this.graph = { win: new Map(), lose: new Map(), shots: new Map(), statusCounts: null };
  }

  get size() {
    return this.words.length;
  }

  async load({ wordsUrl = 'data/words.txt', statsUrl = 'data/stats.json', onProgress } = {}) {
    const dict = this;

    try {
      const res = await fetch(statsUrl, { cache: 'no-cache' });
      if (res.ok) dict.stats = await res.json();
    } catch {
      /* 통계 파일이 없어도 사전은 쓸 수 있다 */
    }
    if (dict.stats) {
      dict.setGraph(dict.stats.graph);
      dict.setEasy(dict.stats.easy);
    }

    const res = await fetch(wordsUrl, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`단어 사전을 불러오지 못했습니다 (HTTP ${res.status})`);

    const totalBytes = Number(res.headers.get('content-length')) || 0;
    const words = [];
    const flags = [];
    const ranges = new Map();
    let loadedBytes = 0;
    let rest = '';
    let pending = 0;
    let lastChar = '';

    const consume = (line) => {
      if (!line) return;
      const tab = line.indexOf('\t');
      const word = tab === -1 ? line : line.slice(0, tab);
      if (word.length < 2) return;
      const flag = tab === -1 ? 0 : Number(line.slice(tab + 1)) || 0;
      const ch = word.charAt(0);
      if (ch !== lastChar) {
        const prev = ranges.get(lastChar);
        if (prev) prev[1] = words.length;
        ranges.set(ch, [words.length, words.length]);
        lastChar = ch;
      }
      words.push(word);
      flags.push(flag);
    };

    if (res.body && res.body.getReader) {
      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        loadedBytes += value.byteLength;
        pending += value.byteLength;
        rest += decoder.decode(value, { stream: true });
        const lines = rest.split('\n');
        rest = lines.pop() ?? '';
        for (let i = 0; i < lines.length; i += 1) consume(lines[i]);
        if (pending > 260_000) {
          pending = 0;
          onProgress?.({
            ratio: totalBytes ? Math.min(0.99, loadedBytes / totalBytes) : null,
            words: words.length,
          });
          await nextFrame();
        }
      }
      rest += decoder.decode();
    } else {
      const text = await res.text();
      for (const line of text.split('\n')) {
        consume(line);
        if (words.length % 40_000 === 0) {
          onProgress?.({ ratio: null, words: words.length });
          await nextFrame();
        }
      }
    }
    for (const line of rest.split('\n')) consume(line);

    const last = ranges.get(lastChar);
    if (last) last[1] = words.length;

    dict.words = words;
    if (flags.some((f) => f !== 0)) {
      const arr = new Uint8Array(flags.length);
      for (let i = 0; i < flags.length; i += 1) arr[i] = flags[i];
      dict.flags = arr;
    }
    dict.ranges = ranges;
    onProgress?.({ ratio: 1, words: words.length });
    return dict;
  }

  /* ── 일상 어휘 ───────────────────────────────────────────── */

  /**
   * 빌드 타임에 만든 일상 어휘 단계를 붙인다.
   * stats.easy.bands 는 {단계: "단어 단어 …"} 형태다(전송량을 줄이려고 공백으로 이어 붙였다).
   */
  setEasy(easy) {
    const bands = easy && easy.bands;
    if (!bands) return;
    const map = new Map();
    for (const [band, list] of Object.entries(bands)) {
      const tier = Number(band) || 0;
      if (!tier || typeof list !== 'string') continue;
      for (const word of list.split(' ')) {
        if (!word) continue;
        const prev = map.get(word);
        if (!prev || tier < prev) map.set(word, tier);
      }
    }
    this.easy = map;
    const counts = new Map();
    for (const word of map.keys()) {
      const ch = word.charAt(0);
      counts.set(ch, (counts.get(ch) || 0) + 1);
    }
    this.easyStarts = counts;
  }

  /** 일상 어휘 단계(1~3 표준어 · 5~7 외래어). 목록에 없으면 0. */
  easyTier(word) {
    return this.easy.get(word) || 0;
  }

  /** 이 글자로 이어갈 수 있는 일상 어휘 수(두음법칙 변환 글자까지 합산). */
  easyCountFrom(ch) {
    let n = 0;
    for (const start of allowedStarts(ch)) n += this.easyStarts.get(start) || 0;
    return n;
  }

  /* ── 사전 조회 ───────────────────────────────────────────── */

  /** 빌드 타임에 계산한 음절 대전 그래프를 붙인다. */
  setGraph(graph) {
    if (!graph || !graph.win || !graph.lose) return;
    this.graph = {
      win: new Map(Object.entries(graph.win)),
      lose: new Map(Object.entries(graph.lose)),
      shots: new Map(Object.entries(graph.shots || {})),
      statusCounts: graph.statusCounts || null,
    };
  }

  /**
   * 이 글자에서 둘 차례인 쪽의 완전 정보 상태.
   * 'W' = 두는 쪽이 이긴다, 'L' = 두는 쪽이 진다, 'D' = 무승부/미확정.
   */
  graphStatus(ch) {
    if (this.graph.win.has(ch)) return 'W';
    if (this.graph.lose.has(ch)) return 'L';
    return 'D';
  }

  /** 승리/패배 노드의 수 순번(그래프에 없으면 0). */
  graphDepth(ch) {
    return this.graph.win.get(ch) ?? this.graph.lose.get(ch) ?? 0;
  }

  /** 이 글자로 시작하는 한방 단어 목록(빌드 타임 계산, 없으면 null). */
  shotWords(ch) {
    return this.graph.shots.get(ch) || null;
  }

  indexOf(word) {
    let lo = 0;
    let hi = this.words.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const cur = this.words[mid];
      if (cur === word) return mid;
      if (cur < word) lo = mid + 1;
      else hi = mid - 1;
    }
    return -1;
  }

  has(word) {
    return this.indexOf(word) !== -1;
  }

  flagOf(word) {
    const i = this.indexOf(word);
    return i === -1 ? 0 : this.flags[i] || 0;
  }

  tagsOf(word) {
    const tags = [];
    const flag = this.flagOf(word);
    for (const [bit, name] of FLAG_TAGS) {
      if (flag & bit) tags.push(name);
    }
    return tags;
  }

  /** 해당 음절로 시작하는 단어 구간. */
  rangeOf(ch) {
    return this.ranges.get(ch) || null;
  }

  /** 사전 단어 중 ch로 시작하는 수. */
  dictStartCount(ch) {
    const r = this.ranges.get(ch);
    return r ? r[1] - r[0] : 0;
  }

  /**
   * 이 글자로 이어갈 수 있는 후속 단어 수. 두음법칙 변환 글자까지 합산한다.
   * (빌드 타임에 계산한 nextCount와 같은 정의)
   */
  countFrom(ch) {
    let n = 0;
    for (const start of allowedStarts(ch)) {
      n += this.dictStartCount(start);
    }
    return n;
  }

  /** 후속 단어가 하나도 없는 글자로 끝나는 단어 = 한방 단어. */
  isOneShot(word) {
    return this.countFrom(word.charAt(word.length - 1)) === 0;
  }

  /** 후속 단어가 1~5개뿐인 글자로 끝나는 단어 = 유도(외통수) 단어. */
  isInduced(word, max = 5) {
    const n = this.countFrom(word.charAt(word.length - 1));
    return n > 0 && n <= max;
  }

  /** 이 글자로 시작하는 단어가 하나라도 남아 있는가. */
  hasCandidate(ch, used) {
    for (const start of allowedStarts(ch)) {
      const r = this.ranges.get(start);
      if (r) {
        for (let i = r[0]; i < r[1]; i += 1) {
          if (!used.has(this.words[i])) return true;
        }
      }
    }
    return false;
  }

  /** 이 글자로 시작하는, 아직 쓰이지 않은 단어 목록. */
  candidatesFor(ch, used, limit = Infinity) {
    const out = [];
    for (const start of allowedStarts(ch)) {
      const r = this.ranges.get(start);
      if (r) {
        for (let i = r[0]; i < r[1] && out.length < limit; i += 1) {
          const w = this.words[i];
          if (!used.has(w)) out.push(w);
        }
      }
    }
    return out;
  }

  /** 시작 글자 후보 중 단어가 충분한 음절 목록. */
  goodStartChars(minCount = 60) {
    const out = [];
    for (const [ch, [a, b]] of this.ranges) {
      if (b - a >= minCount) out.push(ch);
    }
    return out;
  }
}
