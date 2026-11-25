/**
 * 🧪 실험실 — 최대 8인 커스텀 방 · 방장 = 신(God) 모드.
 *
 * 다른 창(사전·메일함·계정)은 시트(overlay)지만, 실험실은 홈과 나란한 화면(`scr-lab`)이다.
 * 방 상태는 서버(D1 `lab_rooms`)가 들고 있고, 이 화면은 0.9초마다 상태를 읽는다.
 *
 * 이 화면이 하는 일
 *  - 방 만들기 · 자리(2~8) 편집 · 친구 초대 · 방 룰(턴 제한 시간 1~999초 텍스트 입력 등)
 *  - 진행: 방장 화면이 봇 차례를 engine.js/bot.js AI 로 골라 서버에 내고, 시간 초과도 알린다.
 *  - 신 모드 패널: 턴 제한 시간 변경 · 글자 봉인 · 현재 턴 넘기기 · 봇 난이도 변경
 *  - 초대 받기: 로그인 상태면 8초마다 내게 온 초대를 확인해 위쪽에 띄운다.
 *
 * 전적·랭킹·엽전은 이 방에서 쌓지 않는다(store.js 의 record 를 건드리지 않는다).
 */

import { Bot } from './bot.js';
import { allowedStarts, normalizeWord } from './rules.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ROOM_KEY = 'itda.lab.room.v1';
const POLL_MS = 900;
const INVITE_MS = 8000;
const LEVEL_NAMES = { 1: '순한', 2: '루키', 3: '마스터', 4: '극악', 5: '지옥' };

const ERRORS = {
  not_signed_in: '로그인하면 실험실을 쓸 수 있어요.',
  room_not_found: '방을 찾지 못했어요. 이미 닫혔을 수 있어요.',
  not_host: '방장만 바꿀 수 있어요.',
  not_in_room: '이 방에 앉은 사람만 볼 수 있어요.',
  room_playing: '게임 중에는 바꿀 수 없어요. 신 패널을 써 주세요.',
  already_playing: '이미 게임이 시작됐어요.',
  need_players: '최소 두 자리를 채워야 시작할 수 있어요.',
  seat_taken: '이미 친구가 앉아 있는 자리예요.',
  not_friend: '친구에게만 초대할 수 있어요.',
  self_invite: '나 자신은 초대할 수 없어요.',
  time_invalid: '제한 시간은 1~999초 사이로 정해 주세요.',
  char_invalid: '봉인할 글자를 한 글자로 정해 주세요.',
  already_banned: '이미 봉인한 글자예요.',
  seat_invalid: '자리를 다시 골라 주세요.',
  level_invalid: '봇 난이도는 Lv.1~5 사이예요.',
  rate_limited: '너무 자주 보냈어요. 잠시 후 다시 시도해 주세요.',
  invite_not_found: '이미 처리됐거나 사라진 초대예요.',
  invite_expired: '초대가 만료됐어요. 방장에게 다시 부탁해 주세요.',
  seat_changed: '자리가 바뀌었어요. 방장에게 다시 부탁해 주세요.',
  network: '연결이 잠시 불안정해요. 잠시 후 다시 시도해 주세요.',
  default: '잠시 문제가 생겼어요. 다시 시도해 주세요.',
};

const clampInt = (value, min, max, fallback) => {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
};
/** 한글 음절 하나인가(첫 글자·봉인 글자). */
const isHangulChar = (ch) => /^[가-힣]$/.test(String(ch || ''));

export class LabPanel {
  constructor({ dict, sfx, toast, account, onExit, onOpen, onEnterRoom } = {}) {
    this.dict = dict;
    this.sfx = sfx;
    this.toast = toast || (() => {});
    this.account = account || null;
    this.onExit = onExit || (() => {});
    this.onOpen = onOpen || (() => {});
    this.onEnterRoom = onEnterRoom || (() => {});
    this.user = null;
    this.room = null;
    this.code = '';
    this.screenOpen = false;
    this.pollTimer = null;
    this.inviteTimer = null;
    this.tickTimer = null;
    this.clockOffset = 0;
    this.lastEventAt = 0;
    this.lastVersion = 0;
    this.busy = false;
    this.pendingWork = false;
    this.patching = false;
    this.timeoutSentFor = -1;
    this.botSentFor = -1;
    this.friends = [];
    this.friendsAt = 0;
    this.invites = [];
    this.inviteShown = '';
    this.typedRoom = '';
    this.botThinkAt = 0;
    this.el = {};
  }

  init() {
    const ids = [
      'scr-lab', 'btn-lab', 'lab-back', 'lab-leave', 'lab-notice', 'lab-gate', 'lab-login',
      'lab-home', 'lab-create', 'lab-room', 'lab-code', 'lab-copy', 'lab-state',
      'lab-seats', 'lab-seat-note', 'lab-lobby', 'lab-start', 'lab-start-hint',
      'lab-invite-cap', 'lab-friends', 'lab-rules', 'lab-rule-time', 'lab-rule-nolimit',
      'lab-rule-lives', 'lab-rule-oneshot', 'lab-rule-min', 'lab-rule-max', 'lab-rule-banned',
      'lab-rule-start', 'lab-rule-mission', 'lab-rule-error', 'lab-rule-save',
      'lab-play', 'lab-turn', 'lab-need', 'lab-need-alt', 'lab-now', 'lab-mission', 'lab-timer',
      'lab-chain', 'lab-compose', 'lab-form', 'lab-word', 'lab-submit', 'lab-stuck',
      'lab-word-error', 'lab-god', 'lab-god-time', 'lab-god-time-btn', 'lab-god-seal',
      'lab-god-seal-btn', 'lab-god-pass', 'lab-god-bots', 'lab-god-error',
      'lab-result', 'lab-result-title', 'lab-result-line', 'lab-rematch', 'lab-quit',
      'lab-invite-pop', 'lab-invite-from', 'lab-invite-seat', 'lab-invite-accept', 'lab-invite-decline',
    ];
    for (const id of ids) this.el[id] = $(id);
    if (!this.el['scr-lab']) return;
    this.bind();
    this.startInviteWatch();
  }

  /* ── 서버 ─────────────────────────────────────────────── */

  async api(path, { method = 'GET', body } = {}) {
    const init = {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: body
        ? { 'content-type': 'application/json', accept: 'application/json' }
        : { accept: 'application/json' },
    };
    if (body) init.body = JSON.stringify(body);
    try {
      const res = await fetch(path, init);
      let data = null;
      try { data = await res.json(); } catch { data = null; }
      if (res.status === 401) this.handleAuthLost();
      return { ok: res.ok && Boolean(data && data.ok !== false), status: res.status, data };
    } catch {
      return { ok: false, status: 0, data: { error: 'network', message: ERRORS.network } };
    }
  }

  errorText(data) {
    return ERRORS[data?.error] || data?.message || ERRORS.default;
  }

  handleAuthLost() {
    this.user = null;
    this.room = null;
    this.code = '';
    this.stopPolling();
    this.account?.refreshUser?.({ force: true });
    this.renderScreen();
  }

  setUser(user) {
    const before = this.user?.id;
    this.user = user || null;
    if (!this.user) {
      this.room = null;
      this.code = '';
      this.stopPolling();
      this.hideInvite();
    } else if (this.user.id !== before) {
      void this.pollInvites();
    }
    if (this.screenOpen) this.renderScreen();
  }

  /* ── 열기 · 닫기 ───────────────────────────────────────── */

  open() {
    this.screenOpen = true;
    this.renderScreen();
    // 이 기기에서 마지막으로 놀던 방이 있으면 이어서 들어간다.
    const saved = this.readSavedCode();
    if (this.user && saved && !this.room) {
      this.code = saved;
      void this.loadRoom({ silent: true });
    }
    if (this.room) this.startPolling();
    void this.pollInvites();
    if (this.isFinePointer()) this.el['lab-create']?.focus?.({ preventScroll: true });
  }

  /** 다른 화면으로 옮기면 폴링만 멈춘다(방은 서버에 남는다). */
  pause() {
    this.screenOpen = false;
    this.stopPolling();
  }

  isOpen() {
    return this.screenOpen;
  }

  isFinePointer() {
    return window.matchMedia('(pointer: fine)').matches;
  }

  readSavedCode() {
    try {
      const code = localStorage.getItem(ROOM_KEY) || '';
      return /^[A-HJ-NP-Z2-9]{6}$/.test(code) ? code : '';
    } catch {
      return '';
    }
  }

  saveCode(code) {
    try {
      if (code) localStorage.setItem(ROOM_KEY, code);
      else localStorage.removeItem(ROOM_KEY);
    } catch { /* 저장 못 해도 이 화면은 된다 */ }
  }

  /* ── 방 상태 읽기 · 폴링 ───────────────────────────────── */

  startPolling() {
    this.stopPolling();
    if (!this.room || !this.user) return;
    this.pollTimer = setInterval(() => void this.poll(), POLL_MS);
  }

  stopPolling() {
    clearInterval(this.pollTimer);
    this.pollTimer = null;
    clearInterval(this.tickTimer);
    this.tickTimer = null;
  }

  async loadRoom({ silent = false } = {}) {
    if (!this.user || !this.code) return;
    const res = await this.api(`/api/lab/rooms/${encodeURIComponent(this.code)}`);
    if (!res.ok) {
      if (res.status === 404 || res.status === 403) {
        this.leaveLocalRoom();
        if (!silent) this.toast(this.errorText(res.data));
        this.renderScreen();
        return;
      }
      if (!silent) this.toast(this.errorText(res.data));
      return;
    }
    this.applyRoom(res.data?.room);
    this.startPolling();
  }

  async poll() {
    if (!this.room || !this.user || this.pendingWork || this.patching) return;
    const code = this.code;
    const res = await this.api(`/api/lab/rooms/${encodeURIComponent(code)}`);
    if (!res.ok) {
      if (res.status === 404 || res.status === 403) {
        this.toast(this.errorText(res.data));
        this.leaveLocalRoom();
        this.renderScreen();
      }
      return;
    }
    if (this.code !== code) return;
    this.applyRoom(res.data?.room);
  }

  applyRoom(room) {
    if (!room) return;
    // 늦게 도착한 옛 상태(폴링이 PATCH 보다 먼저 떠난 경우)가 방금 받은 새 상태를 덮지 않게.
    if (this.room && room.code === this.room.code && Number(room.version) < this.lastVersion) return;
    const first = !this.room;
    this.room = room;
    this.code = room.code;
    this.saveCode(room.code);
    this.clockOffset = Number(room.now || Date.now()) - Date.now();
    const changed = first || room.version !== this.lastVersion;
    this.lastVersion = room.version;
    if (changed) this.renderScreen();
    this.tickTimer ||= setInterval(() => this.tick(), 200);
    this.tick();
    if (changed) this.surfaceEvent();
    void this.hostWork();
  }

  leaveLocalRoom() {
    this.room = null;
    this.code = '';
    this.saveCode('');
    this.lastVersion = 0;
    this.lastEventAt = 0;
    this.timeoutSentFor = -1;
    this.botSentFor = -1;
    this.stopPolling();
  }

  /* ── 화면 그리기 ──────────────────────────────────────── */

  renderScreen() {
    if (!this.el['scr-lab']) return;
    const hasUser = Boolean(this.user);
    this.el['lab-gate'].hidden = hasUser || !this.el['lab-gate'];
    this.el['lab-home'].hidden = !hasUser || Boolean(this.room);
    this.el['lab-room'].hidden = !hasUser || !this.room;
    if (hasUser && !this.room) {
      this.el['lab-gate'].hidden = true;
    } else if (!hasUser) {
      this.el['lab-home'].hidden = true;
      this.el['lab-room'].hidden = true;
    }
    this.renderRoom();
  }

  renderRoom() {
    const room = this.room;
    if (!room) {
      this.el['lab-lobby'].hidden = true;
      this.el['lab-play'].hidden = true;
      return;
    }
    if (this.el['lab-code']) this.el['lab-code'].textContent = room.code;
    const state = room.state || {};
    const playing = room.status === 'playing' || room.status === 'over';
    this.el['lab-state'].textContent = room.status === 'playing' ? '대전 중'
      : room.status === 'over' ? '결과' : '준비 중';
    this.el['lab-state'].dataset.status = room.status;
    this.el['lab-leave'].hidden = false;
    this.el['lab-leave'].textContent = room.isHost ? '방 닫기' : '나가기';
    this.el['lab-lobby'].hidden = playing;
    this.el['lab-play'].hidden = !playing;
    this.renderSeats();
    if (playing) this.renderPlay();
    else this.renderLobby();
    if (room.status === 'over') this.renderResult();
    else this.el['lab-result'].hidden = true;
    this.el['lab-god'].hidden = !(room.isHost && room.status === 'playing');
    if (room.isHost && room.status === 'playing') this.renderGodBots();
  }

  renderSeats() {
    const room = this.room;
    const list = this.el['lab-seats'];
    if (!list || !room) return;
    list.replaceChildren();
    const lobby = room.status === 'lobby';
    const host = room.isHost;
    room.seats.forEach((seat, index) => {
      const li = document.createElement('li');
      li.className = 'lab-seat';
      li.dataset.seat = String(index);
      const mine = seat.mine;
      const alive = room.state?.alive?.[index] !== false;
      li.classList.toggle('is-mine', mine);
      li.classList.toggle('is-turn', room.status === 'playing' && room.state?.turnSeat === index);
      li.classList.toggle('is-out', room.status !== 'lobby' && !alive);

      const number = document.createElement('span');
      number.className = 'lab-seat-no';
      number.textContent = String(index + 1);
      li.appendChild(number);

      const who = document.createElement('div');
      who.className = 'lab-seat-who';
      const name = document.createElement('b');
      name.textContent = seat.kind === 'bot' ? `봇 Lv.${seat.level} ${LEVEL_NAMES[seat.level] || ''}`.trim() : seat.name || '친구';
      who.appendChild(name);
      const small = document.createElement('small');
      if (seat.kind === 'host') small.textContent = '나 · 방장(신)';
      else if (seat.kind === 'bot') small.textContent = `AI · Lv.${seat.level}`;
      else if (seat.status === 'invited') small.textContent = '초대 중 · 수락을 기다려요';
      else small.textContent = mine ? '나' : '친구 · 참여 중';
      who.appendChild(small);
      li.appendChild(who);

      if (room.status !== 'lobby' && !seat.mine && seat.kind !== 'bot') {
        // 진행 중에는 남은 목숨을 보여 준다.
        const hearts = document.createElement('span');
        hearts.className = 'lab-hearts';
        const lives = Number(room.state?.lives?.[index] ?? 0);
        hearts.textContent = alive ? '♥'.repeat(Math.max(0, lives)) : '탈락';
        li.appendChild(hearts);
      }

      if (host && lobby && seat.kind !== 'host') {
        const tools = document.createElement('div');
        tools.className = 'lab-seat-tools';
        const add = (label, cls, onClick) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = `lab-seat-btn ${cls || ''}`.trim();
          btn.textContent = label;
          btn.addEventListener('click', onClick);
          tools.appendChild(btn);
        };
        if (seat.kind === 'bot') {
          add(`Lv.${seat.level}`, 'lab-seat-lv', () => this.cycleBot(index));
          if (room.seats.length > 2) add('빼기', 'lab-seat-del', () => this.removeSeat(index));
        } else if (seat.status === 'invited') {
          add('초대 취소', 'lab-seat-del', () => this.removeSeat(index));
        } else if (room.seats.length > 2) {
          add('내보내기', 'lab-seat-del', () => this.removeSeat(index));
        }
        // 방장 자리(첫 자리)는 움직이지 않는다.
        if (index > 1) add('↑', 'lab-seat-move', () => this.moveSeat(index, -1));
        if (index < room.seats.length - 1 && room.seats[index + 1].kind !== 'host') {
          add('↓', 'lab-seat-move', () => this.moveSeat(index, 1));
        }
        li.appendChild(tools);
      }
      list.appendChild(li);
    });

    if (host && lobby && room.seats.length < 8) {
      const li = document.createElement('li');
      li.className = 'lab-seat lab-seat-add';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = '+ 자리 추가';
      btn.addEventListener('click', () => this.addSeat());
      li.appendChild(btn);
      list.appendChild(li);
    }
    if (this.el['lab-seat-note']) {
      this.el['lab-seat-note'].textContent = host && lobby
        ? `자리 ${room.seats.length}/8 · 봇 이름을 누르면 난이도가 바뀌어요`
        : '방장만 자리를 바꿀 수 있어요';
    }
  }

  renderLobby() {
    const room = this.room;
    const host = room.isHost;
    const rules = room.rules || {};
    this.el['lab-start'].hidden = !host;
    this.el['lab-start-hint'].hidden = !host;
    this.el['lab-start'].disabled = room.filled < 2;
    this.el['lab-start-hint'].textContent = room.filled < 2
      ? '두 자리 이상 채우면 시작할 수 있어요.'
      : `${room.filled}자리로 시작할 수 있어요.`;
    this.el['lab-rules'].querySelectorAll('input, select, button').forEach((node) => {
      node.disabled = !host;
    });
    this.el['lab-invite-cap'].textContent = host
      ? '접속 중인 친구를 빈 자리에 앉혀 보세요.'
      : '방장이 친구를 초대할 수 있어요.';
    if (host) this.syncRuleForm(rules);
    void this.renderFriends();
  }

  syncRuleForm(rules) {
    const form = this.el['lab-rules'];
    if (!form || form.dataset.filled === String(this.room?.version)) return;
    this.el['lab-rule-time'].value = String(rules.timeLimit ?? 30);
    this.el['lab-rule-nolimit'].checked = Boolean(rules.noLimit);
    this.el['lab-rule-lives'].value = String(rules.lives ?? 3);
    this.el['lab-rule-oneshot'].value = rules.oneShot === 'ban' ? 'ban' : 'allow';
    this.el['lab-rule-min'].value = String(rules.minLen ?? 2);
    this.el['lab-rule-max'].value = String(rules.maxLen ?? 12);
    this.el['lab-rule-banned'].value = rules.bannedChars || '';
    this.el['lab-rule-start'].value = rules.startChar || '';
    this.el['lab-rule-mission'].checked = rules.mission !== false;
    form.dataset.filled = String(this.room?.version || '');
  }

  renderPlay() {
    const room = this.room;
    const state = room.state || {};
    const turnSeat = Number(state.turnSeat);
    const seat = room.seats[turnSeat];
    const mineTurn = room.status === 'playing' && room.mySeat >= 0 && turnSeat === room.mySeat;
    this.el['lab-need'].textContent = state.needChar || '—';
    const alt = state.needChar ? allowedStarts(state.needChar)[1] : '';
    this.el['lab-need-alt'].hidden = !alt;
    this.el['lab-need-alt'].textContent = alt || '';
    this.el['lab-now'].textContent = room.status === 'playing'
      ? `${seat ? (seat.kind === 'bot' ? `봇 Lv.${seat.level}` : seat.name) : '—'} 차례`
      : '판이 끝났어요';
    const mission = this.el['lab-mission'];
    if (state.missionChar && room.rules.mission) {
      mission.hidden = false;
      mission.innerHTML = `미션 <b>${esc(state.missionChar)}</b>`;
    } else {
      mission.hidden = true;
    }
    this.el['lab-compose'].hidden = !mineTurn;
    this.el['lab-word'].disabled = !mineTurn;
    this.el['lab-submit'].disabled = !mineTurn;
    if (mineTurn) this.el['lab-word'].placeholder = '단어 입력';
    this.renderChain();
    this.renderTimer();
  }

  renderChain() {
    const box = this.el['lab-chain'];
    const room = this.room;
    if (!box || !room) return;
    const chain = (room.state?.chain || []).slice(-14).reverse();
    box.replaceChildren();
    if (!chain.length) {
      const li = document.createElement('li');
      li.className = 'lab-chain-empty';
      li.textContent = room.state?.startChar ? `첫 글자 ‘${room.state.startChar}’` : '아직 낸 단어가 없어요';
      box.appendChild(li);
      return;
    }
    for (const entry of chain) {
      const li = document.createElement('li');
      li.className = 'lab-chain-item';
      const who = document.createElement('span');
      who.className = 'lab-chain-who';
      who.textContent = entry.name || `자리 ${Number(entry.seat) + 1}`;
      const word = document.createElement('b');
      word.textContent = entry.word;
      const score = document.createElement('span');
      score.className = 'lab-chain-score';
      score.textContent = `+${Number(entry.score || 0).toLocaleString('ko-KR')}`;
      li.append(who, word, score);
      box.appendChild(li);
    }
  }

  renderTimer() {
    const el = this.el['lab-timer'];
    if (!el) return;
    const room = this.room;
    const state = room?.state || {};
    if (room?.status !== 'playing') {
      el.textContent = '';
      return;
    }
    if (room.rules?.noLimit) {
      el.textContent = '무제한';
      return;
    }
    const left = Math.max(0, Math.ceil((Number(state.deadline) - (Date.now() + this.clockOffset)) / 1000));
    el.textContent = `${left}초`;
    el.classList.toggle('urgent', left <= 5);
  }

  renderGodBots() {
    const box = this.el['lab-god-bots'];
    const room = this.room;
    if (!box || !room) return;
    box.replaceChildren();
    room.seats.forEach((seat, index) => {
      if (seat.kind !== 'bot') return;
      const li = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = `자리 ${index + 1} 봇`;
      const select = document.createElement('select');
      for (let level = 1; level <= 5; level += 1) {
        const option = document.createElement('option');
        option.value = String(level);
        option.textContent = `Lv.${level} ${LEVEL_NAMES[level]}`;
        if (Number(seat.level) === level) option.selected = true;
        select.appendChild(option);
      }
      select.addEventListener('change', () => this.god({ action: 'botLevel', seat: index, level: Number(select.value) }));
      li.append(label, select);
      box.appendChild(li);
    });
  }

  renderResult() {
    const room = this.room;
    const box = this.el['lab-result'];
    if (!box || room?.status !== 'over') {
      if (box) box.hidden = true;
      return;
    }
    const state = room.state || {};
    const winner = Number(state.winner);
    const winnerSeat = Number.isFinite(winner) && winner >= 0 ? room.seats[winner] : null;
    let title = '무승부';
    if (winnerSeat) {
      const isMine = room.mySeat === winner;
      title = isMine ? '승리' : `${winnerSeat.kind === 'bot' ? `봇 Lv.${winnerSeat.level}` : winnerSeat.name} 승리`;
    }
    this.el['lab-result-title'].textContent = title;
    const reasonText = {
      timeout: '시간 초과', stuck: '이을 단어 없음', leave: '자리 비움', 'last-alive': '마지막까지 살아남음', draw: '모두 탈락',
    }[state.reason] || '';
    const scores = room.seats.map((seat, index) => {
      const name = seat.kind === 'bot' ? `봇 Lv.${seat.level}` : seat.name;
      return `${esc(name)} ${Number(state.scores?.[index] || 0).toLocaleString('ko-KR')}`;
    }).join(' · ');
    this.el['lab-result-line'].textContent = `${reasonText ? `${reasonText} · ` : ''}${scores}`;
    this.el['lab-rematch'].hidden = !room.isHost;
    this.el['lab-quit'].textContent = room.isHost ? '방 닫기' : '나가기';
    box.hidden = false;
  }

  /** 마지막 사건을 토스트로 알린다(같은 사건을 두 번 띄우지 않는다). */
  surfaceEvent() {
    const room = this.room;
    const event = room?.state?.event;
    if (!event || !event.at || event.at <= this.lastEventAt) return;
    this.lastEventAt = event.at;
    const seat = Number(event.seat);
    const name = seat >= 0 ? (room.seats[seat]?.kind === 'bot'
      ? `봇 Lv.${room.seats[seat].level}` : room.seats[seat]?.name || `자리 ${seat + 1}`) : '';
    if (event.type === 'start') {
      this.toast(`실험실 게임 시작! 첫 글자 ‘${event.startChar}’`, 'mission');
      this.sfx?.play('start');
    } else if (event.type === 'life') {
      this.toast(`${name} 목숨 하나 잃음 — ${event.lives}개 남음`);
      this.sfx?.play('error');
    } else if (event.type === 'eliminated') {
      this.toast(`${name} 탈락${event.reason === 'timeout' ? ' (시간 초과)' : ''}`, 'mercy');
      this.sfx?.play('kill');
    } else if (event.type === 'seal') {
      this.toast(`신이 ‘${event.char}’ 글자를 봉인했어요`, 'mercy');
    } else if (event.type === 'pass') {
      this.toast('신이 차례를 넘겼어요');
    } else if (event.type === 'timeLimit') {
      this.toast(event.noLimit ? '신이 제한 시간을 없앴어요' : `신이 제한 시간을 ${event.timeLimit}초로 바꿨어요`);
    } else if (event.type === 'botLevel') {
      this.toast(`신이 자리 ${Number(event.seat) + 1} 봇을 Lv.${event.level}로 바꿨어요`);
    } else if (event.type === 'leave') {
      this.toast(`${name}님이 방을 나갔어요`);
    }
  }

  /* ── 진행: 시간 초과 · 봇 차례 ─────────────────────────── */

  tick() {
    const room = this.room;
    if (!room || room.status !== 'playing') return;
    this.renderTimer();
    const state = room.state || {};
    const turnSeq = Number(state.turnSeq);
    const now = Date.now() + this.clockOffset;
    const expired = !room.rules.noLimit && Number(state.deadline) > 0 && now >= Number(state.deadline) + 350;
    if (expired && this.timeoutSentFor !== turnSeq && (room.isHost || room.mySeat === Number(state.turnSeat))) {
      this.timeoutSentFor = turnSeq;
      void this.submitTurn({ seat: Number(state.turnSeat), turnSeq, action: 'timeout' });
    }
  }

  /** 방장 화면이 봇 차례를 진행한다(engine.js 의 AI 와 같은 bot.js 를 쓴다). */
  async hostWork() {
    const room = this.room;
    if (!room || !room.isHost || room.status !== 'playing' || this.busy || this.pendingWork) return;
    const state = room.state || {};
    const seatIndex = Number(state.turnSeat);
    const seat = room.seats[seatIndex];
    if (!seat || seat.kind !== 'bot') return;
    const turnSeq = Number(state.turnSeq);
    if (this.botSentFor === turnSeq) return;

    // 다음 차례가 봇이면 잠깐 생각하는 사이를 두고 낸다.
    if (!this.botThinkAt || this.botThinkAt.turnSeq !== turnSeq) {
      this.botThinkAt = { turnSeq, at: Date.now() + 420 + Math.random() * 520 };
      return;
    }
    if (Date.now() < this.botThinkAt.at) return;

    const used = new Set(state.used || []);
    const bot = new Bot({ level: Number(seat.level) || 2, dict: this.dict, rng: Math.random });
    const guard = room.rules.oneShot === 'ban';
    let move = null;
    try {
      move = bot.choose({
        needChar: state.needChar,
        used,
        turn: Number(state.rounds || 0) + 1,
        mission: room.rules.mission ? state.missionChar : null,
        guard,
      });
    } catch {
      move = null;
    }
    this.botSentFor = turnSeq;
    if (!move) {
      await this.submitTurn({ seat: seatIndex, turnSeq, action: 'stuck' });
      return;
    }
    await this.submitTurn({ seat: seatIndex, turnSeq, word: move.word });
  }

  async submitTurn({ seat, turnSeq, word = '', action = 'word' }) {
    if (!this.room) return;
    this.pendingWork = true;
    try {
      const res = await this.api(`/api/lab/rooms/${encodeURIComponent(this.code)}/turn`, {
        method: 'POST',
        body: { seat, turnSeq, word, action },
      });
      if (res.data?.room) this.applyRoom(res.data.room);
      if (!res.ok) {
        if (action === 'timeout' && res.status !== 429) this.timeoutSentFor = -1;
        if (res.data?.error === 'stale') return;          // 다음 폴링이 맞춘다
        if (action === 'word' && word) {
          this.showWordError(this.errorText(res.data));
          this.lastWord = null;
        } else if (res.status !== 0) {
          this.toast(this.errorText(res.data));
        }
      } else if (action === 'word') {
        this.sfx?.play('ok');
        this.el['lab-word'].value = '';
        this.showWordError('');
      }
    } finally {
      this.pendingWork = false;
    }
  }

  /* ── 내 입력 ──────────────────────────────────────────── */

  submitWord(event) {
    event?.preventDefault();
    const room = this.room;
    if (!room || room.status !== 'playing' || room.mySeat < 0) return;
    const input = this.el['lab-word'];
    const raw = input.value;
    const word = normalizeWord(raw);
    if (!word) return this.showWordError('단어를 입력해 주세요.');
    const state = room.state || {};
    if (room.mySeat !== Number(state.turnSeat)) return this.showWordError('아직 내 차례가 아니에요.');
    if (!allowedStarts(state.needChar).some((start) => word.startsWith(start))) {
      return this.showWordError(`‘${state.needChar}’(으)로 시작해야 해요.`);
    }
    if (room.rules.minLen && [...word].length < room.rules.minLen) {
      return this.showWordError(`${room.rules.minLen}글자 이상이어야 해요.`);
    }
    if (room.rules.maxLen && [...word].length > room.rules.maxLen) {
      return this.showWordError(`${room.rules.maxLen}글자까지 쓸 수 있어요.`);
    }
    const banned = (room.rules.bannedChars || '').split('').find((ch) => word.includes(ch));
    if (banned) return this.showWordError(`‘${banned}’는 방장이 봉인한 글자예요.`);
    if ((state.used || []).includes(word)) return this.showWordError('이미 나온 단어예요.');
    if (!this.dict.has(word)) return this.showWordError('사전에 없는 단어예요.');
    if (room.rules.oneShot === 'ban' && this.dict.isOneShot(word)) {
      return this.showWordError('이 방은 한방 단어를 쓸 수 없어요.');
    }
    this.showWordError('');
    this.sfx?.play('tap');
    void this.submitTurn({ seat: room.mySeat, turnSeq: Number(state.turnSeq), word });
  }

  showWordError(message) {
    const box = this.el['lab-word-error'];
    if (!box) return;
    box.hidden = !message;
    box.textContent = message || '';
    const input = this.el['lab-word'];
    if (message) {
      input.classList.add('bad');
      input.addEventListener('animationend', () => input.classList.remove('bad'), { once: true });
    }
  }

  claimStuck() {
    const room = this.room;
    if (!room || room.status !== 'playing' || room.mySeat < 0) return;
    const state = room.state || {};
    if (room.mySeat !== Number(state.turnSeat)) return this.toast('아직 내 차례가 아니에요.');
    void this.submitTurn({ seat: room.mySeat, turnSeq: Number(state.turnSeq), action: 'stuck' });
  }

  /* ── 방 만들기 · 나가기 ────────────────────────────────── */

  async createRoom() {
    if (!this.user) return this.account?.openAuth?.('login');
    if (this.busy) return;
    this.busy = true;
    this.el['lab-create'].disabled = true;
    try {
      const res = await this.api('/api/lab/rooms', { method: 'POST', body: {} });
      if (!res.ok) {
        this.toast(this.errorText(res.data));
        return;
      }
      this.lastVersion = 0;
      this.applyRoom(res.data.room);
      this.startPolling();
      this.sfx?.play('start');
      this.toast('실험실 방을 만들었어요. 친구를 초대해 보세요.');
    } finally {
      this.busy = false;
      this.el['lab-create'].disabled = false;
    }
  }

  async leaveRoom() {
    const room = this.room;
    if (!room) return this.onExit();
    if (room.isHost) {
      const res = await this.api(`/api/lab/rooms/${encodeURIComponent(room.code)}`, { method: 'DELETE' });
      if (!res.ok && res.data?.error !== 'room_not_found') {
        this.toast(this.errorText(res.data));
        return;
      }
      this.leaveLocalRoom();
      this.toast('실험실 방을 닫았어요.');
      this.onExit();
      return;
    }
    const res = await this.api(`/api/lab/rooms/${encodeURIComponent(room.code)}/leave`, { method: 'POST', body: {} });
    if (!res.ok) this.toast(this.errorText(res.data));
    this.leaveLocalRoom();
    this.onExit();
  }

  /* ── 자리 편집 (방장) ─────────────────────────────────── */

  seatPayload(seats) {
    return seats.map((seat) => ({
      kind: seat.kind,
      userId: seat.kind === 'bot' ? '' : (seat.userId || (seat.mine && this.user ? this.user.id : '')),
      level: seat.kind === 'bot' ? Number(seat.level || 2) : 0,
      name: seat.kind === 'bot' ? '' : seat.name || '',
      avatarAt: Number(seat.avatarAt || 0),
      status: seat.kind === 'bot' ? 'joined' : (seat.status || 'joined'),
    }));
  }

  async patchSeats(seats) {
    const room = this.room;
    if (!room || !room.isHost) return;
    await this.patch({ action: 'seats', seats: this.seatPayload(seats) });
  }

  async patch(payload) {
    if (!this.room || !this.room.isHost) return { ok: false };
    this.patching = true;
    try {
      // 봇이 한 수를 두면 방 버전이 바뀐다 — 방장 동작이 그 사이 나가면 409 가 오므로
      // 최신 상태를 한 번 받아 같은 동작을 다시 보낸다(최대 3번).
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const room = this.room;
        if (!room) break;
        const res = await this.api(`/api/lab/rooms/${encodeURIComponent(room.code)}`, {
          method: 'PATCH',
          body: { ...payload, version: room.version },
        });
        if (res.data?.room) this.applyRoom(res.data.room);
        if (res.ok) return res;
        if (res.data?.error === 'version_conflict' && attempt < 2) {
          const fresh = await this.api(`/api/lab/rooms/${encodeURIComponent(room.code)}`);
          if (fresh.ok && fresh.data?.room) this.applyRoom(fresh.data.room);
          else return res;
          continue;
        }
        if (res.data?.error !== 'version_conflict') this.toast(this.errorText(res.data));
        return res;
      }
      return { ok: false, status: 0, data: { error: 'version_conflict' } };
    } finally {
      this.patching = false;
    }
  }

  cycleBot(index) {
    const room = this.room;
    if (!room) return;
    const seats = room.seats.map((seat) => ({ ...seat }));
    const level = (Number(seats[index].level) % 5) + 1;
    seats[index] = { ...seats[index], kind: 'bot', level, status: 'joined', userId: '' };
    void this.patchSeats(seats);
    this.sfx?.play('tap');
  }

  addSeat() {
    const room = this.room;
    if (!room || room.seats.length >= 8) return;
    const seats = room.seats.map((seat) => ({ ...seat }));
    seats.push({ kind: 'bot', level: 2, status: 'joined', userId: '', name: '' });
    void this.patchSeats(seats);
    this.sfx?.play('tap');
  }

  removeSeat(index) {
    const room = this.room;
    if (!room || room.seats.length <= 2) {
      this.toast('최소 두 자리는 남겨야 해요.');
      return;
    }
    const seats = room.seats.filter((_, i) => i !== index).map((seat) => ({ ...seat }));
    void this.patchSeats(seats);
    this.sfx?.play('tap');
  }

  moveSeat(index, dir) {
    const room = this.room;
    if (!room) return;
    const seats = room.seats.map((seat) => ({ ...seat }));
    const to = index + dir;
    if (to < 0 || to >= seats.length) return;
    // 방장 자리는 늘 맨 위에 둔다(방장은 신이라 자기 자리를 움직이지 않는다).
    if (seats[to].kind === 'host') return;
    const [item] = seats.splice(index, 1);
    seats.splice(to, 0, item);
    void this.patchSeats(seats);
    this.sfx?.play('tap');
  }

  /* ── 룰 저장 · 게임 시작 ──────────────────────────────── */

  readRulesFromForm() {
    const raw = this.el['lab-rule-time'].value.trim();
    const noLimit = this.el['lab-rule-nolimit'].checked;
    if (!noLimit && !/^\d{1,3}$/.test(raw)) {
      this.showRuleError('턴 제한 시간은 1~999 사이 숫자로 적어 주세요.');
      return null;
    }
    if (!noLimit && (Number(raw) < 1 || Number(raw) > 999)) {
      this.showRuleError('턴 제한 시간은 1~999초 사이로 정해 주세요.');
      return null;
    }
    const timeLimit = clampInt(raw, 1, 999, 30);
    const minLen = clampInt(this.el['lab-rule-min'].value, 1, 10, 2);
    const maxLen = clampInt(this.el['lab-rule-max'].value, 2, 30, 12);
    if (minLen > maxLen) {
      this.showRuleError('최소 글자 수가 최대 글자 수보다 클 수 없어요.');
      return null;
    }
    const startChar = this.el['lab-rule-start'].value.trim();
    if (startChar && !isHangulChar(startChar)) {
      this.showRuleError('첫 제시 글자는 한글 한 글자로 적어 주세요.');
      return null;
    }
    this.showRuleError('');
    return {
      timeLimit,
      noLimit,
      lives: clampInt(this.el['lab-rule-lives'].value, 1, 5, 3),
      oneShot: this.el['lab-rule-oneshot'].value === 'ban' ? 'ban' : 'allow',
      minLen,
      maxLen,
      startChar,
      bannedChars: this.el['lab-rule-banned'].value,
      mission: this.el['lab-rule-mission'].checked,
    };
  }

  showRuleError(message) {
    const box = this.el['lab-rule-error'];
    if (!box) return;
    box.hidden = !message;
    box.textContent = message || '';
  }

  /** 숫자 말고는 턴 제한 시간 입력에 들어가지 않게 한다(1~999 텍스트 인풋). */
  filterTimeInput(input) {
    const cleaned = String(input.value || '').replace(/[^0-9]/g, '').slice(0, 3);
    if (input.value !== cleaned) input.value = cleaned;
  }

  async saveRules({ silent = false } = {}) {
    const rules = this.readRulesFromForm();
    if (!rules) return false;
    const res = await this.patch({ action: 'rules', rules });
    if (res.ok) {
      if (!silent) this.toast('방 룰을 저장했어요.');
      this.sfx?.play('tap');
      return true;
    }
    return false;
  }

  async startGame() {
    const room = this.room;
    if (!room || !room.isHost) return;
    if (room.filled < 2) return this.toast('최소 두 자리를 채워야 시작할 수 있어요.');
    const saved = await this.saveRules({ silent: true });
    if (!saved) return;
    const startChar = this.el['lab-rule-start'].value.trim();
    if (startChar && this.dict.candidatesFor(startChar, new Set()).length === 0) {
      return this.showRuleError(`‘${startChar}’로 시작하는 단어가 사전에 없어요. 다른 글자를 골라 주세요.`);
    }
    const res = await this.patch({ action: 'start', startChar });
    if (res.ok) {
      this.lastEventAt = 0;
      this.sfx?.play('start');
      this.el['lab-word'].value = '';
      this.showWordError('');
    }
  }

  /* ── 신 모드 ──────────────────────────────────────────── */

  async god(payload) {
    const res = await this.patch(payload);
    if (!res.ok && res.data?.error === 'version_conflict') this.toast('방 상태가 막 바뀌었어요. 다시 한 번 눌러 주세요.');
    return res;
  }

  applyGodTime() {
    const raw = this.el['lab-god-time'].value.trim();
    if (!/^\d{1,3}$/.test(raw)) {
      this.el['lab-god-error'].hidden = false;
      this.el['lab-god-error'].textContent = '1~999 사이 숫자로 적어 주세요.';
      return;
    }
    const value = Number(raw);
    if (value < 1 || value > 999) {
      this.el['lab-god-error'].hidden = false;
      this.el['lab-god-error'].textContent = '1~999 사이 숫자로 적어 주세요.';
      return;
    }
    this.el['lab-god-error'].hidden = true;
    void this.god({ action: 'timeLimit', timeLimit: value, noLimit: false });
  }

  applyGodSeal() {
    const ch = this.el['lab-god-seal'].value.trim();
    if (!isHangulChar(ch)) {
      this.el['lab-god-error'].hidden = false;
      this.el['lab-god-error'].textContent = '봉인할 글자를 한 글자로 적어 주세요.';
      return;
    }
    this.el['lab-god-error'].hidden = true;
    void this.god({ action: 'seal', char: ch });
    this.el['lab-god-seal'].value = '';
  }

  /* ── 친구 목록 · 초대 ──────────────────────────────────── */

  async loadFriends({ force = false } = {}) {
    if (!this.user) return;
    const now = Date.now();
    if (!force && now - this.friendsAt < 10000 && this.friends.length) return;
    const res = await this.api('/api/friends');
    if (!res.ok) return;
    this.friends = Array.isArray(res.data?.friends) ? res.data.friends : [];
    this.friendsAt = Date.now();
  }

  async renderFriends() {
    const box = this.el['lab-friends'];
    if (!box) return;
    if (!this.room?.isHost) {
      box.replaceChildren();
      return;
    }
    await this.loadFriends();
    if (!this.room?.isHost) return;
    box.replaceChildren();
    if (!this.friends.length) {
      const li = document.createElement('li');
      li.className = 'lab-friend-empty';
      li.textContent = '아직 친구가 없어요. 계정 창의 친구 탭에서 아이디로 친구를 찾아보세요.';
      box.appendChild(li);
      return;
    }
    const seated = new Set(this.room.seats.filter((seat) => seat.kind === 'friend' && seat.userId).map((seat) => seat.userId));
    for (const friend of this.friends) {
      const li = document.createElement('li');
      li.className = 'lab-friend';
      const dot = document.createElement('i');
      dot.className = `friend-dot ${friend.online ? 'on' : ''}`;
      dot.setAttribute('aria-hidden', 'true');
      const name = document.createElement('span');
      name.className = 'lab-friend-name';
      name.textContent = friend.displayName || friend.username;
      const meta = document.createElement('small');
      meta.textContent = friend.online ? '접속 중' : '오프라인';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn ghost lab-invite-btn';
      if (seated.has(friend.id)) {
        btn.textContent = '초대됨';
        btn.disabled = true;
      } else {
        btn.textContent = '초대';
        btn.addEventListener('click', () => this.inviteFriend(friend, btn));
      }
      li.append(dot, name, meta, btn);
      box.appendChild(li);
    }
  }

  async inviteFriend(friend, btn) {
    const room = this.room;
    if (!room || !room.isHost) return;
    // 초대할 자리: 봇 자리를 먼저, 없으면 새 자리를 붙인다.
    const seats = room.seats.map((seat) => ({ ...seat }));
    let index = seats.findIndex((seat) => seat.kind === 'bot');
    if (index < 0) {
      if (seats.length >= 8) return this.toast('자리가 다 찼어요. 자리를 하나 비우고 초대해 주세요.');
      seats.push({ kind: 'bot', level: 2, status: 'joined', userId: '', name: '' });
      index = seats.length - 1;
    }
    // 좌석 구조를 먼저 저장하고(새 자리 만들기), 그다음 그 자리에 초대한다.
    if (seats.length !== room.seats.length) {
      const res = await this.patchSeats(seats);
      if (!res || res.ok === false) return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '보내는 중…'; }
    const res = await this.patch({ action: 'invite', seat: index, userId: friend.id });
    if (res.ok) {
      this.sfx?.play('tap');
      this.toast(`${friend.displayName || friend.username}님에게 초대를 보냈어요.`);
    }
    if (btn && btn.isConnected) {
      btn.disabled = false;
      btn.textContent = '초대';
    }
    void this.renderFriends();
  }

  /* ── 초대 받기 ─────────────────────────────────────────── */

  startInviteWatch() {
    clearInterval(this.inviteTimer);
    this.inviteTimer = setInterval(() => {
      if (document.visibilityState === 'visible') void this.pollInvites();
    }, INVITE_MS);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void this.pollInvites();
    });
  }

  async pollInvites() {
    if (!this.user) return this.hideInvite();
    const res = await this.api('/api/lab/invites');
    if (!res.ok) return;
    this.invites = Array.isArray(res.data?.invites) ? res.data.invites : [];
    const pending = this.invites.find((invite) => invite.id !== this.dismissedInvite);
    if (!pending) {
      this.hideInvite();
      return;
    }
    this.activeInvite = pending;
    this.el['lab-invite-from'].textContent = pending.fromName || '친구';
    this.el['lab-invite-seat'].textContent = pending.roomStatus === 'lobby'
      ? `자리 ${pending.seat + 1} · 코드 ${pending.code}`
      : '이미 시작된 방';
    this.el['lab-invite-pop'].hidden = false;
  }

  hideInvite() {
    this.activeInvite = null;
    if (this.el['lab-invite-pop']) this.el['lab-invite-pop'].hidden = true;
  }

  async respondInvite(action) {
    const invite = this.activeInvite;
    if (!invite) return;
    this.dismissedInvite = invite.id;
    this.hideInvite();
    const res = await this.api('/api/lab/invites', { method: 'POST', body: { id: invite.id, action } });
    if (!res.ok) {
      this.toast(this.errorText(res.data));
      return;
    }
    if (action === 'decline') {
      this.toast('초대를 거절했어요.');
      return;
    }
    this.lastVersion = 0;
    this.applyRoom(res.data.room);
    this.startPolling();
    this.toast('실험실에 초대돼 앉았어요!');
    this.sfx?.play('start');
    this.onEnterRoom?.(this.room);
  }

  /* ── 이벤트 ───────────────────────────────────────────── */

  bind() {
    this.el['btn-lab'].addEventListener('click', () => {
      this.sfx?.play('tap');
      this.open();
      this.onOpen?.();
    });
    this.el['lab-back'].addEventListener('click', () => {
      this.sfx?.play('tap');
      this.onExit();
    });
    this.el['lab-leave'].addEventListener('click', () => void this.leaveRoom());
    this.el['lab-login'].addEventListener('click', () => this.account?.openAuth?.('login'));
    this.el['lab-create'].addEventListener('click', () => void this.createRoom());
    this.el['lab-copy'].addEventListener('click', () => {
      const code = this.room?.code;
      if (!code) return;
      void this.copyText(code);
    });
    this.el['lab-start'].addEventListener('click', () => void this.startGame());
    this.el['lab-rule-save'].addEventListener('click', () => void this.saveRules());
    this.el['lab-rule-time'].addEventListener('input', () => this.filterTimeInput(this.el['lab-rule-time']));
    this.el['lab-god-time'].addEventListener('input', () => this.filterTimeInput(this.el['lab-god-time']));
    this.el['lab-rule-nolimit'].addEventListener('change', () => {
      this.el['lab-rule-time'].disabled = this.el['lab-rule-nolimit'].checked;
    });
    this.el['lab-rules'].addEventListener('submit', (event) => {
      event.preventDefault();
      void this.saveRules();
    });
    this.el['lab-form'].addEventListener('submit', (event) => this.submitWord(event));
    this.el['lab-stuck'].addEventListener('click', () => this.claimStuck());
    this.el['lab-word'].addEventListener('input', () => this.showWordError(''));
    this.el['lab-god-time-btn'].addEventListener('click', () => this.applyGodTime());
    this.el['lab-god-seal-btn'].addEventListener('click', () => this.applyGodSeal());
    this.el['lab-god-pass'].addEventListener('click', () => void this.god({ action: 'pass' }));
    this.el['lab-rematch'].addEventListener('click', () => void this.god({ action: 'rematch' }));
    this.el['lab-quit'].addEventListener('click', () => void this.leaveRoom());
    this.el['lab-invite-accept'].addEventListener('click', () => void this.respondInvite('accept'));
    this.el['lab-invite-decline'].addEventListener('click', () => void this.respondInvite('decline'));
    this.el['lab-word'].addEventListener('keydown', (event) => {
      // 한글 조합 중 Enter 는 조합 확정에 쓰이므로 그대로 둔다.
      if (event.key === 'Enter' && event.isComposing) event.preventDefault();
    });
  }

  async copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      this.toast(`방 코드 ${text}를 복사했어요.`);
    } catch {
      this.toast(`방 코드는 ${text} 예요.`);
    }
  }
}
