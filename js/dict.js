/**
 * 단어 사전 화면.
 *
 * 시작 글자(또는 앞부분)로 사전 구간을 찾고, 끝 글자로 이어갈 수 있는 후속 단어 수
 * (endCount)를 기준으로 '어려움순 · 쉬움순 · 긴순 · 짧은순' 네 가지로 늘어놓는다.
 *
 * 사전은 시작 음절마다 연속 구간이라, 검색은 구간 안에서 이진 탐색 + startsWith 로 끝난다.
 * 후속 수는 끝 글자 하나로만 정해지므로 글자별로 한 번만 계산해 캐시한다.
 *
 * 목록의 단어를 누르면 그 단어를 클립보드로 복사하고, ‘후속 N개’를 누르면 그 단어의
 * 끝 글자를 검색어로 다시 찾는다(두음 포함·정렬 4종은 지금 고른 그대로). 후속을 타고
 * 내려간 자리는 ‘← 이전’ 칩으로 되돌아온다.
 */

import { allowedStarts, normalizeWord, twoeumOf } from './rules.js';

const PAGE_SIZE = 100;
const SEARCH_DELAY = 110;
// 검색어 길이 상한. 한글로 시작·끝나는 표제어 중에는 71글자(너바나더밴드…17년전으로돌)처럼
// 긴 단어도 있어서, 그 단어를 통째로 붙여넣어도 앞부분이 잘리지 않게 넉넉히 둔다.
const MAX_QUERY = 80;

const SORT_LABEL = {
  hard: '어려움순',
  easy: '쉬움순',
  long: '긴순',
  short: '짧은순',
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (n) => Number(n).toLocaleString('ko-KR');

/** 받침이 있으면 '으로', 없으면 '로' (마지막 글자 기준). */
const roFor = (text) => {
  const ch = String(text).charAt(String(text).length - 1);
  const k = ch.charCodeAt(0) - 0xac00;
  return k >= 0 && k < 11172 && k % 28 ? '으로' : '로';
};

/** 클립보드에 글자를 넣는다. 보안 컨텍스트·권한이 없으면 옛 방식으로 한 번 더 시도한다. */
async function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 권한이 없거나 보안 컨텍스트가 아니면 아래 폴백으로 */
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;top:-1000px;left:0;opacity:0;';
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, text.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

/** 사전 words[a, b) 안에서 prefix 이상이 처음 나오는 위치. */
function lowerBound(words, prefix, a, b) {
  let lo = a;
  let hi = b;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid] < prefix) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export class DictPanel {
  constructor({ dict, sfx, onBack, toast }) {
    this.dict = dict;
    this.sfx = sfx;
    this.onBack = onBack;
    this.toast = toast;

    this.query = '';
    this.twoeum = true;
    this.sort = 'hard';
    /** @type {string[]} 후속 단어를 타고 내려오기 전의 검색어들(뒤가 직전) */
    this.history = [];
    /** 마지막 복사 결과(검증용) */
    this.lastCopy = null;

    /** @type {string[]} 검색에 걸린 단어 */
    this.words = [];
    /** @type {Uint8Array} 두음법칙 대체 글자로 걸린 단어인지 */
    this.alts = new Uint8Array(0);
    /** @type {Int32Array} 끝 글자 후속 단어 수 */
    this.counts = new Int32Array(0);
    /** @type {Uint8Array} 일상 어휘 단계(0이면 목록에 없음) */
    this.tiers = new Uint8Array(0);
    /** @type {Int32Array} 정렬된 순서(단어 배열 인덱스) */
    this.order = new Int32Array(0);

    this.shown = 0;
    this.tailCount = new Map();
    this.timer = null;
    this.mounted = false;
  }

  /* ── 조립 ─────────────────────────────────────────────── */

  mount() {
    if (this.mounted) return;
    this.mounted = true;

    this.el = {
      screen: $('scr-dict'),
      input: $('dict-input'),
      clear: $('dict-clear'),
      twoeum: $('btn-twoeum'),
      sorts: $('dict-sorts'),
      meta: $('dict-meta'),
      body: $('dict-body'),
      list: $('dict-list'),
      empty: $('dict-empty'),
      emptyTitle: $('dict-empty-title'),
      emptyDesc: $('dict-empty-desc'),
      suggest: $('dict-suggest'),
      more: $('dict-more'),
      moreCount: $('dict-more-count'),
      back: $('btn-dict-back'),
      total: $('dict-total'),
      backChip: $('dict-back-chip'),
      backWord: $('dict-back-word'),
    };

    this.el.total.textContent = `${num(this.dict.size)} 단어`;
    this.renderTwoeum();
    this.renderSorts();
    this.renderHistory();

    this.el.back.addEventListener('click', () => this.close());
    this.el.clear.addEventListener('click', () => {
      this.el.input.value = '';
      this.el.input.focus({ preventScroll: true });
      this.setQuery('');
    });
    this.el.twoeum.addEventListener('click', () => {
      this.twoeum = !this.twoeum;
      this.renderTwoeum();
      this.sfx?.play('tap');
      this.search();
    });
    this.el.sorts.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (this.sort === btn.dataset.sort) return;
        this.sort = btn.dataset.sort;
        this.renderSorts();
        this.sfx?.play('tap');
        // 이미 모아 둔 결과를 다시 정렬만 한다(사전 재조회 없음)
        this.sortResults();
        this.resetList();
        this.renderMeta();
        this.renderPage();
      });
    });
    this.el.more.addEventListener('click', () => {
      this.sfx?.play('tap');
      this.renderPage();
    });

    // 목록에서: 단어를 누르면 복사, ‘후속 O개’를 누르면 그 끝 글자로 다시 찾기
    this.el.list.addEventListener('click', (event) => {
      const tail = event.target.closest('.dict-tail');
      if (tail) {
        event.preventDefault();
        event.stopPropagation();
        this.followTail(tail.dataset.tail);
        return;
      }
      const word = event.target.closest('.dict-word');
      if (word) {
        event.preventDefault();
        event.stopPropagation();
        this.copyWord(word.closest('.dict-item')?.dataset.word);
      }
    });

    this.el.backChip.addEventListener('click', () => this.goBack());

    const input = this.el.input;
    input.addEventListener('input', (event) => {
      if (event.isComposing) return;   // 한글 조합 중에는 기다린다
      this.schedule();
    });
    input.addEventListener('compositionend', () => this.schedule());
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        this.clearTimer();
        this.setQuery(input.value);
        input.blur();
      }
    });

    this.el.suggest.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.el.input.value = btn.dataset.char;
        this.setQuery(btn.dataset.char);
        this.sfx?.play('tap');
      });
    });
  }

  /* ── 열기 / 닫기 ───────────────────────────────────────── */

  open() {
    this.mount();
    this.el.total.textContent = `${num(this.dict.size)} 단어`;   // 사전은 mount 뒤에 불러온다
    this.el.input.value = this.query;
    this.renderClear();
    this.renderHistory();
    if (!this.query) {
      this.renderEmpty('start');
      this.renderMeta();
    } else if (!this.words.length) this.search();
    else this.el.body.scrollTop = 0;
  }

  close() {
    this.clearTimer();
    this.el.input.blur();
    this.onBack?.();
  }

  focusInput() {
    this.el.input.focus({ preventScroll: true });
  }

  /* ── 상태 그리기 ───────────────────────────────────────── */

  renderTwoeum() {
    this.el.twoeum.setAttribute('aria-checked', String(this.twoeum));
    this.el.twoeum.setAttribute('aria-label', `두음 포함 ${this.twoeum ? '켬' : '끔'}`);
  }

  renderSorts() {
    this.el.sorts.querySelectorAll('button').forEach((btn) => {
      btn.setAttribute('aria-checked', String(btn.dataset.sort === this.sort));
    });
  }

  renderClear() {
    this.el.clear.hidden = !this.el.input.value;
  }

  clearTimer() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  schedule() {
    this.renderClear();
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      this.setQuery(this.el.input.value);
    }, SEARCH_DELAY);
  }

  /* ── 검색 ─────────────────────────────────────────────── */

  /** 입력값을 다듬어(공백·제로폭 문자·한글·영숫자 밖 제거) 새로 찾는다. 직접 친 검색어는 후속 기록을 비운다. */
  setQuery(raw) {
    this.history = [];
    this.applyQuery(raw);
    this.renderHistory();
  }

  applyQuery(raw) {
    // 사전 표제어에는 `가락1동`처럼 숫자가 섞인 단어도 있으므로 영문자·숫자는 남긴다.
    const cleaned = normalizeWord(raw).replace(/[^가-힣0-9A-Za-z]/g, '').slice(0, MAX_QUERY);
    this.query = cleaned;
    this.renderClear();
    this.search();
  }

  /** ‘후속 O개’ — 지금 검색어를 기록에 남기고 그 단어의 끝 글자로 다시 찾는다.
   *  두음 포함·정렬 4종은 지금 고른 상태를 그대로 따른다(사전 검색과 같은 경로). */
  followTail(char) {
    const target = String(char || '').slice(0, 1);
    if (!target) return;
    if (this.query && this.query !== target) this.history.push(this.query);
    this.el.input.value = target;
    this.applyQuery(target);
    this.renderHistory();
    this.sfx?.play('tap');
  }

  /** 기록에 남은 직전 검색어로 돌아간다. */
  goBack() {
    const prev = this.history.pop();
    if (prev == null) return;
    this.el.input.value = prev;
    this.applyQuery(prev);
    this.renderHistory();
    this.sfx?.play('tap');
  }

  /** 단어를 클립보드에 넣고 토스트·소리로 알린다. */
  async copyWord(word) {
    const text = String(word || '').trim();
    if (!text) return;
    const ok = await copyText(text);
    this.lastCopy = { word: text, ok, at: Date.now() };
    this.sfx?.play('tap');
    this.toast?.(ok ? `‘${text}’ 복사됨` : `‘${text}’을 복사하지 못했어요`);
    return ok;
  }

  renderHistory() {
    const prev = this.history.length ? this.history[this.history.length - 1] : null;
    this.el.backChip.hidden = prev == null;
    if (prev != null) {
      this.el.backWord.textContent = prev;
      this.el.backChip.setAttribute('aria-label', `이전 검색 ‘${prev}’${roFor(prev)} 돌아가기`);
    }
  }

  search() {
    this.resetList();
    this.tailCount.clear();

    if (!this.query) {
      this.words = [];
      this.order = new Int32Array(0);
      this.renderEmpty('start');
      this.renderMeta();
      return;
    }

    this.collect();
    this.sortResults();
    this.renderEmpty(this.words.length ? null : 'miss');
    this.renderMeta();
    this.renderPage();
  }

  /** 목록을 비우고 스크롤을 맨 위로 올린다(새 검색·정렬 바꿈). */
  resetList() {
    this.shown = 0;
    this.el.list.innerHTML = '';
    this.el.body.scrollTop = 0;
  }

  /** 시작 글자 구간에서 prefix 로 시작하는 단어를 모은다. */
  collect() {
    const dict = this.dict;
    const q = this.query;
    const first = q.charAt(0);
    const starts = this.twoeum ? allowedStarts(first) : [first];
    const words = [];
    const alts = [];

    for (const start of starts) {
      const range = dict.rangeOf(start);
      if (!range) continue;
      const prefix = start + q.slice(1);
      const [a, b] = range;
      const isAlt = start !== first;
      for (let i = lowerBound(dict.words, prefix, a, b); i < b; i += 1) {
        const word = dict.words[i];
        if (!word.startsWith(prefix)) break;
        words.push(word);
        alts.push(isAlt ? 1 : 0);
      }
    }

    const n = words.length;
    this.words = words;
    this.alts = Uint8Array.from(alts);
    this.counts = new Int32Array(n);
    this.tiers = new Uint8Array(n);
    for (let i = 0; i < n; i += 1) {
      this.counts[i] = this.endCount(words[i]);
      this.tiers[i] = dict.easyTier(words[i]);
    }
  }

  /**
   * 이 글자로 이어갈 수 있는 후속 단어 수. 끝 글자 하나로만 정해지므로 글자별로 캐시한다
   * (두음법칙 변환 글자까지 합산하는 dict.countFrom 과 같은 정의).
   */
  endCount(word) {
    const ch = word.charAt(word.length - 1);
    let n = this.tailCount.get(ch);
    if (n === undefined) {
      n = this.dict.countFrom(ch);
      this.tailCount.set(ch, n);
    }
    return n;
  }

  sortResults() {
    const n = this.words.length;
    const order = new Int32Array(n);
    for (let i = 0; i < n; i += 1) order[i] = i;
    const { words, counts, tiers } = this;
    const len = (i) => words[i].length;
    const alpha = (a, b) => (words[a] < words[b] ? -1 : words[a] > words[b] ? 1 : 0);
    const easy = (i) => (tiers[i] > 0 ? 0 : 1);

    let cmp;
    if (this.sort === 'easy') {
      // 일상 명사 먼저 → 후속 단어가 많은(이어가기 쉬운) 순
      cmp = (a, b) => (easy(a) - easy(b)) || (counts[b] - counts[a]) || (tiers[a] - tiers[b])
        || (len(a) - len(b)) || alpha(a, b);
    } else if (this.sort === 'long') {
      cmp = (a, b) => (len(b) - len(a)) || alpha(a, b);
    } else if (this.sort === 'short') {
      cmp = (a, b) => (len(a) - len(b)) || alpha(a, b);
    } else {
      // 어려움순: 한방 단어(후속 0개)가 맨 위 → 후속이 적은 공격 단어 순
      cmp = (a, b) => (counts[a] - counts[b]) || (len(a) - len(b)) || alpha(a, b);
    }
    order.sort(cmp);
    this.order = order;
  }

  /* ── 그리기 ────────────────────────────────────────────── */

  renderMeta() {
    const meta = this.el.meta;
    if (!this.query) {
      meta.innerHTML = `<b>${num(this.dict.size)}</b> 단어 · ${SORT_LABEL[this.sort]}`;
      return;
    }
    const total = this.words.length;
    const q = esc(this.query);
    const twoeum = this.twoeum && twoeumOf(this.query.charAt(0)) ? ' · 두음 포함' : '';
    meta.innerHTML = total
      ? `<b>${num(total)}개</b> · ‘${q}’ 시작${twoeum} · ${SORT_LABEL[this.sort]}`
      : `‘${q}’${roFor(this.query)} 시작하는 단어 없음${twoeum}`;
  }

  renderEmpty(kind) {
    const box = this.el.empty;
    if (!kind) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    if (kind === 'miss') {
      const ch = this.query.charAt(0);
      const alt = twoeumOf(ch);
      this.el.emptyTitle.textContent = `‘${this.query}’${roFor(this.query)} 시작하는 단어가 없어요`;
      this.el.emptyDesc.textContent = alt && !this.twoeum
        ? `두음을 켜면 ‘${alt}’로 시작하는 단어까지 함께 봅니다.`
        : '글자를 줄이거나 다른 글자로 찾아보세요.';
      this.el.suggest.hidden = true;
      return;
    }
    this.el.emptyTitle.textContent = '시작 글자를 입력하세요';
    this.el.emptyDesc.textContent = '1글자는 그 글자로 시작하는 단어, 2글자 이상은 앞부분으로 찾습니다.';
    this.el.suggest.hidden = false;
  }

  /** 한 번에 100개씩 덧붙이고, 남은 수를 '더 보기'에 적는다. */
  renderPage() {
    const total = this.order.length;
    if (!total) {
      this.el.more.hidden = true;
      return;
    }
    const from = this.shown;
    const to = Math.min(total, from + PAGE_SIZE);
    const q = this.query;
    const highlight = q.length;
    const parts = [];
    for (let k = from; k < to; k += 1) {
      const i = this.order[k];
      const word = this.words[i];
      const count = this.counts[i];
      const tier = this.tiers[i];
      const oneShot = count === 0;
      const head = esc(word.slice(0, highlight));
      const rest = esc(word.slice(highlight));
      const lastChar = word.charAt(word.length - 1);
      const chips = [];
      if (tier) chips.push(tier <= 3 ? '<span class="dict-chip easy">일상</span>' : '<span class="dict-chip loan">외래어</span>');
      if (this.alts[i]) chips.push('<span class="dict-chip twoeum">두음</span>');
      const tail = oneShot
        ? '<span class="dict-tail shot">🔥 한방</span>'
        : `<button class="dict-tail" type="button" data-tail="${esc(lastChar)}"`
          + ` aria-label="‘${esc(word)}’ 끝 글자 ‘${esc(lastChar)}’${roFor(lastChar)} 이어지는 단어 ${num(count)}개 보기">후속 ${num(count)}개</button>`;
      parts.push(`
        <li class="dict-item${oneShot ? ' oneshot' : ''}" data-word="${esc(word)}" data-count="${count}" data-len="${word.length}" data-tier="${tier}">
          <button class="dict-word" type="button" aria-label="‘${esc(word)}’ 복사">${head ? `<b>${head}</b>` : ''}${rest}</button>
          <span class="dict-tags">
            <span class="dict-len">${word.length}글자</span>
            ${tail}
            ${chips.join('')}
          </span>
        </li>`);
    }
    this.el.list.insertAdjacentHTML('beforeend', parts.join(''));
    this.shown = to;

    const left = total - to;
    this.el.more.hidden = left <= 0;
    this.el.moreCount.textContent = left > 0 ? `(${num(left)}개 남음)` : '';
  }

  /* ── 검증용 ────────────────────────────────────────────── */

  rows(limit = this.order.length) {
    const out = [];
    const n = Math.min(limit, this.order.length);
    for (let k = 0; k < n; k += 1) {
      const i = this.order[k];
      out.push({
        word: this.words[i],
        len: this.words[i].length,
        count: this.counts[i],
        tier: this.tiers[i],
        alt: this.alts[i],
      });
    }
    return out;
  }

  info() {
    return {
      query: this.query,
      twoeum: this.twoeum,
      sort: this.sort,
      total: this.order.length,
      shown: this.shown,
      history: [...this.history],
      lastCopy: this.lastCopy,
    };
  }
}
