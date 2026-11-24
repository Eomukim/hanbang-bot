/**
 * 메일함 (받은 메일 · 보낸 메일 · 공지사항).
 *
 * 서버는 Cloudflare Pages Functions(`/api/mail/*`) + D1 이다.
 *   - 로그인한 플레이어끼리 쪽지를 주고받고, 받은 메일에 답장(Re:)할 수 있다.
 *   - 공지사항은 누구나(게스트 포함) 읽고, `ADMIN_USERNAMES` 관리자만 쓴다.
 *   - 안 읽은 메일이나 새 공지가 있으면 상단 메일함 버튼에 빨간 동그라미가 뜬다.
 *     로그인 사용자는 서버(notice_reads·is_read), 게스트는 이 기기의 마지막 확인 시각으로 판단한다.
 *
 * 이 파일은 서버에서 온 글자를 화면에 넣을 때 textContent 만 쓴다(innerHTML 로 넣지 않는다).
 */

const $ = (id) => document.getElementById(id);

/** 게스트가 마지막으로 공지를 확인한 시각(epoch ms). */
const NOTICE_SEEN_KEY = 'itda.mail.noticeSeenAt';
const SUMMARY_REFRESH_MS = 60 * 1000;

const ERROR_TEXT = {
  not_signed_in: '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.',
  recipient_required: '받는 사람 아이디를 입력해 주세요.',
  recipient_invalid: '아이디는 2~12자의 한글·영문·숫자·밑줄로 적어 주세요.',
  recipient_not_found: '그 아이디를 찾지 못했어요. 받는 사람 아이디를 다시 확인해 주세요.',
  self_mail: '자기 자신에게는 메일을 보낼 수 없어요.',
  subject_required: '제목을 입력해 주세요.',
  subject_long: '제목은 80자까지 쓸 수 있어요.',
  body_required: '내용을 입력해 주세요.',
  body_long: '내용은 2000자까지 쓸 수 있어요.',
  reply_invalid: '답장할 메일을 찾지 못했어요. 목록에서 다시 열어 주세요.',
  rate_limited: '너무 빨리 많이 보냈어요. 잠시 후 다시 시도해 주세요.',
  forbidden: '공지 작성은 관리자만 할 수 있어요.',
  title_required: '공지 제목을 입력해 주세요.',
  title_long: '공지 제목은 100자까지 쓸 수 있어요.',
  not_found: '이미 지운 항목이에요.',
  network: '연결이 잠시 불안정해요. 잠시 후 다시 시도해 주세요.',
  default: '잠시 문제가 생겼어요. 다시 시도해 주세요.',
};

/** DOM 을 글자 그대로 만든다(서버에서 온 값은 전부 textContent). */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const pad2 = (n) => String(n).padStart(2, '0');

/** 오늘이면 `11.24 18:02`, 다른 해면 `2025.11.24 18:02`. */
function formatWhen(ts) {
  const date = new Date(Number(ts));
  if (!Number.isFinite(date.getTime())) return '';
  const now = new Date();
  const datePart = date.getFullYear() === now.getFullYear()
    ? `${pad2(date.getMonth() + 1)}.${pad2(date.getDate())}`
    : `${date.getFullYear()}.${pad2(date.getMonth() + 1)}.${pad2(date.getDate())}`;
  return `${datePart} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

/** 목록 미리보기용 한 줄 요약. */
function preview(text, max = 70) {
  const line = String(text || '').replace(/\s+/g, ' ').trim();
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

const TAB_CAPTION = {
  inbox: '받은 메일',
  sent: '보낸 메일',
  notices: '공지사항',
};

export class MailPanel {
  constructor({ sfx, toast, account, onUnreadChange } = {}) {
    this.sfx = sfx;
    this.toast = toast || (() => {});
    this.account = account || null;
    this.onUnreadChange = onUnreadChange || (() => {});
    this.user = null;
    this.apiReady = false;
    this.summary = null;
    this.tab = 'inbox';
    this.mails = { inbox: [], sent: [] };
    this.notices = [];
    this.current = null;
    this.busy = false;
    this.deleting = false;
    this.loadingTab = null;
    this.closeTimer = null;
    this.armed = null;
    this.summaryTimer = null;
    this.seenAt = this.readSeenAt();
    this.el = {};
  }

  async init() {
    const ids = [
      'btn-mail', 'mail-badge', 'ov-mail', 'btn-mail-close', 'mail-tabs',
      'mail-tab-dot-inbox', 'mail-tab-dot-notices',
      'mail-body', 'mail-view-list', 'mail-toolbar', 'mail-caption', 'mail-status',
      'mail-list', 'mail-empty', 'mail-empty-title', 'mail-empty-desc', 'mail-login-btn',
      'mail-compose-btn', 'mail-notice-new',
      'mail-view-detail', 'mail-detail-back', 'mail-detail-subject', 'mail-detail-meta',
      'mail-detail-body', 'mail-reply-btn', 'mail-delete-btn',
      'mail-view-compose', 'mail-compose-back', 'mail-compose-title', 'mail-compose-form',
      'mail-to', 'mail-subject', 'mail-content', 'mail-compose-error', 'mail-compose-submit',
      'mail-view-notice', 'mail-notice-back', 'mail-notice-form',
      'mail-notice-title', 'mail-notice-body', 'mail-notice-error', 'mail-notice-submit',
    ];
    for (const id of ids) this.el[id] = $(id);
    if (!this.el['btn-mail']) return;
    this.bind();
    await this.refreshSummary();
    this.summaryTimer = setInterval(() => {
      if (document.visibilityState === 'visible' && !this.isOpen()) void this.refreshSummary();
    }, SUMMARY_REFRESH_MS);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && !this.isOpen()) void this.refreshSummary();
    });
  }

  /* ── 서버 ─────────────────────────────────────────────── */

  async api(path, { method = 'GET', body } = {}) {
    const init = {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: body ? { 'content-type': 'application/json', accept: 'application/json' }
        : { accept: 'application/json' },
    };
    if (body) init.body = JSON.stringify(body);
    const res = await fetch(path, init);
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    // 세션이 만료됐거나 다른 탭에서 로그아웃됐다 — 화면을 바로 게스트로 정리한다.
    if (res.status === 401) this.handleAuthLost();
    return { ok: res.ok && Boolean(data && data.ok !== false), status: res.status, data };
  }

  /**
   * 401 을 받았을 때: 꼬인 로그인 상태를 남기지 않고 게스트로 돌리고 한 번만 알린다.
   * (예전에는 메일만 빈 목록이 되고 상단 계정 아이콘은 로그인 상태로 남아 있었다.)
   */
  handleAuthLost() {
    if (!this.user) return;
    this.setUser(null);
    this.toast('로그인이 풀렸어요. 다시 로그인하면 메일을 이어서 볼 수 있어요.');
    this.account?.refreshUser?.({ force: true });
  }

  errorText(data) {
    return ERROR_TEXT[data?.error] || data?.message || ERROR_TEXT.default;
  }

  /** 로그인 상태가 바뀌면 계정 창이 알려 준다. */
  setUser(user) {
    const wasSignedIn = Boolean(this.user);
    this.user = user || null;
    if (!this.user) {
      this.mails = { inbox: [], sent: [] };
      if (this.tab !== 'notices') this.tab = 'notices';
      if (this.isOpen()) this.showList('notices');
      else this.renderEmptyForTab();
      this.updateNoticeNewButton(false);
    } else if (!wasSignedIn) {
      this.el['mail-list'].replaceChildren();
      if (this.isOpen()) this.reloadTab();
    }
    void this.refreshSummary();
  }

  /**
   * 서버 요약의 로그인 상태를 화면 쪽 사용자와 맞춘다.
   * 로그인이 풀린 것을 요약(60초 주기)이 먼저 알아챈 경우에도 계정 아이콘까지 게스트로 정리한다.
   */
  syncUser(data) {
    const signedIn = Boolean(data.signedIn);
    if (signedIn && !this.user) {
      this.user = { username: data.username || '' };
      if (this.isOpen()) this.reloadTab();
    } else if (!signedIn && this.user) {
      this.handleAuthLost();
    }
  }

  async refreshSummary() {
    try {
      const res = await this.api('/api/mail/summary');
      if (!res.ok || !res.data) throw new Error('summary');
      this.apiReady = true;
      if (this.el['btn-mail']) this.el['btn-mail'].hidden = false;
      this.applySummary(res.data);
    } catch {
      // 메일 API 가 없는 곳(예전 Render 주소)에서는 버튼만 조용히 숨긴다.
      if (!this.apiReady && this.el['btn-mail']) this.el['btn-mail'].hidden = true;
    }
  }

  applySummary(data) {
    this.summary = data;
    this.syncUser(data);
    const signedIn = Boolean(data.signedIn);
    const unreadMail = Number(data.unreadMailCount || 0);
    const unreadNotice = signedIn
      ? Number(data.unreadNoticeCount || 0)
      : (Number(data.latestNoticeAt || 0) > this.seenAt ? 1 : 0);

    // 상단 메인 버튼의 빨간 동그라미
    const badge = this.el['mail-badge'];
    const total = unreadMail + unreadNotice;
    const show = total > 0;
    if (badge) {
      badge.hidden = !show;
      badge.textContent = '';
    }
    const btn = this.el['btn-mail'];
    if (btn) {
      const label = show
        ? `메일함 · 새 메일 ${unreadMail}통, 새 공지 ${unreadNotice}건`
        : '메일함';
      btn.setAttribute('aria-label', label);
      btn.setAttribute('title', show ? '메일함 · 새 소식이 있어요' : '메일함');
      btn.classList.toggle('has-unread', show);
    }
    const inboxDot = this.el['mail-tab-dot-inbox'];
    const noticeDot = this.el['mail-tab-dot-notices'];
    if (inboxDot) inboxDot.hidden = unreadMail === 0;
    if (noticeDot) noticeDot.hidden = unreadNotice === 0;

    // 공지 작성은 공지 탭에서만 보인다(다른 탭에서 요약이 갱신돼도 다시 뜨지 않게).
    this.updateNoticeNewButton(Boolean(signedIn && data.isAdmin) && this.tab === 'notices');
    this.onUnreadChange(total);
    if (this.isOpen() && this.tab === 'inbox') this.syncComposeAvailability();
  }

  /* ── 열고 닫기 ─────────────────────────────────────────── */

  isOpen() {
    return Boolean(this.el['ov-mail'] && !this.el['ov-mail'].hidden);
  }

  open() {
    if (!this.el['ov-mail']) return;
    clearTimeout(this.closeTimer);
    const ov = this.el['ov-mail'];
    ov.hidden = false;
    ov.classList.remove('ov-out');
    this.el['btn-mail'].setAttribute('aria-expanded', 'true');
    this.sfx?.play('tap');
    const preferred = this.user ? 'inbox' : 'notices';
    this.showList(preferred);
    void this.refreshSummary();
    setTimeout(() => this.el['btn-mail-close']?.focus({ preventScroll: true }), 60);
  }

  close(instant = false, { restoreFocus = false } = {}) {
    const ov = this.el['ov-mail'];
    if (!ov || ov.hidden) return;
    this.el['btn-mail']?.setAttribute('aria-expanded', 'false');
    clearTimeout(this.closeTimer);
    this.cancelArmed();
    this.showView('list');
    // 포커스가 사라진 채로 남으면 다음 Enter 가 뒤의 `대전 시작` 을 누를 수 있다 — 버튼으로 돌려준다.
    if (restoreFocus) this.el['btn-mail']?.focus({ preventScroll: true });
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (instant || reduce) {
      ov.hidden = true;
      ov.classList.remove('ov-out');
      return;
    }
    ov.classList.add('ov-out');
    this.closeTimer = setTimeout(() => {
      ov.hidden = true;
      ov.classList.remove('ov-out');
    }, 150);
  }

  closeAll(instant = false) {
    this.close(instant);
  }

  /* ── 탭 · 화면 전환 ───────────────────────────────────── */

  showList(tab = this.tab) {
    this.tab = TAB_CAPTION[tab] ? tab : 'inbox';
    this.el['mail-tabs'].querySelectorAll('[data-mail-tab]').forEach((btn) => {
      btn.setAttribute('aria-selected', String(btn.dataset.mailTab === this.tab));
    });
    this.el['mail-caption'].textContent = TAB_CAPTION[this.tab];
    // 창을 오갈 때 남은 오류 문구·입력값·스크롤이 따라오지 않게 한다.
    this.clearComposeError();
    this.showNoticeError('');
    this.setStatus('');
    this.showView('list');
    this.syncComposeAvailability();
    this.reloadTab();
  }

  showView(name) {
    for (const [key, id] of Object.entries({
      list: 'mail-view-list',
      detail: 'mail-view-detail',
      compose: 'mail-view-compose',
      notice: 'mail-view-notice',
    })) {
      const node = this.el[id];
      if (node) node.hidden = key !== name;
    }
    const body = this.el['mail-body'];
    if (body) body.scrollTop = 0;
    this.cancelArmed();
  }

  /** 받은·보낸 메일은 로그인해야 쓸 수 있다 — 쓰기 버튼을 감춘다. */
  syncComposeAvailability() {
    const signedIn = Boolean(this.user);
    const compose = this.el['mail-compose-btn'];
    if (compose) {
      compose.hidden = !signedIn || this.tab === 'notices';
    }
    this.updateNoticeNewButton(Boolean(signedIn && this.summary?.isAdmin) && this.tab === 'notices');
  }

  updateNoticeNewButton(show) {
    const btn = this.el['mail-notice-new'];
    if (btn) btn.hidden = !show;
  }

  async reloadTab() {
    if (this.tab === 'inbox') return this.loadMails('inbox');
    if (this.tab === 'sent') return this.loadMails('sent');
    return this.loadNotices();
  }

  setStatus(text) {
    const node = this.el['mail-status'];
    if (!node) return;
    node.hidden = !text;
    node.textContent = text || '';
  }

  /* ── 목록 ─────────────────────────────────────────────── */

  async loadMails(kind) {
    const token = `${kind}:${Date.now()}`;
    this.loadingTab = token;
    if (!this.user) {
      this.mails[kind] = [];
      this.renderList([], kind);
      this.setStatus('');
      return;
    }
    this.setStatus('불러오는 중…');
    try {
      const res = await this.api(`/api/mail/${kind}`);
      if (this.loadingTab !== token || this.tab !== kind) return;
      if (!res.ok) {
        if (res.status === 401) {
          this.setUser(null);
          this.renderList([], kind);
          return;
        }
        this.setStatus(this.errorText(res.data));
        this.renderList([], kind);
        return;
      }
      this.mails[kind] = Array.isArray(res.data.mails) ? res.data.mails : [];
      this.setStatus('');
      this.renderList(this.mails[kind], kind);
    } catch {
      if (this.loadingTab !== token) return;
      this.setStatus(ERROR_TEXT.network);
      this.renderList([], kind);
    }
  }

  async loadNotices() {
    const token = `notices:${Date.now()}`;
    this.loadingTab = token;
    this.setStatus('불러오는 중…');
    try {
      const res = await this.api('/api/mail/notices');
      if (this.loadingTab !== token || this.tab !== 'notices') return;
      if (!res.ok) {
        this.setStatus(this.errorText(res.data));
        this.renderList([], 'notices');
        return;
      }
      this.notices = Array.isArray(res.data.notices) ? res.data.notices : [];
      this.setStatus('');
      this.renderList(this.notices, 'notices');
      this.updateNoticeNewButton(Boolean(this.user && res.data.isAdmin));
      // 공지 목록을 연 순간이면 다 읽은 것으로 본다(서버는 사용자별, 게스트는 이 기기 기준).
      if (this.notices.length) {
        this.markNoticesRead();
        if (!this.user) {
          const latest = Math.max(...this.notices.map((n) => Number(n.createdAt) || 0));
          this.writeSeenAt(Math.max(latest, Number(res.data.latestNoticeAt) || 0));
        }
      }
    } catch {
      if (this.loadingTab !== token) return;
      this.setStatus(ERROR_TEXT.network);
      this.renderList([], 'notices');
    }
  }

  renderEmptyForTab() {
    this.renderList([], this.tab);
  }

  renderList(items, kind) {
    const list = this.el['mail-list'];
    const empty = this.el['mail-empty'];
    list.replaceChildren();
    const signedIn = Boolean(this.user);
    const unit = kind === 'notices' ? '건' : '통';
    this.el['mail-caption'].textContent = `${TAB_CAPTION[kind] || ''} · ${items.length}${unit}`;

    if (!items.length) {
      empty.hidden = false;
      const loginBtn = this.el['mail-login-btn'];
      if (!signedIn && kind !== 'notices') {
        this.el['mail-empty-title'].textContent = '로그인하면 메일을 주고받을 수 있어요';
        this.el['mail-empty-desc'].textContent = '아이디와 비밀번호만 있으면 바로 시작할 수 있어요.';
        loginBtn.hidden = false;
      } else if (kind === 'inbox') {
        this.el['mail-empty-title'].textContent = '아직 받은 메일이 없어요';
        this.el['mail-empty-desc'].textContent = '다른 플레이어가 보낸 메일이 여기에 도착해요.';
        loginBtn.hidden = true;
      } else if (kind === 'sent') {
        this.el['mail-empty-title'].textContent = '보낸 메일이 없어요';
        this.el['mail-empty-desc'].textContent = '새 메일 쓰기로 다른 플레이어에게 첫 메일을 보내 보세요.';
        loginBtn.hidden = true;
      } else {
        this.el['mail-empty-title'].textContent = '아직 공지사항이 없어요';
        this.el['mail-empty-desc'].textContent = '잇다의 새 소식이 올라오면 여기에서 알려 드릴게요.';
        loginBtn.hidden = true;
      }
      return;
    }

    empty.hidden = true;
    for (const item of items) {
      list.appendChild(kind === 'notices' ? this.noticeItem(item) : this.mailItem(item, kind));
    }
  }

  mailItem(mail, kind) {
    const item = el('li', 'mail-item');
    if (kind === 'inbox' && !mail.isRead) item.classList.add('unread');

    const open = el('button', 'mail-open');
    open.type = 'button';
    open.dataset.id = mail.id;

    const top = el('div', 'mail-top');
    if (kind === 'inbox' && !mail.isRead) top.appendChild(el('i', 'mail-dot'));
    top.appendChild(el('b', 'mail-who', kind === 'inbox' ? `@${mail.senderUsername}` : `@${mail.recipientUsername}`));
    top.appendChild(el('span', 'mail-when', formatWhen(mail.createdAt)));

    const subject = el('span', 'mail-subject', mail.subject);
    const previewLine = el('span', 'mail-preview', preview(mail.body));

    open.append(top, subject, previewLine);
    if (kind === 'sent') {
      open.appendChild(el('span', 'mail-flag' + (mail.isRead ? ' read' : ''), mail.isRead ? '읽음' : '아직 안 읽음'));
    }
    open.addEventListener('click', () => this.openMail(mail, kind));
    item.appendChild(open);
    return item;
  }

  noticeItem(notice) {
    const item = el('li', 'mail-item notice-item');
    if (notice.isRead === false) item.classList.add('unread');

    const open = el('button', 'mail-open');
    open.type = 'button';
    open.dataset.id = notice.id;
    const top = el('div', 'mail-top');
    if (notice.isRead === false) top.appendChild(el('i', 'mail-dot'));
    top.appendChild(el('b', 'mail-subject', notice.title));
    top.appendChild(el('span', 'mail-when', formatWhen(notice.createdAt)));
    open.append(top, el('span', 'mail-preview', preview(notice.body, 90)));
    open.addEventListener('click', () => this.openNotice(notice));
    item.appendChild(open);

    if (this.user && this.summary?.isAdmin) {
      const tools = el('div', 'mail-item-tools');
      const del = el('button', 'mail-item-del', '삭제');
      del.type = 'button';
      del.addEventListener('click', () => this.armAction(del, '정말 삭제?', () => this.deleteNotice(notice)));
      tools.appendChild(del);
      item.appendChild(tools);
    }
    return item;
  }

  /* ── 상세 ─────────────────────────────────────────────── */

  openMail(mail, kind) {
    this.current = { kind, mail };
    this.el['mail-detail-subject'].textContent = mail.subject;
    const who = kind === 'inbox'
      ? `보낸 사람 @${mail.senderUsername}`
      : `받는 사람 @${mail.recipientUsername}`;
    const extra = kind === 'sent' ? (mail.isRead ? ' · 읽음' : ' · 아직 안 읽음') : '';
    this.el['mail-detail-meta'].textContent = `${who} · ${formatWhen(mail.createdAt)}${extra}`;
    this.el['mail-detail-body'].textContent = mail.body;
    this.el['mail-reply-btn'].hidden = kind !== 'inbox';
    this.el['mail-delete-btn'].hidden = false;
    this.el['mail-delete-btn'].textContent = '삭제';
    this.showView('detail');
    this.el['mail-detail-back']?.focus({ preventScroll: true });
    this.sfx?.play('tap');

    if (kind === 'inbox' && !mail.isRead) {
      mail.isRead = true;
      void this.markMailRead(mail.id);
      const row = this.el['mail-list'].querySelector(`[data-id="${mail.id}"]`);
      if (row) {
        row.closest('.mail-item')?.classList.remove('unread');
        row.querySelector('.mail-dot')?.remove();
      }
    }
  }

  openNotice(notice) {
    this.current = { kind: 'notices', mail: notice };
    this.el['mail-detail-subject'].textContent = notice.title;
    this.el['mail-detail-meta'].textContent = `공지 · ${notice.authorUsername} · ${formatWhen(notice.createdAt)}`;
    this.el['mail-detail-body'].textContent = notice.body;
    this.el['mail-reply-btn'].hidden = true;
    this.el['mail-delete-btn'].hidden = !(this.user && this.summary?.isAdmin);
    this.el['mail-delete-btn'].textContent = '삭제';
    this.showView('detail');
    this.el['mail-detail-back']?.focus({ preventScroll: true });
    this.sfx?.play('tap');
  }

  async markMailRead(id) {
    try {
      const res = await this.api('/api/mail/read', { method: 'POST', body: { id } });
      if (res.ok && res.data) {
        const list = this.mails.inbox.map((item) => (item.id === id ? { ...item, isRead: true } : item));
        this.mails.inbox = list;
        if (this.summary) {
          this.summary.unreadMailCount = Number(res.data.unreadMailCount || 0);
          this.applySummary(this.summary);
        }
      }
    } catch {
      /* 읽음 기록은 다음에 목록을 열 때 다시 시도된다 */
    }
  }

  async markNoticesRead() {
    if (!this.user) return;
    try {
      const res = await this.api('/api/mail/notices/read', { method: 'POST', body: { all: true } });
      if (res.ok && this.summary) {
        this.summary.unreadNoticeCount = Number(res.data?.unreadNoticeCount || 0);
        this.applySummary(this.summary);
      }
      this.notices = this.notices.map((n) => ({ ...n, isRead: true }));
      this.el['mail-list'].querySelectorAll('.mail-dot').forEach((dot) => dot.remove());
      this.el['mail-list'].querySelectorAll('.mail-item.unread').forEach((li) => li.classList.remove('unread'));
    } catch {
      /* 다음에 다시 */
    }
  }

  /* ── 답장 · 새 메일 쓰기 ──────────────────────────────── */

  openCompose({ to = '', subject = '', body = '', replyTo = null, label = '새 메일 쓰기' } = {}) {
    if (!this.user) return this.showLoginPrompt();
    this.composeReply = replyTo;
    this.el['mail-compose-title'].textContent = label;
    this.el['mail-to'].value = to;
    this.el['mail-subject'].value = subject;
    this.el['mail-content'].value = body;
    this.clearComposeError();
    this.el['mail-compose-submit'].textContent = replyTo ? '답장 보내기' : '보내기';
    this.showView('compose');
    if (window.matchMedia('(pointer: fine)').matches) {
      setTimeout(() => (to ? this.el['mail-subject'] : this.el['mail-to']).focus({ preventScroll: true }), 60);
    }
  }

  replyToCurrent() {
    const { kind, mail } = this.current || {};
    if (!mail || kind !== 'inbox') return;
    // 제목 상한(80자)을 넘으면 서버가 거절하므로, 답장 제목도 80자 안으로 맞춘다.
    const base = String(mail.subject || '');
    const subject = (/^re:/i.test(base) ? base : `Re: ${base}`).slice(0, 80);
    this.openCompose({
      to: mail.senderUsername,
      subject,
      body: '',
      replyTo: mail.id,
      label: `@${mail.senderUsername}님에게 답장`,
    });
  }

  showLoginPrompt() {
    this.tab = 'inbox';
    this.showList('inbox');
  }

  showComposeError(message) {
    const box = this.el['mail-compose-error'];
    if (!box) return;
    box.hidden = !message;
    box.textContent = message || '';
  }

  clearComposeError() {
    this.showComposeError('');
  }

  async submitCompose(event) {
    event.preventDefault();
    if (this.busy) return;
    if (!this.user) return this.showLoginPrompt();

    const to = this.el['mail-to'].value.trim();
    const subject = this.el['mail-subject'].value.trim();
    const content = this.el['mail-content'].value.trim();
    if (!to) return this.showComposeError(ERROR_TEXT.recipient_required);
    if (!subject) return this.showComposeError(ERROR_TEXT.subject_required);
    if (!content) return this.showComposeError(ERROR_TEXT.body_required);

    this.busy = true;
    const btn = this.el['mail-compose-submit'];
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = '보내는 중…';
    this.clearComposeError();
    try {
      const res = await this.api('/api/mail/send', {
        method: 'POST',
        body: { to, subject, body: content, replyToId: this.composeReply || null },
      });
      if (!res.ok) {
        this.showComposeError(this.errorText(res.data));
        return;
      }
      const sentTo = res.data?.mail?.recipientUsername || to.replace(/^@/, '');
      this.toast(`@${sentTo}님에게 메일을 보냈어요.`);
      this.el['mail-compose-form'].reset();
      this.composeReply = null;
      this.tab = 'sent';
      this.showList('sent');
      void this.refreshSummary();
    } catch {
      this.showComposeError(ERROR_TEXT.network);
    } finally {
      this.busy = false;
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  /* ── 삭제(두 번 눌러 확인) ────────────────────────────── */

  cancelArmed() {
    if (!this.armed) return;
    clearTimeout(this.armed.timer);
    if (this.armed.node && this.armed.node.isConnected) this.armed.node.textContent = this.armed.label;
    this.armed = null;
  }

  armAction(node, armedLabel, run) {
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

  async deleteCurrent() {
    const { kind, mail } = this.current || {};
    if (!mail) return;
    if (kind === 'notices') return this.deleteNotice(mail);
    if (this.deleting) return;   // 연타·더블 클릭 차단(응답이 올 때까지 한 번만)
    this.deleting = true;
    const btn = this.el['mail-delete-btn'];
    if (btn) btn.disabled = true;
    try {
      const res = await this.api('/api/mail/delete', { method: 'POST', body: { id: mail.id } });
      if (!res.ok) {
        this.toast(this.errorText(res.data));
        return;
      }
      this.toast('메일을 지웠어요.');
      this.mails[kind] = this.mails[kind].filter((item) => item.id !== mail.id);
      this.current = null;
      this.showList(kind);
      void this.refreshSummary();
    } catch {
      this.toast(ERROR_TEXT.network);
    } finally {
      this.deleting = false;
      if (btn) btn.disabled = false;
    }
  }

  async deleteNotice(notice) {
    if (this.deleting) return;
    this.deleting = true;
    try {
      const res = await this.api('/api/mail/notices', { method: 'DELETE', body: { id: notice.id } });
      if (!res.ok) {
        this.toast(this.errorText(res.data));
        return;
      }
      this.toast('공지를 지웠어요.');
      this.notices = this.notices.filter((item) => item.id !== notice.id);
      this.current = null;
      this.showList('notices');
      void this.refreshSummary();
    } catch {
      this.toast(ERROR_TEXT.network);
    } finally {
      this.deleting = false;
    }
  }

  /* ── 공지 작성(관리자) ────────────────────────────────── */

  openNoticeForm() {
    if (!this.user || !this.summary?.isAdmin) return;
    this.el['mail-notice-form'].reset();
    this.showNoticeError('');
    this.showView('notice');
    this.sfx?.play('tap');
    if (window.matchMedia('(pointer: fine)').matches) {
      setTimeout(() => this.el['mail-notice-title'].focus({ preventScroll: true }), 60);
    }
  }

  showNoticeError(message) {
    const box = this.el['mail-notice-error'];
    if (!box) return;
    box.hidden = !message;
    box.textContent = message || '';
  }

  async submitNotice(event) {
    event.preventDefault();
    if (this.busy) return;
    const title = this.el['mail-notice-title'].value.trim();
    const body = this.el['mail-notice-body'].value.trim();
    if (!title) return this.showNoticeError(ERROR_TEXT.title_required);
    if (!body) return this.showNoticeError(ERROR_TEXT.body_required);

    this.busy = true;
    const btn = this.el['mail-notice-submit'];
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = '올리는 중…';
    this.showNoticeError('');
    try {
      const res = await this.api('/api/mail/notices', { method: 'POST', body: { title, body } });
      if (!res.ok) {
        this.showNoticeError(this.errorText(res.data));
        return;
      }
      this.toast('공지사항을 올렸어요.');
      this.el['mail-notice-form'].reset();
      this.showList('notices');
      void this.refreshSummary();
    } catch {
      this.showNoticeError(ERROR_TEXT.network);
    } finally {
      this.busy = false;
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  /* ── 게스트의 공지 확인 시각 ──────────────────────────── */

  readSeenAt() {
    try {
      const value = Number(localStorage.getItem(NOTICE_SEEN_KEY) || 0);
      return Number.isFinite(value) ? value : 0;
    } catch {
      return 0;
    }
  }

  writeSeenAt(value) {
    const at = Number(value) || 0;
    if (at <= this.seenAt) return;
    this.seenAt = at;
    try { localStorage.setItem(NOTICE_SEEN_KEY, String(at)); } catch { /* 저장 못 해도 이번 화면은 된다 */ }
    if (this.summary) this.applySummary(this.summary);
  }

  /* ── 이벤트 ───────────────────────────────────────────── */

  bind() {
    this.el['btn-mail'].addEventListener('click', () => {
      if (this.isOpen()) this.close();
      else this.open();
    });
    this.el['btn-mail-close'].addEventListener('click', () => {
      this.close(false, { restoreFocus: true });
      this.sfx?.play('tap');
    });
    this.el['ov-mail'].addEventListener('click', (event) => {
      if (event.target === this.el['ov-mail']) this.close(false, { restoreFocus: true });
    });
    this.el['mail-tabs'].addEventListener('click', (event) => {
      const tab = event.target.closest('[data-mail-tab]');
      if (!tab || tab.dataset.mailTab === this.tab) return;
      this.sfx?.play('tap');
      this.showList(tab.dataset.mailTab);
    });
    this.el['mail-compose-btn'].addEventListener('click', () => {
      if (!this.user) return this.showList('inbox');
      this.openCompose();
    });
    this.el['mail-login-btn'].addEventListener('click', () => {
      this.close(true);
      this.account?.openAuth?.('login');
    });
    this.el['mail-detail-back'].addEventListener('click', () => {
      this.showList(this.current?.kind === 'notices' ? 'notices' : this.tab);
      this.sfx?.play('tap');
    });
    this.el['mail-reply-btn'].addEventListener('click', () => this.replyToCurrent());
    this.el['mail-delete-btn'].addEventListener('click', () => {
      const btn = this.el['mail-delete-btn'];
      this.armAction(btn, '정말 삭제?', () => this.deleteCurrent());
    });
    this.el['mail-compose-back'].addEventListener('click', () => {
      this.showList(this.current?.kind || this.tab);
      this.sfx?.play('tap');
    });
    this.el['mail-compose-form'].addEventListener('submit', (event) => this.submitCompose(event));
    this.el['mail-notice-new'].addEventListener('click', () => this.openNoticeForm());
    this.el['mail-notice-back'].addEventListener('click', () => {
      this.showList('notices');
      this.sfx?.play('tap');
    });
    this.el['mail-notice-form'].addEventListener('submit', (event) => this.submitNotice(event));
    for (const id of ['mail-to', 'mail-subject', 'mail-content']) {
      this.el[id].addEventListener('input', () => this.clearComposeError());
    }
    for (const id of ['mail-notice-title', 'mail-notice-body']) {
      this.el[id].addEventListener('input', () => this.showNoticeError(''));
    }
  }
}
