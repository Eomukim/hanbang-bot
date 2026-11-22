/** 화면 조립과 조작. 게임 규칙은 engine.js 에 있다. */

import { Engine } from './engine.js';
import { LEVELS, levelInfo, botLine } from './bot.js';
import { saveSettings, recordResult } from './store.js';
import { allowedStarts } from './rules.js';
import { DictPanel } from './dict.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const TIME_OPTIONS = [10, 15, 20];
const FIRST_OPTIONS = [
  ['me', '나부터'],
  ['bot', '봇부터'],
];

/** 앞 단어의 끝 글자로 이 단어를 받을 수 있는가(두음법칙 포함). */
const linksTo = (prevWord, nextWord) => Boolean(prevWord && nextWord
  && allowedStarts(prevWord[prevWord.length - 1]).includes(nextWord.charAt(0)));

const REASON_TEXT = {
  timeout: '시간이 다 됐어요.',
  blocked: '이어갈 단어가 없어 막혔어요.',
  'one-shot': '한방 단어에 그대로 막혔어요.',
  quit: '대전을 포기했어요.',
};

export class App {
  constructor({ dict, settings, record, sfx }) {
    this.dict = dict;
    this.settings = settings;
    // 전적은 대국이 끝날 때마다 store.js 로 쌓기만 한다(설정 화면에는 표시하지 않는다).
    this.record = record;
    this.sfx = sfx;
    this.engine = null;
    this.screen = 'loading';
    this.lastTick = -1;
    this.toastTimer = null;
    this.bubbleTimer = null;
    this.botLineTimer = null;
    this.quitArmed = false;
    this.quitTimer = null;
    this.rafId = null;
    this.dictPanel = null;
    /** 방금 놓인 단어 타일(이어지는 글자 표시용) */
    this.chainPrev = null;
    /** 보드로 올라간 마지막 수(다음 수가 오면 말풍선으로 내려간다) */
    this.chainPending = null;
    this.stagePrev = null;

    this.el = {};
  }

  mount() {
    const ids = [
      'scr-loading', 'scr-setup', 'scr-dict', 'scr-game', 'load-fill', 'load-meta', 'load-error',
      'levels', 'lv-desc', 'time-opts', 'first-opts',
      'btn-mercy', 'mercy-desc',
      'btn-sound', 'sound-icon', 'sound-value', 'btn-start', 'btn-dict',
      'bot-face', 'bot-name', 'bot-lv', 'score-me', 'score-bot', 'btn-quit', 'game-mercy',
      'arena', 'stage', 'stage-hint', 'bot-bubble', 'chain',
      'need-char', 'need-alt', 'cand-count', 'chip-mission', 'chip-combo',
      'countdown', 'time-left', 'timer-fill', 'turn-panel', 'composer', 'word-input', 'btn-submit',
      'ov-result', 'result-badge', 'result-title', 'result-mercy', 'result-level', 'result-level-face',
      'result-level-label', 'result-reason', 'result-me', 'result-bot',
      'result-stats', 'btn-again', 'btn-tosetup',
      'battle-log-btn', 'battle-log-label', 'battle-log', 'battle-log-list',
    ];
    for (const id of ids) this.el[id] = $(id);

    // 단어 사전 화면(설정 화면 오른쪽 위 📖 사전 버튼으로 연다)
    this.dictPanel = new DictPanel({
      dict: this.dict,
      sfx: this.sfx,
      onBack: () => this.show('setup'),
    });
    this.dictPanel.mount();

    this.renderLevels();
    this.renderSegments();
    this.renderMercy();
    this.renderSoundButton();

    this.bindEvents();
    this.show('setup');
    this.watchViewport();
  }

  /* ── 공통 ──────────────────────────────────────────────── */

  show(name) {
    this.screen = name;
    for (const key of ['scr-loading', 'scr-setup', 'scr-dict', 'scr-game']) {
      this.el[key].hidden = key !== `scr-${name}`;
    }
  }

  setProgress(ratio, words) {
    if (ratio != null) this.el['load-fill'].style.width = `${Math.round(ratio * 100)}%`;
    this.el['load-meta'].textContent = `${Number(words || 0).toLocaleString('ko-KR')} 단어`;
  }

  showLoadError(message) {
    const el = this.el['load-error'];
    el.hidden = false;
    el.textContent = message;
  }

  watchViewport() {
    const vv = window.visualViewport;
    if (!vv) return;
    const apply = () => {
      document.documentElement.style.setProperty('--vvh', `${Math.round(vv.height)}px`);
    };
    apply();
    vv.addEventListener('resize', apply);
    vv.addEventListener('scroll', apply);
  }

  /* ── 설정 화면 ─────────────────────────────────────────── */

  renderLevels() {
    const box = this.el.levels;
    // 난이도는 점(pip) 5개로 단계를 표시한다(초안 B 보드게임 타일).
    const pips = (n) => Array.from({ length: 5 }, (_, i) => `<i class="${i < n ? 'on' : ''}"></i>`).join('');
    box.innerHTML = LEVELS.map((l) => `
      <button class="level" type="button" role="radio" data-lv="${l.id}" aria-checked="false" title="${esc(l.desc)}">
        <span class="pips" aria-hidden="true">${pips(l.id)}</span><b>${l.name}</b><small>Lv.${l.id}</small>
      </button>`).join('');
    box.querySelectorAll('.level').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.settings.level = Number(btn.dataset.lv);
        this.persist();
        this.syncLevels();
        this.sfx.play('tap');
      });
    });
    this.syncLevels();
  }

  syncLevels() {
    const info = levelInfo(this.settings.level);
    this.el['lv-desc'].textContent = info.desc;
    this.el.levels.querySelectorAll('.level').forEach((btn) => {
      btn.setAttribute('aria-checked', String(Number(btn.dataset.lv) === this.settings.level));
    });
  }

  renderSegments() {
    const timeBox = this.el['time-opts'];
    timeBox.innerHTML = TIME_OPTIONS.map((t) => `<button type="button" role="radio" data-time="${t}">${t}초</button>`).join('');
    timeBox.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.settings.timeLimit = Number(btn.dataset.time);
        this.persist();
        this.syncSegments();
        this.sfx.play('tap');
      });
    });

    const firstBox = this.el['first-opts'];
    firstBox.innerHTML = FIRST_OPTIONS.map(([v, label]) => `<button type="button" role="radio" data-first="${v}">${label}</button>`).join('');
    firstBox.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.settings.first = btn.dataset.first;
        this.persist();
        this.syncSegments();
        this.sfx.play('tap');
      });
    });
    this.syncSegments();
  }

  syncSegments() {
    this.el['time-opts'].querySelectorAll('button').forEach((btn) => {
      btn.setAttribute('aria-checked', String(Number(btn.dataset.time) === this.settings.timeLimit));
    });
    this.el['first-opts'].querySelectorAll('button').forEach((btn) => {
      btn.setAttribute('aria-checked', String(btn.dataset.first === this.settings.first));
    });
  }

  /* ── 배려모드 ────────────────────────────────────────── */

  /** 설정 화면의 배려모드 스위치: 켜면 첫 5수 동안 나도 봇도 한방 단어를 쓰지 않는다. */
  renderMercy() {
    const on = Boolean(this.settings.mercy);
    const btn = this.el['btn-mercy'];
    btn.setAttribute('aria-checked', String(on));
    btn.setAttribute('aria-label', `배려모드 ${on ? '켬' : '끔'}`);
    this.el['mercy-desc'].textContent = on
      ? '첫 5턴(1~5수) 한방 금지 · 6턴부터 허용'
      : '끄면 일반 · 켜면 첫 5턴 한방 금지';
  }

  /** 대전 화면의 배려모드 칩: 보호 중에는 몇 번째 수인지, 6수부터는 해금을 보여 준다. */
  renderMercyBadge(state) {
    const badge = this.el['game-mercy'];
    if (!badge) return;
    if (!state?.mercy) {
      badge.hidden = true;
      badge.classList.remove('released');
      return;
    }
    const guard = Boolean(state.mercyGuard);
    badge.hidden = false;
    badge.classList.toggle('released', !guard);
    badge.innerHTML = guard
      ? `🛡️ 배려모드<small>${state.mercyTurn}/${state.mercyTurns}턴 · 한방 금지</small>`
      : '🛡️ 배려 해금<small>한방 가능</small>';
  }

  renderSoundButton() {
    const btn = this.el['btn-sound'];
    const on = this.settings.sound;
    btn.setAttribute('aria-pressed', String(on));
    btn.setAttribute('aria-label', `효과음 ${on ? '켬' : '끔'}`);
    this.el['sound-icon'].textContent = on ? '🔊' : '🔇';
    this.el['sound-value'].textContent = on ? '켬' : '끔';
  }

  persist() {
    saveSettings(this.settings);
  }

  /* ── 이벤트 ────────────────────────────────────────────── */

  bindEvents() {
    this.el['btn-sound'].addEventListener('click', () => {
      this.settings.sound = !this.settings.sound;
      this.sfx.setEnabled(this.settings.sound);
      if (this.settings.sound) {
        this.sfx.unlock();
        this.sfx.play('tap');
      }
      this.persist();
      this.renderSoundButton();
    });

    this.el['btn-start'].addEventListener('click', () => this.startGame());
    this.el['btn-dict'].addEventListener('click', () => this.openDict());
    this.el['btn-again'].addEventListener('click', () => {
      this.hideResult();
      this.startGame();
    });
    this.el['btn-tosetup'].addEventListener('click', () => {
      this.hideResult();
      this.show('setup');
    });

    this.el['btn-quit'].addEventListener('click', () => this.armQuit());
    this.el['battle-log-btn'].addEventListener('click', () => this.toggleBattleLog());
    this.el['battle-log'].addEventListener('scroll', () => this.updateBattleLogFade(), { passive: true });
    this.el['btn-mercy'].addEventListener('click', () => {
      this.settings.mercy = !this.settings.mercy;
      this.persist();
      this.renderMercy();
      this.sfx.play('tap');
    });

    this.el.composer.addEventListener('submit', (event) => {
      event.preventDefault();
      this.submitInput();
    });

    this.el['word-input'].addEventListener('input', () => {
      if (this.el['word-input'].classList.contains('bad')) this.el['word-input'].classList.remove('bad');
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !this.el['ov-result'].hidden) this.hideResult();
      if (e.key === 'Escape' && this.screen === 'dict') this.closeDict();
      if (e.key === 'Enter' && this.screen === 'setup') {
        if (document.activeElement && ['INPUT', 'BUTTON'].includes(document.activeElement.tagName)) return;
        e.preventDefault();
        this.startGame();
      }
    });

    // 오디오 잠금 해제 (첫 입력)
    const unlock = () => {
      this.sfx.unlock();
      this.sfx.setEnabled(this.settings.sound);
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
    };
    window.addEventListener('pointerdown', unlock, { once: true });
    window.addEventListener('keydown', unlock, { once: true });
  }

  /* ── 단어 사전 ────────────────────────────────────────── */

  openDict() {
    this.sfx.play('tap');
    this.show('dict');
    this.dictPanel.open();
    if (this.isFinePointer()) this.dictPanel.focusInput();
  }

  closeDict() {
    this.dictPanel?.close();
  }

  /* ── 대전 시작 ─────────────────────────────────────────── */

  startGame(overrides = {}) {
    this.sfx.unlock();
    const level = overrides.level ?? this.settings.level;
    const info = levelInfo(level);
    const mercy = overrides.mercy ?? Boolean(this.settings.mercy);
    const timeLimit = overrides.timeLimit ?? this.settings.timeLimit;
    const first = overrides.first ?? this.settings.first;

    this.hideResult();
    this.engine?.destroy();
    this.el.stage.innerHTML = '<p class="stage-hint" id="stage-hint">첫 단어를 입력하세요</p>';
    // innerHTML 로 새로 만든 노드라 mount()에서 잡아 둔 참조는 이미 떨어졌다.
    this.el['stage-hint'] = $('stage-hint');
    this.el.chain.innerHTML = '';
    this.el.chain.classList.remove('more-top');
    this.chainPrev = null;
    this.chainPending = null;
    this.stagePrev = null;
    this.el['bot-bubble'].hidden = true;
    this.el.arena.classList.remove('has-bubble');
    this.el['score-me'].textContent = '0';
    this.el['score-bot'].textContent = '0';
    this.el['chip-combo'].hidden = true;
    this.el['bot-face'].textContent = info.face;
    this.el['bot-name'].textContent = info.botName;
    this.el['bot-lv'].textContent = info.label;
    this.el['game-mercy'].hidden = !mercy;
    document.body.dataset.level = String(level);
    this.show('game');
    this.el.arena.scrollTop = 0;

    const now = (fn) => (payload) => {
      if (this.engine !== engine) return;   // 이미 끝난 대전의 늦은 콜백은 버린다
      fn(payload);
    };

    const engine = new Engine({
      dict: this.dict,
      level,
      mercy,
      timeLimit,
      first,
      startChar: overrides.startChar ?? null,
      mission: overrides.mission ?? null,
      on: {
        start: now((state) => this.onStart(state)),
        turn: now((state) => this.onTurn(state)),
        botThinking: now(() => this.onBotThinking()),
        meWord: now((payload) => this.onMeWord(payload)),
        botWord: now((payload) => this.onBotWord(payload)),
        error: now((payload) => this.onError(payload)),
        end: now((payload) => this.onEnd(payload)),
      },
    });
    this.engine = engine;
    engine.start();
    this.tickLoop();
  }

  onStart(state) {
    this.sfx.play('start');
    this.renderStartHint(state);
    this.setNeed(state);
    this.say(botLine(state.level, 'start', Math.random));
  }

  /**
   * 첫 수 안내: 끄투식으로 받은 제시 글자를 그대로 알려 준다.
   * (예전에는 화면을 다시 만들면서 잡아 둔 참조가 떨어져 '첫 단어를 입력하세요'가 그대로 남았다)
   */
  renderStartHint(state) {
    const hint = this.el['stage-hint'];
    if (!hint) return;
    const ch = state.startChar || state.needChar;
    // 받침이 있으면 '으로', 없으면 '로'
    const ro = (ch.charCodeAt(0) - 0xac00) % 28 ? '으로' : '로';
    hint.innerHTML = state.first === 'bot'
      ? `봇이 <b>‘${esc(ch)}’</b>${ro} 시작하는 단어를 고르는 중…`
      : `<b>‘${esc(ch)}’</b>${ro} 시작하는 단어를 입력하세요`;
  }

  onTurn(state) {
    this.setNeed(state);
    const input = this.el['word-input'];
    if (state.phase === 'me') {
      input.disabled = false;
      input.placeholder = '단어 입력';
      this.el['btn-submit'].disabled = false;
      this.lastTick = -1;
      this.el['countdown'].classList.remove('waiting');
      if (this.screen === 'game' && this.isFinePointer()) input.focus({ preventScroll: true });
    } else {
      input.disabled = true;
      input.placeholder = '봇이 고르는 중…';
      this.el['btn-submit'].disabled = true;
      this.el['countdown'].classList.remove('urgent');
      // 봇 차례에는 '···초' 대신 점만 보이게 한다(단위 '초'는 내 차례에만).
      this.el['countdown'].classList.add('waiting');
      const timerEl = document.querySelector('.timer');
      timerEl.classList.remove('warn', 'urgent');
      this.el['timer-fill'].style.width = '100%';
      this.el['time-left'].textContent = '···';
      this.el['cand-count'].textContent = '';
    }
  }

  onBotThinking() {
    this.el['word-input'].disabled = true;
    this.el['btn-submit'].disabled = true;
    this.el['countdown'].classList.add('waiting');
    this.el['time-left'].textContent = '···';
  }

  setNeed(state) {
    this.el['need-char'].textContent = state.needChar;
    this.renderMercyBadge(state);
    const alt = this.el['need-alt'];
    if (state.needAlt) {
      alt.hidden = false;
      alt.textContent = state.needAlt;
      alt.title = `두음법칙: ‘${state.needChar}’는 ‘${state.needAlt}’로도 이어갈 수 있어요`;
    } else {
      alt.hidden = true;
    }
    if (state.phase === 'me') {
      this.el['cand-count'].textContent = `${state.candidateCount.toLocaleString('ko-KR')}개`;
    }
    if (state.combo >= 2) {
      this.el['chip-combo'].hidden = false;
      this.el['chip-combo'].innerHTML = `콤보 <b>${state.combo}</b>`;
    } else {
      this.el['chip-combo'].hidden = true;
    }
    this.setMissionChip(state.missionChar);
  }

  /** 미션 칩: 글자가 바뀌면 짧게 튀어오른다. */
  setMissionChip(ch) {
    const chip = this.el['chip-mission'];
    if (!ch) {
      chip.hidden = true;
      delete chip.dataset.char;
      return;
    }
    const changed = Boolean(chip.dataset.char) && chip.dataset.char !== ch;
    chip.hidden = false;
    chip.innerHTML = `미션 <b>${esc(ch)}</b>`;
    chip.dataset.char = ch;
    if (!changed) return;
    chip.classList.remove('pop');
    void chip.offsetWidth;
    chip.classList.add('pop');
  }

  onMeWord({ word, score, combo, missionHits: hits, missionChar, missionMul, nextMission, state }) {
    this.sfx.play('ok', { combo });
    this.renderStage({ who: 'me', word, score }, { char: missionChar, hits });
    this.addChain({ who: 'me', word });
    this.el['score-me'].textContent = state.scoreMe.toLocaleString('ko-KR');
    this.floatScore(`+${score}`, 'me');
    if (hits > 0) this.missionHit({ char: missionChar, hits, mul: missionMul, next: nextMission });
    if (combo >= 3) this.say(botLine(state.level, 'combo'));
    else if (word.length >= 4 && state.level >= 2) this.say(botLine(state.level, 'long'));
    else if (Math.random() < 0.35) this.say(botLine(state.level, 'good'));
    this.setNeed(state);
  }

  onBotWord({ word, score, kind, oneShot, line, mission, state }) {
    const hits = mission?.hits ?? 0;
    if (hits > 0 && !oneShot) this.missionHit({ char: mission.char, hits, mul: mission.mul, next: mission.next, who: 'bot' });
    this.renderStage({ who: 'bot', word, score }, mission, kind);
    this.addChain({ who: 'bot', word });
    this.el['score-bot'].textContent = state.scoreBot.toLocaleString('ko-KR');
    this.sfx.play('bot');
    if (line) this.say(line);
    if (oneShot) {
      this.sfx.play('kill');
      this.koSplash('한방!', '후속 단어가 없는 글자로 끝났습니다');
    }
    this.setNeed(state);
  }

  /** 미션 성공 알림: 겹친 횟수와 다음 미션 글자를 함께 보여 준다. */
  missionHit({ char, hits, mul, next, who = 'me' }) {
    this.sfx.play('mission', { stack: hits });
    const head = hits === 1 ? '미션 성공!' : `미션 ${hits}중첩!`;
    const gain = hits === 1 ? '+50%' : `×${mul}`;
    const tail = next ? ` · 다음 미션 ‘${next}’` : '';
    this.toast(`${who === 'bot' ? '봇 ' : ''}${head} ‘${char}’ ${gain}${tail}`, 'mission');
  }

  onError({ message, code }) {
    this.sfx.play('error');
    const input = this.el['word-input'];
    input.classList.add('bad', 'shake');
    input.addEventListener('animationend', () => input.classList.remove('shake'), { once: true });
    // 배려모드로 거주된 한방 단어는 실수가 아니라 규칙 안내다.
    this.toast(message, code === 'mercy' ? 'mercy' : '');
  }

  onEnd(payload) {
    this.el['word-input'].disabled = true;
    this.el['btn-submit'].disabled = true;
    cancelAnimationFrame(this.rafId);

    this.record = recordResult(this.record, this.engine.level, {
      win: payload.win,
      bestCombo: payload.bestCombo,
      score: payload.scoreMe,
    });

    if (payload.win) this.sfx.play('win');
    else this.sfx.play('lose');

    const last = payload.chain[payload.chain.length - 1];
    const lastBot = [...payload.chain].reverse().find((c) => c.who === 'bot');
    const reasonLine = payload.win
      ? (payload.reason === 'bot-stuck' ? '봇이 이어갈 단어를 찾지 못했어요.' : '봇이 막혔어요.')
      : payload.reason === 'one-shot'
        ? `‘${lastBot?.word ?? ''}’ — 후속 단어가 없는 한방 단어였어요.`
        : payload.reason === 'blocked'
          ? `‘${last?.word ?? ''}’ 뒤에 이을 단어가 없어요.`
          : (REASON_TEXT[payload.reason] || '');

    const owner = this.engine;
    setTimeout(() => {
      if (this.engine !== owner) return;   // 그 사이 새 대전이 시작됐다면 결과창을 띄우지 않는다
      this.showResult(payload, reasonLine);
    }, payload.win ? 520 : 700);
  }

  /* ── 그리기 ────────────────────────────────────────────── */

  renderStage(entry, mission, kind) {
    const tags = this.dict.tagsOf(entry.word);
    const who = entry.who === 'me' ? '나' : '봇';
    const hits = mission && mission.hits > 0 ? mission.hits : 0;
    const missionTag = hits
      ? `<span class="tag mission">${hits === 1 ? '미션 +50%' : `미션 ×${hits}`}</span>`
      : '';
    // 이어지는 글자(앞 단어의 끝 = 이 단어의 첫 글자, 두음 포함)는 황동색, 미션 글자는 청록으로 표시한다.
    const prevWord = this.stagePrev?.word || '';
    const linkAt = linksTo(prevWord, entry.word) ? 0 : -1;
    const misChar = hits && mission && mission.char ? mission.char : '';
    const wordHtml = [...entry.word].map((ch, i) => {
      const isLink = i === linkAt;
      const isMis = Boolean(misChar) && ch === misChar;
      if (!isLink && !isMis) return esc(ch);
      const cls = [isLink ? 'lk' : '', isMis ? 'mis' : ''].filter(Boolean).join(' ');
      return `<em class="${cls}">${esc(ch)}</em>`;
    }).join('');
    const tagHtml = [
      missionTag,
      ...tags.map((t) => `<span class="tag">${esc(t)}</span>`),
    ].join('');
    const kindHtml = kind === 'outer'
      ? '<span class="tag danger">외통수</span>'
      : kind === 'route'
        ? '<span class="tag danger">필승 라인</span>'
        : kind === 'press' ? '<span class="tag danger press">압박</span>' : '';
    this.el.stage.innerHTML = `
      <div class="stage-word ${entry.who}">
        <div class="stage-who ${entry.who}"><i class="dot"></i>${who} · ${entry.word.length}글자</div>
        <h2 class="${entry.word.length > 12 ? 'long' : ''}">${wordHtml}</h2>
        <div class="stage-sub">
          <span class="gain">+${entry.score}</span>
          ${kindHtml}${tagHtml}
        </div>
      </div>`;
    this.el.arena.scrollTop = 0;
    this.stagePrev = entry;
  }

  /**
   * 주고받은 단어를 타일 말풍선으로 쌓는다. 방금 놓인 단어는 보드(#stage)에 크게 남기고,
   * 그 앞의 단어부터 말풍선으로 옮긴다. 앞 단어의 끝 글자와 이어지는 첫 글자는 양쪽 타일에서
   * 같은 색으로 표시해 말이 이어진 자리를 눈으로 보이게 한다.
   */
  addChain(entry) {
    const prev = this.chainPending;
    this.chainPending = entry;
    if (!prev) return;              // 첫 수는 보드에만 남긴다
    const word = String(prev.word);
    const before = this.chainPrev;
    const linked = linksTo(before?.word, word);
    const li = document.createElement('li');
    li.className = prev.who;
    li.innerHTML = `<span class="chain-who">${prev.who === 'me' ? '나' : '봇'}</span>`
      + `<span class="chain-word">${linked ? this.linkHtml(word, 0) : esc(word)}</span>`;
    this.el.chain.appendChild(li);
    // 앞 타일의 끝 글자도 같은 자리로 표시(이미 표시돼 있으면 그대로 둔다)
    if (linked && before.li && !before.li.dataset.linked) {
      const prevWord = before.word;
      const box = before.li.querySelector('.chain-word');
      if (box) box.innerHTML = this.linkHtml(prevWord, prevWord.length - 1);
      before.li.dataset.linked = '1';
    }
    li.dataset.linked = linked ? '1' : '';
    this.chainPrev = { word, li };
    const box = this.el.chain;
    box.scrollTop = box.scrollHeight;
    // 위로 더 남아 있으면 위쪽을 부드럽게 지운다
    box.classList.toggle('more-top', box.scrollTop > 6);
  }

  /** word 의 index 글자만 이어진 글자(.lk)로 감싼 HTML. */
  linkHtml(word, index) {
    return esc(word.slice(0, index))
      + `<span class="lk">${esc(word.slice(index, index + 1))}</span>`
      + esc(word.slice(index + 1));
  }

  say(text) {
    if (!text) return;
    const bubble = this.el['bot-bubble'];
    bubble.textContent = text;
    bubble.hidden = false;
    this.el.arena.classList.add('has-bubble');
    clearTimeout(this.bubbleTimer);
    this.bubbleTimer = setTimeout(() => {
      bubble.hidden = true;
      this.el.arena.classList.remove('has-bubble');
    }, 4200);
  }

  toast(message, variant = '') {
    let el = document.querySelector('.toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'toast';
      document.body.appendChild(el);
    }
    el.className = variant ? `toast ${variant}` : 'toast';
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
  }

  floatScore(text, who) {
    const el = document.createElement('div');
    el.className = 'float-score';
    el.textContent = text;
    if (who === 'bot') el.style.color = 'var(--bot)';
    const panel = this.el['turn-panel'].getBoundingClientRect();
    el.style.left = `${panel.left + panel.width - 40}px`;
    el.style.top = `${panel.top - 26}px`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 1000);
  }

  koSplash(main, sub) {
    const el = document.createElement('div');
    el.className = 'ko-splash';
    el.innerHTML = `<div><b>${esc(main)}</b><span>${esc(sub || '')}</span></div>`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 1100);
  }

  isFinePointer() {
    return window.matchMedia('(pointer: fine)').matches;
  }

  /* ── 입력 처리 ─────────────────────────────────────────── */

  submitInput() {
    if (!this.engine || this.engine.phase !== 'me') return;
    const input = this.el['word-input'];
    const raw = input.value;
    const result = this.engine.playMe(raw);
    if (result.ok) {
      input.value = '';
      this.sfx.play('tap');
    }
  }

  armQuit() {
    if (!this.engine || this.engine.phase === 'over') {
      this.show('setup');
      return;
    }
    if (this.quitArmed) {
      clearTimeout(this.quitTimer);
      this.quitArmed = false;
      this.el['btn-quit'].textContent = '✕';
      this.engine.quit();
      return;
    }
    this.quitArmed = true;
    this.el['btn-quit'].textContent = '!';
    this.toast('한 번 더 누르면 대전을 포기합니다.');
    this.quitTimer = setTimeout(() => {
      this.quitArmed = false;
      this.el['btn-quit'].textContent = '✕';
    }, 2500);
  }

  /* ── 타이머 ────────────────────────────────────────────── */

  tickLoop() {
    cancelAnimationFrame(this.rafId);
    const step = () => {
      const engine = this.engine;
      if (!engine || engine.phase === 'over') return;
      if (engine.phase === 'me') {
        const left = engine.timeLeft();
        const ratio = Math.max(0, Math.min(1, left / engine.timeLimit));
        this.el['timer-fill'].style.width = `${(ratio * 100).toFixed(1)}%`;
        this.el['time-left'].textContent = String(Math.ceil(left));
        const timer = document.querySelector('.timer');
        const urgent = left <= 3.2;
        const warn = left <= 6;
        timer.classList.toggle('warn', warn && !urgent);
        timer.classList.toggle('urgent', urgent);
        this.el['countdown'].classList.toggle('urgent', urgent);
        const whole = Math.ceil(left);
        if (urgent && whole !== this.lastTick) {
          this.lastTick = whole;
          this.sfx.play('tick');
        }
      }
      this.rafId = requestAnimationFrame(step);
    };
    this.rafId = requestAnimationFrame(step);
  }

  /* ── 결과 ──────────────────────────────────────────────── */

  showResult(payload, reasonLine) {
    const sheet = this.el['ov-result'].querySelector('.result-sheet');
    sheet.classList.toggle('win', payload.win);
    sheet.classList.toggle('lose', !payload.win);
    this.el['result-badge'].textContent = payload.win ? '🏆' : '💀';
    this.el['result-title'].textContent = payload.win ? '승리' : '패배';
    this.el['result-mercy'].hidden = !payload.mercy;
    this.renderResultLevel(payload.state?.level);
    this.el['result-reason'].textContent = reasonLine || '';
    this.el['result-me'].textContent = payload.scoreMe.toLocaleString('ko-KR');
    this.el['result-bot'].textContent = payload.scoreBot.toLocaleString('ko-KR');
    this.el['result-stats'].innerHTML = `
      <div><dt>턴</dt><dd>${payload.turns}</dd></div>
      <div><dt>최고 콤보</dt><dd>${payload.bestCombo}</dd></div>
      <div><dt>내 단어</dt><dd>${payload.words}</dd></div>`;
    this.renderBattleLog(payload.chain || []);
    this.el['ov-result'].hidden = false;
    if (payload.win) this.confetti();
  }

  /* ── 배틀 내역 ─────────────────────────────────────────── */

  /**
   * 그 판에서 주고받은 수를 순서대로 늘어놓는다(턴 번호 · 나/봇 · 단어 · 획득 점수 · 그 수의 태그).
   * 결과 화면은 승리 · 패배 · 시간 초과 · 포기 모두 여기를 거치므로 어느 쪽이든 볼 수 있고,
   * 결과가 뜰 때는 항상 접힌 채로 시작한다.
   */
  renderBattleLog(chain = []) {
    const list = this.el['battle-log-list'];
    const count = chain.length;
    this.el['battle-log-label'].textContent = `배틀 내역 (${count}수)`;
    this.el['battle-log-btn'].classList.toggle('empty', count === 0);
    this.setBattleLogOpen(false);
    if (!count) {
      list.innerHTML = '<li class="battle-log-empty">주고받은 단어가 없어요.</li>';
      return;
    }
    list.innerHTML = chain.map((entry, i) => {
      const who = entry.who === 'bot' ? 'bot' : 'me';
      const tags = [
        ...this.moveKindTags(entry),
        ...this.dict.tagsOf(entry.word).map((t) => `<span class="tag">${esc(t)}</span>`),
      ].join('');
      return `
        <li class="blog-move ${who}" data-turn="${i + 1}" data-who="${who}" data-score="${entry.score}" data-kind="${esc(entry.kind || '')}">
          <span class="blog-turn" aria-label="${i + 1}수">${i + 1}</span>
          <div class="blog-body">
            <div class="blog-head">
              <b class="blog-who">${who === 'me' ? '나' : '봇'}</b>
              <span class="blog-gain">+${entry.score}</span>
            </div>
            <p class="blog-word">${esc(entry.word)}</p>
            ${tags ? `<div class="blog-tags">${tags}</div>` : ''}
          </div>
        </li>`;
    }).join('');
  }

  /** 게임 중 카드에 붙던 수 태그를 그대로 옮긴다(한방 · 미션 · 외통수 · 필승 라인 · 압박). */
  moveKindTags(entry) {
    const out = [];
    const hits = entry.missionHits || 0;
    if (hits > 0) {
      out.push(`<span class="tag mission">${hits === 1 ? '미션 +50%' : `미션 ×${hits}`}</span>`);
    }
    const kindTag = { oneshot: '한방', outer: '외통수', route: '필승 라인', press: '압박' }[entry.kind];
    if (kindTag) out.push(`<span class="tag danger${entry.kind === 'press' ? ' press' : ''}">${kindTag}</span>`);
    return out;
  }

  setBattleLogOpen(open) {
    this.el['battle-log-btn'].setAttribute('aria-expanded', String(open));
    this.el['battle-log'].hidden = !open;
    if (open) this.el['battle-log'].scrollTop = 0;
    // 스크롤이 더 남아 있으면 아래쪽을 흐리게 해 '더 있음'을 보여 준다.
    requestAnimationFrame(() => this.updateBattleLogFade());
  }

  /** 배틀 내역이 잘려 보이지 않도록, 아래에 더 남았을 때만 페이드를 켠다. */
  updateBattleLogFade() {
    const box = this.el['battle-log'];
    if (!box || box.hidden) return;
    const more = box.scrollHeight - box.clientHeight > 2
      && box.scrollTop + box.clientHeight < box.scrollHeight - 4;
    box.classList.toggle('more', more);
  }

  toggleBattleLog() {
    const open = this.el['battle-log-btn'].getAttribute('aria-expanded') === 'true';
    this.setBattleLogOpen(!open);
    this.sfx.play('tap');
  }

  /** 결과 화면에 이번 대국의 난이도를 배지로 남긴다(승리·패배·시간 초과·포기 모두). */
  renderResultLevel(level) {
    const info = levelInfo(level ?? this.engine?.level ?? this.settings.level);
    const name = `Lv.${info.id} ${info.name}`;
    const box = this.el['result-level'];
    box.dataset.lv = String(info.id);
    box.setAttribute('aria-label', `대국 난이도 ${name}`);
    this.el['result-level-face'].textContent = info.face;
    this.el['result-level-label'].textContent = name;
  }

  hideResult() {
    this.el['ov-result'].hidden = true;
  }

  confetti() {
    const colors = ['#3E9B79', '#C4503B', '#C98A2E', '#7E64B8', '#3D7EC8', '#2E8794'];
    for (let i = 0; i < 26; i += 1) {
      const piece = document.createElement('i');
      piece.className = 'confetti';
      piece.style.left = `${Math.random() * 100}%`;
      piece.style.background = colors[i % colors.length];
      piece.style.animationDelay = `${Math.random() * 0.4}s`;
      piece.style.transform = `rotate(${Math.random() * 360}deg)`;
      document.body.appendChild(piece);
      setTimeout(() => piece.remove(), 2600);
    }
  }
}
