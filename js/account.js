/**
 * 계정 창(로그인 · 회원가입 · 내 계정).
 *
 * 서버는 Cloudflare Pages Functions(`/api/auth/*`) + D1 이다.
 *   - 아이디 + 비밀번호: 이메일 없이 바로 가입/로그인, 서버가 Turnstile 을 검사한다.
 *   - 구글 로그인: 구글 버튼 한 번으로 로그인/자동 가입.
 *   - 내 계정: 닉네임(1~16자)과 프로필 사진을 바꾸고, `친구` 탭에서 아이디로 친구를 찾는다.
 *     사진은 이 기기에서 160×160 정사각 WebP/JPEG 로 줄여 Data URL(24KB 이하)로 보낸다 —
 *     R2·이미지 카드 없이 D1 만으로 동작하는 길이다.
 * 로그인하지 않아도 게임은 지금처럼 그대로 즐길 수 있고, 계정 API 가 없는 곳
 * (예전 Render 주소)에서는 우측 상단 계정 버튼만 조용히 숨긴다.
 */

import { FriendsPanel } from './friends.js';

const $ = (id) => document.getElementById(id);

const TURNSTILE_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
const GIS_SRC = 'https://accounts.google.com/gsi/client';

const ERROR_TEXT = {
  username_required: '아이디를 입력해 주세요.',
  username_invalid: '아이디는 2~12자의 한글·영문·숫자·밑줄만 쓸 수 있어요.',
  username_reserved: '쓸 수 없는 아이디예요. 다른 아이디를 정해 주세요.',
  username_taken: '이미 쓰고 있는 아이디예요.',
  password_required: '비밀번호를 입력해 주세요.',
  password_short: '비밀번호는 6자 이상으로 정해 주세요.',
  password_long: '비밀번호는 72자까지 쓸 수 있어요.',
  password_mismatch: '비밀번호 확인이 서로 달라요.',
  invalid_credentials: '아이디 또는 비밀번호가 맞지 않아요.',
  use_google: '구글 로그인으로 만든 계정이에요. 아래 구글 로그인을 써 주세요.',
  turnstile_failed: '봇 확인에 실패했어요. 확인을 마친 뒤 다시 시도해 주세요.',
  turnstile_missing: '아래 봇 확인을 먼저 마쳐 주세요.',
  rate_limited: '시도가 너무 많아요. 잠시 후 다시 시도해 주세요.',
  google_failed: '구글 로그인을 확인하지 못했어요. 다시 시도해 주세요.',
  not_signed_in: '로그인한 상태에서만 계정을 지울 수 있어요.',
  password_mismatch: '비밀번호가 맞지 않아요. 다시 확인해 주세요.',
  confirm_required: '확인 문구를 입력해 주세요.',
  confirm_mismatch: '확인 문구가 맞지 않아요. 입력한 문구를 다시 확인해 주세요.',
  google_disabled: '구글 로그인은 준비 중이에요.',
  not_configured: '계정 서버가 아직 준비되지 않았어요.',
  nickname_required: '닉네임을 입력해 주세요.',
  nickname_long: '닉네임은 16자까지 쓸 수 있어요.',
  nickname_invalid: '닉네임에 쓸 수 없는 글자가 있어요.',
  avatar_invalid: 'PNG·JPEG·WebP 사진만 쓸 수 있어요.',
  avatar_too_large: '사진이 너무 커요. 더 작은 사진으로 다시 골라 주세요.',
  avatar_conflict: '사진을 지울지 바꿀지 하나만 골라 주세요.',
  nothing_to_change: '바꾼 내용이 없어요.',
  network: '연결이 잠시 불안정해요. 잠시 후 다시 시도해 주세요.',
  default: '잠시 문제가 생겼어요. 다시 시도해 주세요.',
};

/** 프로필 사진: 화면에서 160×160 정사각으로 줄여 Data URL 24KB 이하로 만든다. */
const AVATAR_SIZE = 160;
const AVATAR_MAX_CHARS = 24 * 1024;
const AVATAR_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);

export function avatarSrc(user) {
  if (!user?.id || !Number(user.avatarAt)) return '';
  return `/api/account/avatar?u=${encodeURIComponent(user.id)}&v=${Number(user.avatarAt)}`;
}

/** 파일 → 화면·서버가 함께 쓰는 사진 모양(작은 Data URL). */
async function fileToAvatar(file) {
  const type = String(file?.type || '').toLowerCase();
  if (!AVATAR_TYPES.has(type)) throw Object.assign(new Error('avatar_invalid'), { code: 'avatar_invalid' });
  if (Number(file.size || 0) > 8 * 1024 * 1024) {
    throw Object.assign(new Error('avatar_too_large'), { code: 'avatar_too_large' });
  }

  let bitmap;
  try {
    if (window.createImageBitmap) {
      try {
        bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
      } catch {
        bitmap = await createImageBitmap(file);
      }
    }
  } catch {
    bitmap = null;
  }
  if (!bitmap) {
    bitmap = await new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('avatar_invalid')); };
      img.src = url;
    });
  }

  // 가운데를 정사각으로 잘라 16×16 미리 줄인 뒤 160/128/96px 순서로 다시 그린다.
  const width = bitmap.width || bitmap.naturalWidth || 0;
  const height = bitmap.height || bitmap.naturalHeight || 0;
  if (!width || !height) throw Object.assign(new Error('avatar_invalid'), { code: 'avatar_invalid' });
  const side = Math.min(width, height);
  const sx = Math.round((width - side) / 2);
  const sy = Math.round((height - side) / 2);

  const qualities = [0.84, 0.76, 0.68, 0.6, 0.52, 0.44];
  for (const size of [AVATAR_SIZE, 128, 96]) {
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx) break;
    ctx.fillStyle = '#FFFDF8';
    ctx.fillRect(0, 0, size, size);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bitmap, sx, sy, side, side, 0, 0, size, size);
    for (const quality of qualities) {
      const webp = canvas.toDataURL('image/webp', quality);
      if (webp.startsWith('data:image/webp') && webp.length <= AVATAR_MAX_CHARS) {
        if (bitmap.close) bitmap.close();
        return webp;
      }
    }
    // WebP 인코딩이 없는 브라우저는 JPEG 로
    for (const quality of qualities) {
      const jpeg = canvas.toDataURL('image/jpeg', quality);
      if (jpeg.length <= AVATAR_MAX_CHARS) {
        if (bitmap.close) bitmap.close();
        return jpeg;
      }
    }
  }
  if (bitmap.close) bitmap.close();
  throw Object.assign(new Error('avatar_too_large'), { code: 'avatar_too_large' });
}

/** 같은 주소의 스크립트를 한 번만 불러온다. */
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const existing = [...document.scripts].find((s) => s.src === src);
    if (existing) {
      if (existing.dataset.loaded === '1') resolve();
      else {
        existing.addEventListener('load', () => resolve(), { once: true });
        existing.addEventListener('error', () => reject(new Error('script')), { once: true });
      }
      return;
    }
    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.defer = true;
    script.addEventListener('load', () => { script.dataset.loaded = '1'; resolve(); }, { once: true });
    script.addEventListener('error', () => reject(new Error('script')), { once: true });
    document.head.appendChild(script);
  });
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** 로그인 상태가 바뀌었다는 신호(다른 탭과 맞추는 용도). */
const AUTH_PING_KEY = 'itda.auth.ping';

/** 로그인·로그아웃·탈퇴 뒤 다른 탭에 알린다. */
function pingAuth() {
  try { localStorage.setItem(AUTH_PING_KEY, String(Date.now())); } catch { /* 저장 못 해도 이 탭은 된다 */ }
}

export class AccountPanel {
  constructor({ sfx, toast, onUserChange, onComposeMail } = {}) {
    this.sfx = sfx;
    this.toast = toast || (() => {});
    /** 로그인 상태가 바뀌면 다른 창(메일함 등)에 알린다. */
    this.onUserChange = onUserChange || (() => {});
    /** 친구 목록의 `메일` → 메일함 새 메일 쓰기(@아이디 채움). */
    this.onComposeMail = onComposeMail || (() => {});
    this.user = null;
    this.config = null;
    this.apiReady = false;
    this.mode = 'login';
    this.token = null;
    this.busy = false;
    this.turnstileId = null;
    this.turnstileLoad = null;
    this.googleReady = false;
    this.deleteBusy = false;
    this.closeTimers = { auth: null, account: null };
    /** 같은 탭에서 너무 자주 /api/auth/me 를 부르지 않게(창을 오갈 때마다 부르면 빨라진다). */
    this.lastRefresh = 0;
    /** 열려 있는 탭(내 계정 · 친구) */
    this.accountTab = 'profile';
    /** 프로필 편집 중 미리 보는 사진(Data URL) · 지우기 표시 */
    this.avatarDraft = '';
    this.avatarRemoved = false;
    this.profileBusy = false;
    /** 친구 목록·받은 요청(별도 모듈이 이 시트의 친구 탭을 그린다) */
    this.friends = null;
    this.friendCounts = { friends: 0, incoming: 0, outgoing: 0 };
    this.el = {};
  }

  async init() {
    const ids = [
      'btn-account', 'account-badge',
      'ov-auth', 'btn-auth-close', 'auth-title', 'auth-tabs', 'auth-form',
      'auth-username', 'auth-password', 'auth-password2', 'auth-password2-field',
      'auth-turnstile', 'auth-hint', 'auth-error', 'auth-submit', 'auth-submit-label',
      'auth-or', 'auth-google-slot', 'auth-google-note',
      'ov-account', 'btn-account-close', 'account-title', 'account-avatar', 'account-avatar-letter', 'account-avatar-img',
      'account-name', 'account-handle',
      'account-provider', 'account-joined', 'btn-logout',
      'account-main', 'account-delete-view', 'btn-delete-account', 'btn-delete-confirm',
      'btn-delete-cancel', 'account-delete-confirm', 'account-delete-label',
      'account-delete-hint', 'account-delete-target', 'account-delete-error',
      'account-tabs', 'account-view-profile', 'account-view-friends',
      'account-tab-dot', 'account-friend-dot', 'account-friend-count', 'btn-friends-open',
      'friend-dot-incoming',
      'btn-profile-edit', 'profile-edit', 'profile-nickname', 'profile-hint', 'profile-error',
      'btn-profile-save', 'btn-profile-cancel', 'btn-avatar-pick', 'btn-avatar-remove',
      'avatar-file', 'profile-photo', 'profile-photo-letter', 'profile-photo-img',
    ];
    for (const id of ids) this.el[id] = $(id);
    // 친구 탭(아이디 검색 · 받은 요청 · 친구 · 보낸 요청)은 friends.js 가 맡는다.
    this.friends = new FriendsPanel({
      sfx: this.sfx,
      toast: this.toast,
      account: this,
      onComposeMail: (to) => this.onComposeMail(to),
      onCounts: (counts) => this.setFriendBadge(counts),
    });
    this.friends.init();
    this.bind();
    this.watchAuth();
    await this.loadServer();
    this.watchFriends();
  }

  /**
   * 받은 친구 요청 빨간 점은 60초에 한 번만 확인한다(메일함 요약과 같은 방식).
   * 창을 보고 있을 때는 친구 목록이 직접 새로 고치므로 띄지 않는다.
   */
  watchFriends() {
    const tick = () => {
      if (document.visibilityState === 'visible' && !this.isOpen()) void this.friends?.refreshSummary();
    };
    setInterval(tick, 60 * 1000);
    document.addEventListener('visibilitychange', tick);
  }

  /**
   * 다른 탭에서 로그인·로그아웃했거나 이 탭이 다시 앞으로 나오면 세션을 다시 확인한다.
   * (한 탭에서 로그아웃했는데 다른 탭은 로그인 상태로 남아 401 만 받던 문제를 없엔다.)
   */
  watchAuth() {
    window.addEventListener('storage', (event) => {
      if (event.key === AUTH_PING_KEY) void this.refreshUser({ force: true });
    });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void this.refreshUser();
    });
  }

  /* ── 서버 상태 ─────────────────────────────────────────── */

  async loadServer() {
    let config = null;
    try {
      const res = await fetch('/api/auth/config', {
        headers: { accept: 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!res.ok) throw new Error('config');
      config = await res.json();
      if (!config || config.ok !== true) throw new Error('config');
    } catch {
      this.apiReady = false;
      if (this.el['btn-account']) this.el['btn-account'].hidden = true;
      return;
    }
    this.config = config;
    this.apiReady = true;
    if (this.el['btn-account']) this.el['btn-account'].hidden = false;
    await this.refreshUser();
  }

  async refreshUser({ force = false } = {}) {
    if (!this.apiReady) return;
    const now = Date.now();
    if (!force && now - this.lastRefresh < 8000) return;
    this.lastRefresh = now;
    try {
      const res = await fetch('/api/auth/me', {
        headers: { accept: 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (res.status === 401) {
        this.setUser(null);
        return;
      }
      const data = await res.json();
      this.setUser(data && data.user ? data.user : null);
    } catch {
      /* 잠깐 끊긴 것뿐이면 지금 화면 상태를 그대로 둔다 */
    }
  }

  setUser(user) {
    const before = this.user;
    this.user = user || null;
    if (before?.id !== this.user?.id || before?.username !== this.user?.username) {
      this.onUserChange(this.user);
    }
    this.friends?.setUser(this.user);
    this.fillAccount();
    if (this.user) void this.friends?.refreshSummary();
    else this.setFriendBadge({ friends: 0, incoming: 0, outgoing: 0 });
    const btn = this.el['btn-account'];
    if (!btn) return;
    const signedIn = Boolean(this.user);
    const name = signedIn ? (this.user.displayName || this.user.username) : '';
    // 버튼은 아이콘만 두고, 상태는 점(::after)과 aria-label·title 로 알린다.
    btn.classList.toggle('signed-in', signedIn);
    const label = signedIn ? `내 계정 · ${name}` : '로그인 · 회원가입';
    btn.setAttribute('aria-label', label);
    btn.setAttribute('title', signedIn ? `내 계정 (${name})` : '로그인');
    btn.setAttribute('aria-expanded', 'false');
  }

  /* ── 열고 닫기 ─────────────────────────────────────────── */

  toggle() {
    if (this.user) this.openAccount();
    else this.openAuth('login');
  }

  openAuth(mode = 'login') {
    if (!this.apiReady) return;
    this.setMode(mode);
    this.clearError();
    // 지난번에 치던 비밀번호가 남지 않게 비운다(아이디는 다시 칠 수 있게 남긴다).
    if (this.el['auth-password']) this.el['auth-password'].value = '';
    if (this.el['auth-password2']) this.el['auth-password2'].value = '';
    const ov = this.el['ov-auth'];
    clearTimeout(this.closeTimers.auth);
    ov.hidden = false;
    ov.classList.remove('ov-out');
    this.el['btn-account'].setAttribute('aria-expanded', 'true');
    this.startTurnstile();
    this.startGoogle();
    this.sfx?.play('tap');
    if (window.matchMedia('(pointer: fine)').matches) {
      setTimeout(() => this.el['auth-username'].focus({ preventScroll: true }), 80);
    }
  }

  closeAuth(instant = false) {
    this.fadeOut('auth', this.el['ov-auth']);
    this.el['btn-account']?.setAttribute('aria-expanded', 'false');
    this.resetTurnstile();
    if (!instant) this.el['btn-account']?.focus({ preventScroll: true });
  }

  openAccount() {
    if (!this.user) return this.openAuth('login');
    const ov = this.el['ov-account'];
    clearTimeout(this.closeTimers.account);
    this.hideDeleteConfirm();
    this.closeProfileEdit();
    this.showAccountTab('profile');
    this.fillAccount();
    ov.hidden = false;
    ov.classList.remove('ov-out');
    this.el['btn-account'].setAttribute('aria-expanded', 'true');
    this.sfx?.play('tap');
    void this.friends?.refreshSummary();
    if (window.matchMedia('(pointer: fine)').matches) {
      setTimeout(() => this.el['btn-account-close'].focus({ preventScroll: true }), 80);
    }
  }

  /** 시트 안의 두 탭(내 계정 · 친구)을 바꾼다. */
  showAccountTab(tab) {
    this.accountTab = tab === 'friends' ? 'friends' : 'profile';
    const friends = this.accountTab === 'friends';
    if (this.el['account-tabs']) {
      this.el['account-tabs'].querySelectorAll('[data-account-tab]').forEach((btn) => {
        btn.setAttribute('aria-selected', String(btn.dataset.accountTab === this.accountTab));
      });
    }
    if (this.el['account-view-profile']) this.el['account-view-profile'].hidden = friends;
    if (this.el['account-view-friends']) this.el['account-view-friends'].hidden = !friends;
    if (this.el['account-title']) this.el['account-title'].textContent = friends ? '친구' : '내 계정';
    if (!friends) this.closeProfileEdit();
    else {
      this.el['ov-account']?.querySelector('.sheet')?.scrollTo?.({ top: 0 });
      void this.friends?.open();
    }
  }

  /** 받은 친구 요청 수를 계정 버튼·탭·친구 버튼의 빨간 점과 숫자로 보여 준다. */
  setFriendBadge(counts) {
    const data = counts || { friends: 0, incoming: 0, outgoing: 0 };
    this.friendCounts = {
      friends: Number(data.friends || 0),
      incoming: Number(data.incoming || 0),
      outgoing: Number(data.outgoing || 0),
    };
    const incoming = this.friendCounts.incoming;
    for (const id of ['account-badge', 'account-tab-dot', 'account-friend-dot', 'friend-dot-incoming']) {
      const node = this.el[id];
      if (node) node.hidden = incoming === 0;
    }
    if (this.el['account-friend-count']) {
      this.el['account-friend-count'].textContent = String(this.friendCounts.friends);
    }
    const btn = this.el['btn-account'];
    if (btn) {
      btn.classList.toggle('has-requests', incoming > 0);
      const name = this.user ? (this.user.displayName || this.user.username) : '';
      const label = this.user
        ? `내 계정 · ${name}${incoming ? ` · 받은 친구 요청 ${incoming}건` : ''}`
        : '로그인 · 회원가입';
      btn.setAttribute('aria-label', label);
      btn.setAttribute('title', this.user
        ? `내 계정 (${name})${incoming ? ` · 받은 친구 요청 ${incoming}건` : ''}`
        : '로그인');
    }
  }

  closeAccount(instant = false) {
    this.fadeOut('account', this.el['ov-account']);
    this.el['btn-account']?.setAttribute('aria-expanded', 'false');
    if (!instant) this.el['btn-account']?.focus({ preventScroll: true });
  }

  /** 화면을 옮기면 열린 계정 창을 애니메이션 없이 닫는다. */
  closeAll() {
    this.fadeOut('auth', this.el['ov-auth'], true);
    this.fadeOut('account', this.el['ov-account'], true);
    this.el['btn-account']?.setAttribute('aria-expanded', 'false');
  }

  /** Esc 로 닫기 — 애니메이션은 두고 포커스는 계정 버튼으로 돌려준다. */
  dismiss() {
    const authOpen = Boolean(this.el['ov-auth'] && !this.el['ov-auth'].hidden);
    const accountOpen = Boolean(this.el['ov-account'] && !this.el['ov-account'].hidden);
    if (authOpen) this.fadeOut('auth', this.el['ov-auth']);
    if (accountOpen) this.fadeOut('account', this.el['ov-account']);
    if (authOpen || accountOpen) this.el['btn-account']?.focus({ preventScroll: true });
    this.resetTurnstile();
    this.el['btn-account']?.setAttribute('aria-expanded', 'false');
  }

  isOpen() {
    return Boolean((this.el['ov-auth'] && !this.el['ov-auth'].hidden)
      || (this.el['ov-account'] && !this.el['ov-account'].hidden));
  }

  fadeOut(key, ov, instant = false) {
    if (!ov || ov.hidden) return;
    clearTimeout(this.closeTimers[key]);
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (instant || reduce) {
      ov.hidden = true;
      ov.classList.remove('ov-out');
      return;
    }
    ov.classList.add('ov-out');
    this.closeTimers[key] = setTimeout(() => {
      ov.hidden = true;
      ov.classList.remove('ov-out');
    }, 150);
  }

  /* ── 모드 · 오류 표시 ──────────────────────────────────── */

  setMode(mode) {
    this.mode = mode === 'signup' ? 'signup' : 'login';
    const signup = this.mode === 'signup';
    this.el['auth-title'].textContent = signup ? '회원가입' : '로그인';
    this.el['auth-tabs'].querySelectorAll('[data-mode]').forEach((tab) => {
      tab.setAttribute('aria-selected', String(tab.dataset.mode === this.mode));
    });
    this.el['auth-password2-field'].hidden = !signup;
    this.el['auth-submit-label'].textContent = signup ? '회원가입' : '로그인';
    this.el['auth-password'].setAttribute('autocomplete', signup ? 'new-password' : 'current-password');
    this.el['auth-hint'].textContent = signup
      ? '이메일 없이 아이디와 비밀번호만으로 시작해요. 봇 확인을 마치면 바로 가입돼요.'
      : '아이디와 비밀번호만 있으면 돼요. 이메일은 받지 않아요.';
  }

  showError(message) {
    const box = this.el['auth-error'];
    box.hidden = false;
    box.textContent = message;
  }

  clearError() {
    const box = this.el['auth-error'];
    if (box) {
      box.hidden = true;
      box.textContent = '';
    }
  }

  setBusy(busy) {
    this.busy = busy;
    const btn = this.el['auth-submit'];
    btn.disabled = busy;
    btn.classList.toggle('busy', busy);
    this.el['auth-submit-label'].textContent = busy
      ? '잠시만요…'
      : this.mode === 'signup' ? '회원가입' : '로그인';
  }

  /* ── 봇 방지 (Turnstile) ─────────────────────────────── */

  async startTurnstile() {
    const box = this.el['auth-turnstile'];
    if (!box) return;
    if (!this.config?.turnstileSiteKey) {
      box.innerHTML = '<p class="auth-hint auth-hint-bad">봇 확인이 준비되지 않아 아이디 로그인을 쓸 수 없어요.</p>';
      return;
    }
    if (this.turnstileId != null && window.turnstile) return;
    box.innerHTML = '<p class="auth-hint">봇 확인을 불러오는 중…</p>';
    if (!this.turnstileLoad) {
      this.turnstileLoad = loadScript(TURNSTILE_SRC)
        .then(async () => {
          for (let i = 0; i < 60 && !window.turnstile; i += 1) await wait(100);
          return Boolean(window.turnstile);
        })
        .catch(() => false);
    }
    const ready = await this.turnstileLoad;
    if (!ready || !window.turnstile) {
      box.innerHTML = '<p class="auth-hint auth-hint-bad">봇 확인을 불러오지 못했어요. 새로고침 후 다시 시도해 주세요.</p>';
      this.turnstileLoad = null;
      return;
    }
    if (this.turnstileId != null) return;
    box.innerHTML = '';
    try {
      this.turnstileId = window.turnstile.render(box, {
        sitekey: this.config.turnstileSiteKey,
        theme: 'light',
        language: 'ko',
        size: 'flexible',
        callback: (token) => {
          this.token = token;
        },
        'expired-callback': () => { this.token = null; },
        'error-callback': () => {
          this.token = null;
          this.showError('봇 확인을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.');
        },
      });
    } catch {
      this.turnstileId = null;
      box.innerHTML = '<p class="auth-hint auth-hint-bad">봇 확인을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.</p>';
    }
  }

  resetTurnstile() {
    this.token = null;
    if (this.turnstileId != null && window.turnstile) {
      try { window.turnstile.reset(this.turnstileId); } catch { /* 위젯이 이미 사라졌으면 그냥 둔다 */ }
    }
  }

  /* ── 구글 로그인 ──────────────────────────────────────── */

  async startGoogle() {
    const slot = this.el['auth-google-slot'];
    const note = this.el['auth-google-note'];
    if (!slot || !note) return;
    if (!this.config?.googleEnabled || !this.config.googleClientId) {
      slot.hidden = true;
      this.el['auth-or'].hidden = true;
      note.textContent = '구글 로그인은 아직 준비 중이에요.';
      note.hidden = false;
      return;
    }
    slot.hidden = false;
    this.el['auth-or'].hidden = false;
    note.hidden = true;
    if (this.googleReady) return;
    const loaded = await loadScript(GIS_SRC).then(() => true).catch(() => false);
    if (!loaded || !window.google?.accounts?.id) {
      note.textContent = '구글 로그인을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';
      note.hidden = false;
      return;
    }
    window.google.accounts.id.initialize({
      client_id: this.config.googleClientId,
      callback: (response) => this.onGoogleCredential(response),
      auto_select: false,
      cancel_on_tap_outside: true,
      ux_mode: 'popup',
    });
    slot.innerHTML = '';
    window.google.accounts.id.renderButton(slot, {
      type: 'standard',
      theme: 'outline',
      size: 'large',
      text: 'continue_with',
      shape: 'pill',
      logo_alignment: 'left',
      locale: 'ko',
      width: 300,
    });
    this.googleReady = true;
  }

  async onGoogleCredential(response) {
    if (!response?.credential || this.busy) return;
    this.setBusy(true);
    this.clearError();
    try {
      const res = await fetch('/api/auth/google', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ credential: response.credential }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        this.showError(ERROR_TEXT[data?.error] || data?.message || ERROR_TEXT.default);
        return;
      }
      this.afterSignIn(data.user);
    } catch {
      this.showError(ERROR_TEXT.network);
    } finally {
      this.setBusy(false);
    }
  }

  /* ── 아이디 · 비밀번호 제출 ───────────────────────────── */

  async onSubmit(event) {
    event.preventDefault();
    if (this.busy) return;
    const username = this.el['auth-username'].value.trim();
    const password = this.el['auth-password'].value;
    if (!username) return this.showError(ERROR_TEXT.username_required);
    if (!password) return this.showError(ERROR_TEXT.password_required);
    if (this.mode === 'signup' && password !== this.el['auth-password2'].value) {
      return this.showError(ERROR_TEXT.password_mismatch);
    }
    if (!this.token) return this.showError(ERROR_TEXT.turnstile_missing);
    this.setBusy(true);
    this.clearError();
    try {
      const endpoint = this.mode === 'signup' ? '/api/auth/register' : '/api/auth/login';
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username, password, turnstileToken: this.token }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        this.showError(ERROR_TEXT[data?.error] || data?.message || ERROR_TEXT.default);
        this.resetTurnstile();
        return;
      }
      this.afterSignIn(data.user);
      this.el['auth-form'].reset();
    } catch {
      this.showError(ERROR_TEXT.network);
      this.resetTurnstile();
    } finally {
      this.setBusy(false);
    }
  }

  afterSignIn(user) {
    this.setUser(user);
    this.closeAuth();
    this.resetTurnstile();
    pingAuth();
    this.sfx?.play('tap');
    const name = user?.displayName || user?.username || '';
    this.toast(name ? `${name}님, 반가워요!` : '로그인했어요.');
  }
  /* ── 내 계정 · 로그아웃 ───────────────────────────────── */

  fillAccount() {
    const user = this.user;
    if (!user) return;
    const name = user.displayName || user.username;
    if (this.el['account-name']) this.el['account-name'].textContent = name;
    if (this.el['account-handle']) this.el['account-handle'].textContent = `@${user.username}`;
    this.renderAvatar('account-avatar-letter', 'account-avatar-img', avatarSrc(user), name);
    if (this.el['account-provider']) {
      this.el['account-provider'].textContent = user.provider === 'google' ? '구글 로그인' : '아이디 + 비밀번호';
    }
    const joined = user.createdAt ? new Date(user.createdAt) : null;
    if (this.el['account-joined']) {
      this.el['account-joined'].textContent = joined && !Number.isNaN(joined.getTime())
        ? joined.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
        : '-';
    }
    if (this.el['account-friend-count']) {
      this.el['account-friend-count'].textContent = String(this.friendCounts.friends || 0);
    }
  }

  /** 글자 아바타와 사진 img 를 맞춰 그린다(사진이 없거나 못 불러오면 첫 글자). */
  renderAvatar(letterId, imgId, src, name) {
    const letter = this.el[letterId];
    const img = this.el[imgId];
    if (letter) {
      const first = [...String(name || '잇').trim()][0] || '잇';
      letter.textContent = first;
    }
    if (!img) return;
    if (!src) {
      img.hidden = true;
      img.removeAttribute('src');
      if (letter) letter.hidden = false;
      return;
    }
    img.onerror = () => {
      img.hidden = true;
      img.removeAttribute('src');
      if (letter) letter.hidden = false;
    };
    img.onload = () => {
      img.hidden = false;
      if (letter) letter.hidden = true;
    };
    img.src = src;
    img.hidden = false;
    if (letter) letter.hidden = true;
  }

  /* ── 닉네임 · 프로필 사진 바꾸기 ─────────────────────── */

  openProfileEdit() {
    if (!this.user) return;
    this.avatarDraft = '';
    this.avatarRemoved = false;
    this.clearProfileError();
    this.el['profile-nickname'].value = this.user.nickname || '';
    this.el['profile-nickname'].placeholder = this.user.username;
    this.el['profile-edit'].hidden = false;
    this.el['btn-profile-edit'].hidden = true;
    this.el['btn-avatar-remove'].hidden = !Number(this.user.avatarAt);
    this.renderAvatar('profile-photo-letter', 'profile-photo-img', avatarSrc(this.user),
      this.user.displayName || this.user.username);
    if (window.matchMedia('(pointer: fine)').matches) {
      setTimeout(() => this.el['profile-nickname'].focus({ preventScroll: true }), 60);
    }
  }

  closeProfileEdit() {
    if (!this.el['profile-edit']) return;
    this.el['profile-edit'].hidden = true;
    this.el['btn-profile-edit'].hidden = false;
    this.avatarDraft = '';
    this.avatarRemoved = false;
    this.el['avatar-file'].value = '';
    this.clearProfileError();
  }

  showProfileError(message) {
    const box = this.el['profile-error'];
    if (!box) return;
    box.hidden = !message;
    box.textContent = message || '';
  }

  clearProfileError() {
    this.showProfileError('');
  }

  setProfileBusy(busy) {
    this.profileBusy = busy;
    const save = this.el['btn-profile-save'];
    if (save) {
      save.disabled = busy;
      save.classList.toggle('busy', busy);
      save.textContent = busy ? '저장 중…' : '저장';
    }
  }

  /** `사진 고르기` → 파일 선택 → 이 기기에서 정사각 160px 로 줄인다. */
  async onAvatarPicked(event) {
    const file = event.target?.files?.[0];
    this.el['avatar-file'].value = '';
    if (!file) return;
    this.clearProfileError();
    try {
      const data = await fileToAvatar(file);
      this.avatarDraft = data;
      this.avatarRemoved = false;
      this.el['btn-avatar-remove'].hidden = false;
      this.renderAvatar('profile-photo-letter', 'profile-photo-img', data,
        this.user?.displayName || this.user?.username);
      this.sfx?.play('tap');
    } catch (error) {
      this.showProfileError(ERROR_TEXT[error?.code || error?.message] || ERROR_TEXT.avatar_invalid);
    }
  }

  /** `사진 지우기` — 저장을 눌러야 서버에서 지운다(지금 화면은 바로 첫 글자로). */
  removeAvatarDraft() {
    this.avatarDraft = '';
    this.avatarRemoved = true;
    this.el['btn-avatar-remove'].hidden = true;
    this.renderAvatar('profile-photo-letter', 'profile-photo-img', '',
      this.user?.displayName || this.user?.username);
    this.sfx?.play('tap');
  }

  async saveProfile() {
    if (!this.user || this.profileBusy) return;
    const nickname = this.el['profile-nickname'].value.trim();
    if (!nickname && !this.avatarDraft && !this.avatarRemoved) {
      return this.showProfileError(ERROR_TEXT.nickname_required);
    }
    if ([...nickname].length > 16) return this.showProfileError(ERROR_TEXT.nickname_long);

    const body = {};
    if (nickname !== (this.user.nickname || '')) {
      if (!nickname) return this.showProfileError(ERROR_TEXT.nickname_required);
      body.nickname = nickname;
    }
    if (this.avatarDraft) body.avatar = this.avatarDraft;
    else if (this.avatarRemoved) body.removeAvatar = true;
    if (!Object.keys(body).length) {
      this.closeProfileEdit();
      this.toast('바뀐 내용이 없어요.');
      return;
    }

    this.setProfileBusy(true);
    this.clearProfileError();
    try {
      const res = await fetch('/api/account/profile', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        this.setProfileBusy(false);
        this.showProfileError(ERROR_TEXT[data?.error] || data?.message || ERROR_TEXT.default);
        return;
      }
      this.setProfileBusy(false);
      this.setUser(data.user || this.user);
      this.closeProfileEdit();
      pingAuth();
      this.toast(data.changed?.avatarUpdated ? '프로필 사진을 바꿨어요.'
        : data.changed?.avatarRemoved ? '프로필 사진을 지웠어요.'
          : '닉네임을 바꿨어요.');
    } catch {
      this.setProfileBusy(false);
      this.showProfileError(ERROR_TEXT.network);
    }
  }

  async logout() {
    if (this.busy) return;
    this.setBusy(true);
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } catch {
      /* 세션이 이미 없어도 화면은 로그아웃 상태로 둔다 */
    }
    this.setBusy(false);
    this.setUser(null);
    this.closeAccount();
    pingAuth();
    this.toast('로그아웃했어요. 게스트로 이어서 즐길 수 있어요.');
  }

  /* ── 계정 삭제 (2단계 확인) ───────────────────────────── */

  /** 지금 계정이 구글 전용 계정인지(비밀번호가 없는지). */
  isGoogleAccount() {
    return this.user?.provider === 'google';
  }

  /** 구글 계정의 확인 문구가 맞는지: `삭제` 또는 `@아이디`(아이디만도 허용). */
  deletePhraseOk(value) {
    const phrase = String(value ?? '').trim();
    const username = this.user?.username || '';
    if (!username) return false;
    return phrase === '삭제' || phrase === `@${username}` || phrase === username;
  }

  showDeleteConfirm() {
    if (!this.user || this.deleteBusy) return;
    const google = this.isGoogleAccount();
    const input = this.el['account-delete-confirm'];
    const username = this.user.username;
    input.type = google ? 'text' : 'password';
    input.value = '';
    input.autocomplete = google ? 'off' : 'current-password';
    input.placeholder = google ? `@${username} 또는 삭제` : '현재 비밀번호';
    input.setAttribute('aria-label', google ? '확인 문구' : '현재 비밀번호');
    this.el['account-delete-label'].textContent = google ? '확인 문구' : '현재 비밀번호';
    this.el['account-delete-hint'].textContent = google
      ? `본인 확인을 위해 @${username} 또는 삭제 를 그대로 입력해 주세요.`
      : '본인 확인을 위해 지금 쓰는 비밀번호를 한 번 더 입력해 주세요.';
    this.el['account-delete-target'].textContent = `@${username} 계정이 영구적으로 지워져요.`;
    this.clearDeleteError();
    this.syncDeleteButton();
    this.el['account-main'].hidden = true;
    this.el['account-delete-view'].hidden = false;
    this.sfx?.play('tap');
    if (window.matchMedia('(pointer: fine)').matches) {
      setTimeout(() => input.focus({ preventScroll: true }), 60);
    }
  }

  hideDeleteConfirm() {
    if (!this.el['account-delete-view']) return;
    this.el['account-delete-view'].hidden = true;
    this.el['account-main'].hidden = false;
    if (this.el['account-delete-confirm']) this.el['account-delete-confirm'].value = '';
    this.clearDeleteError();
    this.setDeleteBusy(false);
  }

  /** 확인 문구를 알맞게 입력했을 때만 `영구 삭제`가 눌린다. */
  syncDeleteButton() {
    const btn = this.el['btn-delete-confirm'];
    if (!btn) return;
    const value = this.el['account-delete-confirm'].value;
    const ready = this.isGoogleAccount() ? this.deletePhraseOk(value) : value.length > 0;
    btn.disabled = this.deleteBusy || !ready;
  }

  showDeleteError(message) {
    const box = this.el['account-delete-error'];
    if (!box) return;
    box.hidden = false;
    box.textContent = message;
  }

  clearDeleteError() {
    const box = this.el['account-delete-error'];
    if (!box) return;
    box.hidden = true;
    box.textContent = '';
  }

  setDeleteBusy(busy) {
    this.deleteBusy = busy;
    const btn = this.el['btn-delete-confirm'];
    if (!btn) return;
    btn.classList.toggle('busy', busy);
    btn.textContent = busy ? '지우는 중…' : '영구 삭제';
    btn.disabled = busy;
    if (!busy) this.syncDeleteButton();
  }

  async deleteAccount() {
    if (!this.user || this.deleteBusy) return;
    const google = this.isGoogleAccount();
    const raw = this.el['account-delete-confirm'].value;
    const phrase = raw.trim();
    if (google) {
      if (!this.deletePhraseOk(phrase)) {
        return this.showDeleteError(`@${this.user.username} 또는 삭제 를 그대로 입력해 주세요.`);
      }
    } else if (!raw) {
      return this.showDeleteError(ERROR_TEXT.password_required);
    }

    this.setDeleteBusy(true);
    this.clearDeleteError();
    try {
      const res = await fetch('/api/auth/delete', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(google ? { confirm: phrase } : { password: raw }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) {
        this.setDeleteBusy(false);
        this.showDeleteError(ERROR_TEXT[data?.error] || data?.message || ERROR_TEXT.default);
        if (data?.error === 'password_mismatch' || data?.error === 'confirm_mismatch') {
          this.el['account-delete-confirm'].select();
        }
        if (data?.error === 'not_signed_in') {
          this.setUser(null);
          this.closeAccount();
        }
        return;
      }
      this.setDeleteBusy(false);
      this.setUser(null);
      this.hideDeleteConfirm();
      this.closeAccount(true);
      pingAuth();
      this.toast('계정을 삭제했어요. 게스트로 이어서 즐길 수 있어요.');
    } catch {
      this.setDeleteBusy(false);
      this.showDeleteError(ERROR_TEXT.network);
    }
  }

  /* ── 이벤트 ───────────────────────────────────────────── */

  bind() {
    this.el['btn-account'].addEventListener('click', () => this.toggle());
    this.el['btn-auth-close'].addEventListener('click', () => {
      this.closeAuth();
      this.sfx?.play('tap');
    });
    this.el['btn-account-close'].addEventListener('click', () => {
      this.closeAccount();
      this.sfx?.play('tap');
    });
    this.el['ov-auth'].addEventListener('click', (event) => {
      if (event.target === this.el['ov-auth']) this.closeAuth();
    });
    this.el['ov-account'].addEventListener('click', (event) => {
      if (event.target === this.el['ov-account']) this.closeAccount();
    });
    this.el['auth-tabs'].addEventListener('click', (event) => {
      const tab = event.target.closest('[data-mode]');
      if (!tab) return;
      if (tab.dataset.mode === this.mode) return;
      this.setMode(tab.dataset.mode);
      this.clearError();
      this.sfx?.play('tap');
    });
    this.el['auth-form'].addEventListener('submit', (event) => this.onSubmit(event));
    this.el['btn-logout'].addEventListener('click', () => this.logout());

    // 탭(내 계정 · 친구) · 친구 열기
    this.el['account-tabs'].addEventListener('click', (event) => {
      const tab = event.target.closest('[data-account-tab]');
      if (!tab || tab.dataset.accountTab === this.accountTab) return;
      this.sfx?.play('tap');
      this.showAccountTab(tab.dataset.accountTab);
    });
    this.el['btn-friends-open'].addEventListener('click', () => {
      this.sfx?.play('tap');
      this.showAccountTab('friends');
    });

    // 닉네임 · 사진 바꾸기
    this.el['btn-profile-edit'].addEventListener('click', () => {
      this.sfx?.play('tap');
      this.openProfileEdit();
    });
    this.el['btn-profile-cancel'].addEventListener('click', () => {
      this.closeProfileEdit();
      this.sfx?.play('tap');
    });
    this.el['btn-profile-save'].addEventListener('click', () => this.saveProfile());
    this.el['btn-avatar-pick'].addEventListener('click', () => this.el['avatar-file'].click());
    this.el['btn-avatar-remove'].addEventListener('click', () => this.removeAvatarDraft());
    this.el['avatar-file'].addEventListener('change', (event) => this.onAvatarPicked(event));
    this.el['profile-nickname'].addEventListener('input', () => this.clearProfileError());
    this.el['profile-nickname'].addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      if (!this.el['btn-profile-save'].disabled) this.saveProfile();
    });

    this.el['btn-delete-account'].addEventListener('click', () => this.showDeleteConfirm());
    this.el['btn-delete-cancel'].addEventListener('click', () => {
      this.hideDeleteConfirm();
      this.sfx?.play('tap');
    });
    this.el['btn-delete-confirm'].addEventListener('click', () => this.deleteAccount());
    this.el['account-delete-confirm'].addEventListener('input', () => {
      this.clearDeleteError();
      this.syncDeleteButton();
    });
    this.el['account-delete-confirm'].addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      if (!this.el['btn-delete-confirm'].disabled) this.deleteAccount();
    });
    for (const id of ['auth-username', 'auth-password', 'auth-password2']) {
      this.el[id].addEventListener('input', () => this.clearError());
    }
  }
}
