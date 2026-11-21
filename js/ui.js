/** 화면 조립과 조작. 게임 규칙은 engine.js 에 있다. */

import { Engine } from './engine.js';
import { LEVELS, levelInfo, botLine } from './bot.js';
import { normalizeWord, HANGUL_ONLY } from './rules.js';
import { saveSettings, saveCustom, recordResult } from './store.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const TIME_OPTIONS = [10, 15, 20];
const FIRST_OPTIONS = [
  ['me', '나부터'],
  ['bot', '봇부터'],
];

const REASON_TEXT = {
  timeout: '시간이 다 됐어요.',
  blocked: '이어갈 단어가 없어 막혔어요.',
  'one-shot': '한방 단어에 그대로 막혔어요.',
  quit: '대전을 포기했어요.',
};

export class App {
  constructor({ dict, settings, custom, record, sfx }) {
    this.dict = dict;
    this.settings = settings;
    this.custom = custom;
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

    this.el = {};
  }

  mount() {
    const ids = [
      'scr-loading', 'scr-setup', 'scr-game', 'load-fill', 'load-meta', 'load-error',
      'levels', 'lv-desc', 'time-opts', 'first-opts', 'btn-custom', 'custom-count',
      'btn-sound', 'btn-start', 'record', 'dict-count',
      'bot-face', 'bot-name', 'bot-lv', 'score-me', 'score-bot', 'btn-quit',
      'arena', 'stage', 'stage-hint', 'bot-bubble', 'chain',
      'need-char', 'need-alt', 'cand-count', 'chip-mission', 'chip-combo',
      'countdown', 'time-left', 'timer-fill', 'turn-panel', 'composer', 'word-input', 'btn-hint', 'btn-submit',
      'ov-result', 'result-badge', 'result-title', 'result-reason', 'result-me', 'result-bot',
      'result-stats', 'btn-again', 'btn-tosetup',
      'ov-custom', 'btn-custom-close', 'custom-form', 'custom-word', 'custom-mean',
      'custom-msg', 'custom-list',
    ];
    for (const id of ids) this.el[id] = $(id);

    this.renderLevels();
    this.renderSegments();
    this.renderSoundButton();
    this.renderCustomCount();
    this.renderRecord();
    this.el['dict-count'].textContent = this.dict.size.toLocaleString('ko-KR');

    this.bindEvents();
    this.show('setup');
    this.watchViewport();
  }

  /* ── 공통 ──────────────────────────────────────────────── */

  show(name) {
    this.screen = name;
    for (const key of ['scr-loading', 'scr-setup', 'scr-game']) {
      this.el[key].hidden = key !== `scr-${name}`;
    }
    if (name === 'setup') this.renderRecord();
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
    box.innerHTML = LEVELS.map((l) => `
      <button class="level" type="button" role="radio" data-lv="${l.id}" aria-checked="false" title="${esc(l.desc)}">
        <i>${l.face}</i><b>${l.name}</b><small>Lv.${l.id}</small>
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

  renderSoundButton() {
    const btn = this.el['btn-sound'];
    btn.textContent = this.settings.sound ? '소리 켬' : '소리 끔';
    btn.setAttribute('aria-pressed', String(this.settings.sound));
  }

  renderCustomCount() {
    this.el['custom-count'].textContent = String(Object.keys(this.custom).length);
  }

  renderRecord() {
    const rows = Object.entries(this.record)
      .filter(([, r]) => r.plays)
      .sort((a, b) => Number(b[0]) - Number(a[0]));
    if (!rows.length) {
      this.el.record.innerHTML = '<span>아직 전적이 없어요. 첫 대전을 시작해 보세요.</span>';
      return;
    }
    this.el.record.innerHTML = rows.map(([lv, r]) => {
      const name = levelInfo(Number(lv)).name;
      return `<span>Lv.${lv} ${name} · <b>${r.wins}</b>승 ${r.losses}패 · 최고 <b>${r.bestScore}</b>점</span>`;
    }).join('<br>');
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
    this.el['btn-again'].addEventListener('click', () => {
      this.hideResult();
      this.startGame();
    });
    this.el['btn-tosetup'].addEventListener('click', () => {
      this.hideResult();
      this.show('setup');
    });

    this.el['btn-quit'].addEventListener('click', () => this.armQuit());
    this.el['btn-hint'].addEventListener('click', () => this.useHint());

    this.el.composer.addEventListener('submit', (event) => {
      event.preventDefault();
      this.submitInput();
    });

    this.el['word-input'].addEventListener('input', () => {
      if (this.el['word-input'].classList.contains('bad')) this.el['word-input'].classList.remove('bad');
    });

    // 내 단어장
    this.el['btn-custom'].addEventListener('click', () => this.openCustom());
    this.el['btn-custom-close'].addEventListener('click', () => this.closeCustom());
    this.el['ov-custom'].addEventListener('click', (e) => {
      if (e.target === this.el['ov-custom']) this.closeCustom();
    });
    this.el['custom-form'].addEventListener('submit', (e) => {
      e.preventDefault();
      this.addCustomWord();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (!this.el['ov-custom'].hidden) this.closeCustom();
        else if (!this.el['ov-result'].hidden) this.hideResult();
      }
      if (e.key === 'Enter' && this.screen === 'setup' && this.el['ov-custom'].hidden) {
        if (document.activeElement && document.activeElement.tagName === 'INPUT') return;
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

  /* ── 대전 시작 ─────────────────────────────────────────── */

  startGame(overrides = {}) {
    this.sfx.unlock();
    const level = overrides.level ?? this.settings.level;
    const info = levelInfo(level);

    this.hideResult();
    this.engine?.destroy();
    this.el.stage.innerHTML = '<p class="stage-hint" id="stage-hint">첫 단어를 입력하세요</p>';
    this.el.chain.innerHTML = '';
    this.el['bot-bubble'].hidden = true;
    this.el.arena.classList.remove('has-bubble');
    this.el['score-me'].textContent = '0';
    this.el['score-bot'].textContent = '0';
    this.el['chip-combo'].hidden = true;
    this.el['bot-face'].textContent = info.face;
    this.el['bot-name'].textContent = info.botName;
    this.el['bot-lv'].textContent = info.label;
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
      timeLimit: overrides.timeLimit ?? this.settings.timeLimit,
      first: overrides.first ?? this.settings.first,
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
    this.el['stage-hint'].textContent = state.first === 'bot' ? '봇이 첫 단어를 고르는 중…' : '첫 단어를 입력하세요';
    this.setNeed(state);
    this.say(botLine(state.level, 'start', Math.random));
  }

  onTurn(state) {
    this.setNeed(state);
    const input = this.el['word-input'];
    if (state.phase === 'me') {
      input.disabled = false;
      input.placeholder = '단어 입력';
      this.el['btn-submit'].disabled = false;
      this.el['btn-hint'].disabled = false;
      this.lastTick = -1;
      if (this.screen === 'game' && this.isFinePointer()) input.focus({ preventScroll: true });
    } else {
      input.disabled = true;
      input.placeholder = '봇이 고르는 중…';
      this.el['btn-submit'].disabled = true;
      this.el['btn-hint'].disabled = true;
      this.el['countdown'].classList.remove('urgent');
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
    this.el['btn-hint'].disabled = true;
  }

  setNeed(state) {
    this.el['need-char'].textContent = state.needChar;
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

  onError({ message }) {
    this.sfx.play('error');
    const input = this.el['word-input'];
    input.classList.add('bad', 'shake');
    input.addEventListener('animationend', () => input.classList.remove('shake'), { once: true });
    this.toast(message);
  }

  onEnd(payload) {
    this.el['word-input'].disabled = true;
    this.el['btn-submit'].disabled = true;
    this.el['btn-hint'].disabled = true;
    cancelAnimationFrame(this.rafId);

    this.record = recordResult(this.record, this.engine.level, {
      win: payload.win,
      bestCombo: payload.bestCombo,
      score: payload.scoreMe,
    });
    this.renderRecord();

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
    const mean = this.dict.meanOf(entry.word);
    const who = entry.who === 'me' ? '나' : '봇';
    const hits = mission && mission.hits > 0 ? mission.hits : 0;
    const missionTag = hits
      ? `<span class="tag mission">${hits === 1 ? '미션 +50%' : `미션 ×${hits}`}</span>`
      : '';
    const wordHtml = hits && mission.char
      ? esc(entry.word).split(esc(mission.char)).join(`<em class="mis">${esc(mission.char)}</em>`)
      : esc(entry.word);
    const tagHtml = [
      missionTag,
      ...tags.map((t) => `<span class="tag">${esc(t)}</span>`),
    ].join('');
    const kindHtml = kind === 'outer'
      ? '<span class="tag danger">외통수</span>'
      : kind === 'press' ? '<span class="tag danger">압박</span>' : '';
    this.el.stage.innerHTML = `
      <div class="stage-word ${entry.who}">
        <div class="stage-who ${entry.who}"><i class="dot"></i>${who} · ${entry.word.length}글자</div>
        <h2 class="${entry.word.length > 12 ? 'long' : ''}">${wordHtml}</h2>
        <div class="stage-sub">
          <span class="gain">+${entry.score}</span>
          ${kindHtml}${tagHtml}
          ${mean ? `<span class="mean">${esc(mean)}</span>` : ''}
        </div>
      </div>`;
    this.el.arena.scrollTop = 0;
  }

  addChain(entry) {
    const li = document.createElement('li');
    li.className = entry.who;
    li.textContent = entry.word;
    this.el.chain.appendChild(li);
    this.el.chain.scrollTop = this.el.chain.scrollHeight;
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

  useHint() {
    if (!this.engine || this.engine.phase !== 'me') return;
    const hint = this.engine.hint();
    if (!hint) return;
    this.sfx.play('hint');
    if (!hint.count) {
      this.toast('이 글자로 이을 단어가 없어요.');
      return;
    }
    this.toast(`남은 단어 ${hint.count.toLocaleString('ko-KR')}개 · 예: ${hint.mask} (${hint.length}글자)`);
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
    this.el['result-reason'].textContent = reasonLine || '';
    this.el['result-me'].textContent = payload.scoreMe.toLocaleString('ko-KR');
    this.el['result-bot'].textContent = payload.scoreBot.toLocaleString('ko-KR');
    this.el['result-stats'].innerHTML = `
      <div><dt>턴</dt><dd>${payload.turns}</dd></div>
      <div><dt>최고 콤보</dt><dd>${payload.bestCombo}</dd></div>
      <div><dt>내 단어</dt><dd>${payload.words}</dd></div>`;
    this.el['ov-result'].hidden = false;
    if (payload.win) this.confetti();
  }

  hideResult() {
    this.el['ov-result'].hidden = true;
  }

  confetti() {
    const colors = ['#5eead4', '#7c9dff', '#ffc14d', '#ff7ab6', '#63f5a3'];
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

  /* ── 내 단어장 ─────────────────────────────────────────── */

  openCustom() {
    this.el['ov-custom'].hidden = false;
    this.el['custom-msg'].textContent = '';
    this.renderCustom();
    setTimeout(() => this.el['custom-word'].focus({ preventScroll: true }), 120);
  }

  closeCustom() {
    this.el['ov-custom'].hidden = true;
  }

  renderCustom() {
    const entries = Object.entries(this.custom).sort((a, b) => (b[1].at || 0) - (a[1].at || 0));
    const list = this.el['custom-list'];
    if (!entries.length) {
      list.innerHTML = '<li class="custom-empty">아직 추가한 단어가 없어요.</li>';
      return;
    }
    list.innerHTML = entries.map(([word, meta]) => `
      <li data-word="${esc(word)}">
        <b>${esc(word)}</b>${meta.mean ? `<span>${esc(meta.mean)}</span>` : ''}
        <button type="button" aria-label="${esc(word)} 삭제" data-remove="${esc(word)}">✕</button>
      </li>`).join('');
    list.querySelectorAll('[data-remove]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const word = btn.dataset.remove;
        delete this.custom[word];
        this.dict.removeCustom(word);
        saveCustom(this.custom);
        this.renderCustom();
        this.renderCustomCount();
      });
    });
  }

  addCustomWord() {
    const wordInput = this.el['custom-word'];
    const meanInput = this.el['custom-mean'];
    const msg = this.el['custom-msg'];
    const word = normalizeWord(wordInput.value);

    msg.classList.remove('ok');
    if (!word) {
      msg.textContent = '단어를 입력해 주세요.';
      return;
    }
    if (word.length < 2) {
      msg.textContent = '두 글자 이상만 추가할 수 있어요.';
      return;
    }
    if (!HANGUL_ONLY.test(word)) {
      msg.textContent = '한글 단어만 추가할 수 있어요.';
      return;
    }
    if (this.dict.has(word)) {
      msg.textContent = '이미 사전에 있는 단어예요.';
      return;
    }
    if (this.custom[word]) {
      msg.textContent = '이미 내 단어장에 있어요.';
      return;
    }

    this.custom[word] = { mean: meanInput.value.trim().slice(0, 40), at: Date.now() };
    this.dict.addCustom(word, this.custom[word].mean);
    saveCustom(this.custom);
    this.renderCustomCount();
    this.renderCustom();
    msg.classList.add('ok');
    msg.textContent = `‘${word}’ 추가 완료 — 나와 봇 모두 쓸 수 있어요.`;
    wordInput.value = '';
    meanInput.value = '';
    wordInput.focus({ preventScroll: true });
  }
}
