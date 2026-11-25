/**
 * 친구 (아이디 검색 · 받은 요청 · 친구 목록 · 보낸 요청).
 *
 * 서버는 Cloudflare Pages Functions(`/api/friends/*`) + D1 이다.
 *   - 아이디(`@아이디`)로 사람을 찾아 친구 요청을 보낸다(2자 이상, 최대 8건).
 *   - 상대가 수락하면 친구가 되고, 친구 목록에서 바로 메일을 보내거나 친구를 끊을 수 있다.
 *   - 받은 요청이 있으면 상단 계정 버튼과 친구 탭에 빨간 점이 뜬다.
 *
 * 이 창은 `내 계정` 시트 안의 한 탭이라, 시트 자체의 열고 닫기는 account.js 가 맡는다.
 * 서버에서 온 글자는 언제나 textContent 로만 넣는다(innerHTML 로 넣지 않는다).
 */

const $ = (id) => document.getElementById(id);

const ERROR_TEXT = {
  not_signed_in: '로그인하면 친구를 찾고 요청을 주고받을 수 있어요.',
  query_short: '아이디를 두 글자 이상 넣어 주세요.',
  query_invalid: '아이디는 2~12자의 한글·영문·숫자·밑줄이에요.',
  user_not_found: '그 아이디를 찾지 못했어요.',
  username_invalid: '친구로 찾을 아이디는 2~12자의 한글·영문·숫자·밑줄이에요.',
  self_request: '자기 자신에게는 친구 요청을 보낼 수 없어요.',
  already_friends: '이미 친구예요.',
  already_requested: '이미 친구 요청을 보냈어요. 상대가 수락하면 친구가 돼요.',
  request_not_found: '이미 처리됐거나 찾을 수 없는 요청이에요.',
  friend_not_found: '이미 친구가 아니에요.',
  rate_limited: '너무 자주 눌렀어요. 잠시 후 다시 시도해 주세요.',
  network: '연결이 잠시 불안정해요. 잠시 후 다시 시도해 주세요.',
  default: '잠시 문제가 생겼어요. 다시 시도해 주세요.',
};

const TAB_HINT = {
  incoming: ['아직 받은 요청이 없어요', '친구가 되고 싶은 사람이 요청을 보내면 여기에 와요.'],
  friends: ['아직 친구가 없어요', '위에서 @아이디로 찾아 친구 요청을 보내 보세요.'],
  outgoing: ['보낸 요청이 없어요', '요청을 보내면 상대가 수락할 때까지 여기에 남아요.'],
};

/** DOM 을 글자 그대로 만든다. */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/** 닉네임(없으면 아이디)의 첫 글자 — 사진이 없을 때 쓰는 글자 아바타. */
function letterOf(user) {
  const name = String(user?.displayName || user?.username || '잇').trim();
  return [...name][0] || '잇';
}

/** 사진 주소. 사진을 바꾸면 avatarAt 이 달라져 캐시된 예전 사진이 남지 않는다. */
function avatarSrc(user) {
  if (!user?.id || !Number(user.avatarAt)) return '';
  return `/api/account/avatar?u=${encodeURIComponent(user.id)}&v=${Number(user.avatarAt)}`;
}

export class FriendsPanel {
  constructor({ sfx, toast, account, onComposeMail, onCounts } = {}) {
    this.sfx = sfx;
    this.toast = toast || (() => {});
    this.account = account || null;
    this.onComposeMail = onComposeMail || (() => {});
    this.onCounts = onCounts || (() => {});
    this.user = null;
    this.tab = 'incoming';
    this.list = { friends: [], incoming: [], outgoing: [] };
    this.counts = { friends: 0, incoming: 0, outgoing: 0 };
    this.results = [];
    this.query = '';
    this.busy = false;
    this.loading = false;
    this.loadedAt = 0;
    this.armed = null;
    this.el = {};
  }

  init() {
    const ids = [
      'account-view-friends', 'friend-search-form', 'friend-search-input', 'friend-search-btn',
      'friend-status', 'friend-results', 'friend-tabs', 'friend-list', 'friend-empty',
      'friend-empty-title', 'friend-empty-desc', 'friend-dot-incoming',
    ];
    for (const id of ids) this.el[id] = $(id);
    if (!this.el['account-view-friends']) return;
    this.bind();
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
    const res = await fetch(path, init);
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (res.status === 401) this.handleAuthLost();
    return { ok: res.ok && Boolean(data && data.ok !== false), status: res.status, data };
  }

  handleAuthLost() {
    if (!this.user) return;
    this.setUser(null);
    this.account?.refreshUser?.({ force: true });
  }

  errorText(data) {
    return ERROR_TEXT[data?.error] || data?.message || ERROR_TEXT.default;
  }

  setUser(user) {
    this.user = user || null;
    if (!this.user) {
      this.list = { friends: [], incoming: [], outgoing: [] };
      this.results = [];
      this.counts = { friends: 0, incoming: 0, outgoing: 0 };
      this.query = '';
      if (this.el['friend-search-input']) this.el['friend-search-input'].value = '';
      this.renderResults();
      this.renderList();
      this.setStatus('');
      this.applyCounts();
    }
  }

  /** 받은 요청 수를 상단 버튼·탭의 빨간 점과 숫자에 알린다. */
  applyCounts() {
    this.onCounts({ ...this.counts });
  }

  setCounts(counts) {
    if (!counts) return;
    this.counts = {
      friends: Number(counts.friends || 0),
      incoming: Number(counts.incoming || 0),
      outgoing: Number(counts.outgoing || 0),
    };
    this.applyCounts();
  }

  /** 시트가 열릴 때·친구 탭으로 옮길 때 목록을 새로 읽는다(8초 안이면 그대로). */
  async open({ force = false } = {}) {
    if (!this.user) return;
    const now = Date.now();
    if (!force && now - this.loadedAt < 8000 && this.list.incoming.length + this.list.friends.length + this.list.outgoing.length) {
      this.renderList();
      return;
    }
    await this.load();
  }

  async load() {
    if (!this.user) {
      this.renderList();
      return;
    }
    this.loading = true;
    this.setStatus('불러오는 중…');
    try {
      const res = await this.api('/api/friends');
      if (!res.ok) {
        this.setStatus(this.errorText(res.data));
        this.renderList();
        return;
      }
      const data = res.data || {};
      this.list = {
        friends: Array.isArray(data.friends) ? data.friends : [],
        incoming: Array.isArray(data.incoming) ? data.incoming : [],
        outgoing: Array.isArray(data.outgoing) ? data.outgoing : [],
      };
      this.setCounts(data.counts || {
        friends: this.list.friends.length,
        incoming: this.list.incoming.length,
        outgoing: this.list.outgoing.length,
      });
      this.loadedAt = Date.now();
      this.setStatus('');
      this.renderList();
      this.updateResultRelations();
    } catch {
      this.setStatus(ERROR_TEXT.network);
      this.renderList();
    } finally {
      this.loading = false;
    }
  }

  /** 상단 계정 버튼·탭의 빨간 점만 갱신한다(60초 주기). */
  async refreshSummary() {
    if (!this.user) return;
    try {
      const res = await this.api('/api/friends/summary');
      if (res.ok && res.data) this.setCounts(res.data);
    } catch {
      /* 잠깐 끊긴 것뿐이면 지금 숫자를 그대로 둔다 */
    }
  }

  /* ── 탭 ───────────────────────────────────────────────── */

  showTab(tab) {
    this.tab = TAB_HINT[tab] ? tab : 'incoming';
    this.el['friend-tabs'].querySelectorAll('[data-friend-tab]').forEach((btn) => {
      btn.setAttribute('aria-selected', String(btn.dataset.friendTab === this.tab));
    });
    this.cancelArmed();
    this.renderList();
  }

  setStatus(text) {
    const node = this.el['friend-status'];
    if (!node) return;
    node.hidden = !text;
    node.textContent = text || '';
  }

  /* ── 그리기 ───────────────────────────────────────────── */

  avatarNode(user, className) {
    const box = el('span', className);
    const src = avatarSrc(user);
    if (src) {
      const img = el('img');
      img.src = src;
      img.alt = '';
      img.loading = 'lazy';
      img.decoding = 'async';
      img.addEventListener('error', () => {
        img.remove();
        box.textContent = letterOf(user);
      });
      box.appendChild(img);
    } else {
      box.textContent = letterOf(user);
    }
    return box;
  }

  /** 사람 한 줄: 사진 · 닉네임 · @아이디 · (관계에 맞는 버튼). */
  personNode(user, place) {
    const item = el('li', 'friend-item');
    item.dataset.id = user.id;
    item.appendChild(this.avatarNode(user, 'friend-avatar'));
    if (user.online) {
      // 접속 중(90초 안에 활동) 표시 — 초록 점
      const dot = el('i', 'friend-online');
      dot.setAttribute('aria-label', '접속 중');
      dot.title = '접속 중';
      item.appendChild(dot);
      item.classList.add('is-online');
    }

    const who = el('div', 'friend-who');
    // 닉네임이 있으면 `닉네임` + `@아이디`, 없으면 아이디가 곧 이름이라 `@아이디` 하나만.
    if (user.nickname) {
      who.appendChild(el('b', 'friend-name', user.displayName || user.nickname));
      who.appendChild(el('small', 'friend-handle', `@${user.username}`));
      if (user.online) who.appendChild(el('small', 'friend-live', '접속 중'));
    } else {
      who.appendChild(el('b', 'friend-name', `@${user.username}`));
    }
    item.appendChild(who);

    const actions = el('div', 'friend-actions');
    const add = (label, cls, onClick) => {
      const btn = el('button', `btn friend-btn ${cls}`, label);
      btn.type = 'button';
      btn.addEventListener('click', () => onClick(btn));
      actions.appendChild(btn);
      return btn;
    };

    if (place === 'search') {
      if (user.relation === 'friend') {
        add('메일', 'ghost', () => this.composeMail(user));
        const done = add('친구', 'ghost is-done', () => {});
        done.disabled = true;
        done.setAttribute('aria-disabled', 'true');
      } else if (user.relation === 'incoming') {
        add('수락', 'primary', (btn) => this.respond(user, 'accept', btn));
        add('거절', 'ghost', (btn) => this.respond(user, 'decline', btn));
      } else if (user.relation === 'outgoing') {
        add('요청 취소', 'ghost', (btn) => this.respond(user, 'cancel', btn));
      } else {
        add('친구 요청', 'primary', (btn) => this.request(user, btn));
      }
    } else if (place === 'incoming') {
      add('수락', 'primary', (btn) => this.respond(user, 'accept', btn));
      add('거절', 'ghost', (btn) => this.respond(user, 'decline', btn));
    } else if (place === 'outgoing') {
      add('요청 취소', 'ghost', (btn) => this.respond(user, 'cancel', btn));
    } else {
      add('메일', 'ghost', () => this.composeMail(user));
      add('삭제', 'ghost danger', (btn) => {
        this.arm(btn, '정말 삭제?', async () => {
          await this.remove(user);
        });
      });
    }

    item.appendChild(actions);
    return item;
  }

  renderList() {
    const list = this.el['friend-list'];
    if (!list) return;
    list.replaceChildren();
    const items = this.list[this.tab] || [];
    const empty = this.el['friend-empty'];
    if (!items.length) {
      empty.hidden = false;
      const [title, desc] = TAB_HINT[this.tab];
      this.el['friend-empty-title'].textContent = this.user ? title : '로그인하면 친구를 쓸 수 있어요';
      this.el['friend-empty-desc'].textContent = this.user ? desc : '아이디로 친구를 찾아 요청을 주고받을 수 있어요.';
      return;
    }
    empty.hidden = true;
    for (const user of items) list.appendChild(this.personNode(user, this.tab));
  }

  renderResults() {
    const list = this.el['friend-results'];
    if (!list) return;
    list.replaceChildren();
    if (!this.results.length) return;
    for (const user of this.results) list.appendChild(this.personNode(user, 'search'));
  }

  /** 검색 결과의 관계 표시(친구/요청됨)를 최신 목록에 맞춘다. */
  updateResultRelations() {
    if (!this.results.length) return;
    const rel = new Map();
    for (const user of this.list.friends) rel.set(user.id, 'friend');
    for (const user of this.list.incoming) rel.set(user.id, 'incoming');
    for (const user of this.list.outgoing) rel.set(user.id, 'outgoing');
    this.results = this.results.map((user) => ({ ...user, relation: rel.get(user.id) || 'none' }));
    this.renderResults();
  }

  /* ── 검색 ─────────────────────────────────────────────── */

  async search(event) {
    event?.preventDefault();
    if (!this.user) return this.account?.openAuth?.('login');
    if (this.busy) return;
    const raw = this.el['friend-search-input'].value.trim();
    const query = raw.replace(/^@+/, '').trim();
    if ([...query].length < 2) {
      this.results = [];
      this.renderResults();
      this.setStatus(ERROR_TEXT.query_short);
      return;
    }
    this.busy = true;
    const btn = this.el['friend-search-btn'];
    btn.disabled = true;
    this.setStatus('찾는 중…');
    try {
      const res = await this.api(`/api/friends/search?q=${encodeURIComponent(query)}`);
      if (!res.ok) {
        this.results = [];
        this.renderResults();
        this.setStatus(this.errorText(res.data));
        return;
      }
      this.query = query;
      this.results = Array.isArray(res.data?.results) ? res.data.results : [];
      this.renderResults();
      this.setStatus(this.results.length
        ? `‘${query}’ 로 찾은 아이디 ${this.results.length}개`
        : `‘${query}’ 로 찾은 아이디가 없어요.`);
      if (this.results.length) this.sfx?.play('tap');
    } catch {
      this.setStatus(ERROR_TEXT.network);
    } finally {
      this.busy = false;
      btn.disabled = false;
    }
  }

  /* ── 요청 · 수락 · 거절 · 취소 · 삭제 ─────────────────── */

  async request(user, btn) {
    if (!this.user || this.busy) return;
    this.busy = true;
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = '보내는 중…';
    try {
      const res = await this.api('/api/friends/request', {
        method: 'POST',
        body: { userId: user.id },
      });
      if (!res.ok) {
        if (res.data?.error === 'already_friends' || res.data?.error === 'already_requested') {
          this.toast(this.errorText(res.data));
          await this.load();
          return;
        }
        this.toast(this.errorText(res.data));
        return;
      }
      this.setCounts(res.data?.counts);
      this.sfx?.play('tap');
      this.toast(res.data?.accepted
        ? `@${user.username}님과 친구가 됐어요.`
        : `@${user.username}님에게 친구 요청을 보냈어요.`);
      await this.load();
    } catch {
      this.toast(ERROR_TEXT.network);
    } finally {
      this.busy = false;
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  async respond(user, action, btn) {
    if (!this.user || this.busy) return;
    this.busy = true;
    if (btn) {
      btn.disabled = true;
      btn.dataset.label = btn.textContent;
      btn.textContent = action === 'accept' ? '수락 중…' : '처리 중…';
    }
    try {
      const res = await this.api('/api/friends/respond', {
        method: 'POST',
        body: { userId: user.id, action },
      });
      if (!res.ok) {
        this.toast(this.errorText(res.data));
        if (res.status === 404) await this.load();
        return;
      }
      this.setCounts(res.data?.counts);
      this.sfx?.play('tap');
      this.toast(action === 'accept'
        ? `@${user.username}님과 친구가 됐어요.`
        : action === 'decline'
          ? '친구 요청을 거절했어요.'
          : '친구 요청을 취소했어요.');
      await this.load();
    } catch {
      this.toast(ERROR_TEXT.network);
    } finally {
      this.busy = false;
      if (btn && btn.isConnected) {
        btn.disabled = false;
        btn.textContent = btn.dataset.label || btn.textContent;
      }
    }
  }

  async remove(user) {
    if (!this.user || this.busy) return;
    this.busy = true;
    try {
      const res = await this.api('/api/friends/remove', {
        method: 'POST',
        body: { userId: user.id },
      });
      if (!res.ok) {
        this.toast(this.errorText(res.data));
        return;
      }
      this.setCounts(res.data?.counts);
      this.toast(`@${user.username}님과 친구를 끊었어요.`);
      await this.load();
    } catch {
      this.toast(ERROR_TEXT.network);
    } finally {
      this.busy = false;
    }
  }

  /** 친구 목록에서 `메일` → 메일함 새 메일 쓰기에 @아이디를 채워 연다. */
  composeMail(user) {
    if (!this.user) return;
    this.account?.closeAccount?.(true);
    this.onComposeMail(`@${user.username}`);
  }

  /* ── 두 번 눌러 확인(친구 삭제) ───────────────────────── */

  cancelArmed() {
    if (!this.armed) return;
    clearTimeout(this.armed.timer);
    if (this.armed.node && this.armed.node.isConnected) {
      this.armed.node.textContent = this.armed.label;
      this.armed.node.classList.remove('armed');
    }
    this.armed = null;
  }

  arm(node, armedLabel, run) {
    if (this.armed && this.armed.node === node) {
      this.cancelArmed();
      void run();
      return;
    }
    this.cancelArmed();
    const original = node.textContent;
    node.textContent = armedLabel;
    node.classList.add('armed');
    const timer = setTimeout(() => {
      if (node.isConnected) node.textContent = original;
      node.classList.remove('armed');
      this.armed = null;
    }, 4000);
    this.armed = { node, label: original, timer };
  }

  /* ── 이벤트 ───────────────────────────────────────────── */

  bind() {
    this.el['friend-search-form'].addEventListener('submit', (event) => this.search(event));
    this.el['friend-tabs'].addEventListener('click', (event) => {
      const btn = event.target.closest('[data-friend-tab]');
      if (!btn || btn.dataset.friendTab === this.tab) return;
      this.sfx?.play('tap');
      this.showTab(btn.dataset.friendTab);
    });
    this.el['friend-search-input'].addEventListener('input', () => {
      if (this.el['friend-status'] && !this.el['friend-status'].hidden) this.setStatus('');
    });
    this.el['account-view-friends'].addEventListener('click', (event) => {
      if (event.target === this.el['account-view-friends']) this.cancelArmed();
    });
  }
}
