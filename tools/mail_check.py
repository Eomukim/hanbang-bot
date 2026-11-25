#!/usr/bin/env python3
"""메일함(받은 · 보낸 · 공지 · 빨간 동그라미) 전 흐름 점검.

로컬 `wrangler pages dev`(+로컬 D1)에서 아래를 차례로 확인한다.

 1. 게스트: 공지 읽기 · 받은/보낸/쓰기는 로그인 안내 · 비로그인 inbox/send 401 ·
    공지 작성/삭제 403 · 빨간 동그라미(새 공지) 표시와 확인 뒤 소멸
 2. 로그인: 관리자만 공지 작성 UI·API(일반 유저 403), 공지 읽음(notice_reads)
 3. 메일: A → B 발송(빨간 동그라미) → B 읽음(뱃지 소멸) → 답장(Re:, reply_to_id) →
    A 받은함 확인 → 삭제는 **휴지통**으로(상대 함 유지) → 목록에서 복구 → 상세에서 완전 삭제 →
    B 도 휴지통을 비우면 그때 행 삭제
 4. 수정: 보낸 메일 수정(인라인 폼·`(수정됨)`·상대 받은함 제목 변경·updated_at),
    휴지통에 넣은 내 메일은 수정 불가, 공지 수정(관리자만·`(수정됨)`)
 5. 보안: 비로그인 401 · 비관리자 403 · no-store · Prepared Statement(SQL 인젝션 시도) ·
    textContent 렌더링(XSS 태그가 글자로만 보임) · 길이 제한 · 요청 횟수 제한
 6. 계정 삭제 시 그 사용자의 메일·공지 읽음 기록 정리
 7. 데스크톱·모바일 화면과 보고용 스크린샷(네 탭이 320~390px 에서 잘리지 않는지 포함)

브라우저는 한 번에 두 페이지까지만 띄운다(사전 73만 단어를 페이지마다 올리므로
컨텍스트를 여러 개 동시에 열어 두면 렌더러가 메모리 부족으로 죽는다).

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/mail_check.py --local
"""
import argparse
import json
import os
import random
import shutil
import string
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRANGLER = '/workspace/tools-npm/node_modules/.bin/wrangler'
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
PORT = 8792
LOCAL_URL = f'http://127.0.0.1:{PORT}'
ADMIN_NAME = '점검관리자'  # wrangler.local.toml 의 ADMIN_USERNAMES
PASSWORD = 'itda-Mail-24'

PASS = 0
FAIL = 0
SHOTS = {}
SHOT_DIR = os.path.join(ROOT, 'downloads', 'mail-check')
MIGRATION_FILE = os.path.join('db', 'migrations', '2026-11-25-mail-trash-edit.sql')


def apply_migrations():
    """이미 만들어진 로컬 D1 에 새 칸을 더한다(이미 있으면 ADD COLUMN 이 실패하므로 무시)."""
    path = os.path.join(ROOT, MIGRATION_FILE)
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as handle:
        sql = handle.read()
    for raw in sql.split(';'):
        lines = [line for line in raw.splitlines() if not line.strip().startswith('--')]
        statement = '\n'.join(lines).strip()
        if not statement:
            continue
        try:
            d1(statement)
        except Exception:
            pass


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {label}')
    else:
        FAIL += 1
        print(f'  ✗ {label}' + (f' — {detail}' if detail else ''))


def ensure_local_config():
    """Pages dev 는 표준 이름(wrangler.toml)만 읽는다. 커밋하지 않는 wrangler.local.toml 을 임시로 쓴다."""
    src = os.path.join(ROOT, 'wrangler.local.toml')
    dst = os.path.join(ROOT, 'wrangler.toml')
    if os.path.exists(dst):
        return False
    if os.path.exists(src):
        shutil.copy(src, dst)
        return True
    raise RuntimeError('wrangler.local.toml 이 없어 로컬 바인딩을 만들 수 없습니다')


def wrangler_env():
    env = dict(os.environ)
    env['PATH'] = '/workspace/.local/node/bin:' + env.get('PATH', '')
    env['WRANGLER_SEND_METRICS'] = 'false'
    return env


def d1(sql):
    proc = subprocess.run(
        [WRANGLER, 'd1', 'execute', 'itda-db', '--local', '--json', '--command', sql],
        cwd=ROOT, env=wrangler_env(), capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    text = proc.stdout.strip()
    start = text.find('[') if text.find('[') >= 0 else text.find('{')
    return json.loads(text[start:]) if start >= 0 else []


def d1_file(path):
    proc = subprocess.run(
        [WRANGLER, 'd1', 'execute', 'itda-db', '--local', '--file', path],
        cwd=ROOT, env=wrangler_env(), capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def start_local():
    proc = subprocess.Popen(
        [WRANGLER, 'pages', 'dev', '.', '--port', str(PORT), '--ip', '127.0.0.1'],
        cwd=ROOT, env=wrangler_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(90):
        try:
            urllib.request.urlopen(f'{LOCAL_URL}/api/auth/config', timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError('로컬 서버가 뜨지 않았습니다')


def api(page, path, method='GET', body=None):
    payload = json.dumps(body) if body is not None else 'null'
    return page.evaluate(
        """async ([path, method, payload]) => {
            const res = await fetch(path, {
              method,
              credentials: 'same-origin',
              headers: payload === 'null'
                ? {accept: 'application/json'}
                : {'content-type': 'application/json', accept: 'application/json'},
              body: payload === 'null' ? undefined : payload,
            });
            let data = null;
            try { data = await res.json(); } catch (e) { data = null; }
            return {status: res.status, data, cache: res.headers.get('cache-control') || ''};
        }""",
        [path, method, payload],
    )


def wait_ready(page):
    page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=60000)
    page.wait_for_timeout(350)


def signup(page, username, password=PASSWORD):
    return api(page, '/api/auth/register', 'POST', {
        'username': username, 'password': password, 'turnstileToken': 'local-test-token',
    })


def login(page, username, password=PASSWORD):
    return api(page, '/api/auth/login', 'POST', {
        'username': username, 'password': password, 'turnstileToken': 'local-test-token',
    })


def shot(page, name, cls=None):
    path = os.path.join(SHOT_DIR, f'{name}.png')
    if cls:
        page.locator(cls).screenshot(path=path)
    else:
        page.screenshot(path=path, full_page=False)
    SHOTS[name] = path


def new_name(prefix):
    return prefix + ''.join(random.choice(string.digits) for _ in range(4))


def open_mail(page):
    page.click('#btn-mail')
    page.wait_for_selector('#ov-mail:not([hidden])', timeout=8000)
    page.wait_for_timeout(500)


def close_mail(page):
    page.click('#btn-mail-close')
    page.wait_for_timeout(350)


def tab(page, key):
    page.click(f'#mail-tabs [data-mail-tab="{key}"]')
    page.wait_for_timeout(900)


def run(headless=True):
    names = {
        'admin': ADMIN_NAME,
        'a': new_name('점검메일'),
        'b': new_name('점검쪽지'),
        'c': new_name('점검스팸'),
        'd': new_name('점검탈퇴'),
    }
    created = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=headless,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])

        def open_page(user=None, width=1280, height=900, mobile=False):
            ctx = browser.new_context(
                viewport={'width': width, 'height': height},
                device_scale_factor=2 if mobile else 1,
                is_mobile=mobile, has_touch=mobile, locale='ko-KR',
            )
            page = ctx.new_page()
            page.goto(LOCAL_URL, wait_until='domcontentloaded')
            wait_ready(page)
            if user:
                login(page, user)
                page.reload(wait_until='domcontentloaded')
                wait_ready(page)
            return ctx, page

        def drop(ctx):
            try:
                ctx.close()
            except Exception:
                pass

        # ── 준비: 계정 ────────────────────────────────────────────────
        print('· 준비: 점검 계정')
        ctx_seed, seed = open_page()
        for key in ('a', 'b', 'c', 'd'):
            res = signup(seed, names[key])
            created.append(names[key])
            check(res['status'] == 200 and res['data'].get('ok'),
                  f"점검 계정 {names[key]} 가입", json.dumps(res, ensure_ascii=False)[:160])
        admin = login(seed, ADMIN_NAME)
        if admin['status'] != 200:
            admin = signup(seed, ADMIN_NAME)
            created.append(ADMIN_NAME)
        check(admin['status'] == 200, f'관리자 {ADMIN_NAME} 준비',
              json.dumps(admin, ensure_ascii=False)[:160])
        drop(ctx_seed)

        # ── 1. 게스트 ─────────────────────────────────────────────────
        print('\n· 게스트')
        ctx_guest, guest = open_page()
        order = guest.eval_on_selector_all('.top-actions .top-btn', 'els => els.map(e => e.id)')
        check(order[:4] == ['btn-settings', 'btn-dict', 'btn-mail', 'btn-account'],
              '상단 버튼 순서: 설정 · 사전 · 메일 · 계정', json.dumps(order))
        check(guest.is_visible('#btn-mail'), '메일함 버튼이 보임')
        check(guest.inner_text('#btn-mail').strip() == '', '메일함 버튼은 아이콘만(글자 없음)',
              guest.inner_text('#btn-mail'))
        check(not guest.is_visible('#mail-badge'), '공지가 없을 때 빨간 동그라미 없음')

        res = api(guest, '/api/mail/summary')
        check(res['status'] == 200 and res['data'].get('signedIn') is False,
              '게스트 summary 200 · signedIn false', json.dumps(res, ensure_ascii=False)[:200])
        check('no-store' in res['cache'], 'summary 응답이 no-store', res['cache'])
        res = api(guest, '/api/mail/notices')
        check(res['status'] == 200 and isinstance(res['data'].get('notices'), list),
              '게스트 공지 목록 200', json.dumps(res, ensure_ascii=False)[:200])
        check('no-store' in res['cache'], 'notices 응답이 no-store', res['cache'])
        res = api(guest, '/api/mail/inbox')
        check(res['status'] == 401, '비로그인 받은 메일 401', str(res['status']))
        res = api(guest, '/api/mail/send', 'POST', {'to': '@누구', 'subject': 'x', 'body': 'y'})
        check(res['status'] == 401, '비로그인 메일 발송 401', str(res['status']))
        res = api(guest, '/api/mail/notices', 'POST', {'title': 'x', 'body': 'y'})
        check(res['status'] == 403, '비로그인 공지 작성 403', str(res['status']))
        res = api(guest, '/api/mail/notices', 'DELETE', {'id': 'n_unknown'})
        check(res['status'] == 403, '비로그인 공지 삭제 403', str(res['status']))

        open_mail(guest)
        check(guest.is_visible('#mail-view-list'), '메일함 창이 열림')
        check(guest.get_attribute('#mail-tabs [data-mail-tab="notices"]', 'aria-selected') == 'true',
              '게스트는 공지사항 탭부터')
        check('아직 공지사항이 없어요' in guest.inner_text('#mail-empty-title'),
              '공지 없음 안내', guest.inner_text('#mail-empty-title'))
        tab(guest, 'inbox')
        check(guest.is_visible('#mail-login-btn'), '비로그인 받은 메일에 로그인 버튼')
        check('로그인하면' in guest.inner_text('#mail-empty-title'),
              '로그인 안내 문구', guest.inner_text('#mail-empty-title'))
        check(not guest.is_visible('#mail-compose-btn'), '게스트에게는 새 메일 쓰기 버튼 없음')
        shot(guest, 'local-desktop-mail-guest-inbox')
        close_mail(guest)
        drop(ctx_guest)

        # ── 2. 일반 유저 403 · 관리자 공지 ────────────────────────────
        print('\n· 공지사항')
        ctx_admin, ap = open_page(names['admin'])
        me = api(ap, '/api/auth/me')
        check(me['data'].get('user', {}) and me['data']['user']['username'] == ADMIN_NAME,
              '관리자 세션으로 접속', json.dumps(me, ensure_ascii=False)[:160])
        res = api(ap, '/api/mail/summary')
        check(res['data'].get('isAdmin') is True, '관리자 summary isAdmin true',
              json.dumps(res, ensure_ascii=False)[:160])

        ctx_a, a = open_page(names['a'])
        res = api(a, '/api/auth/me')
        check(res['data'].get('user', {}) and res['data']['user']['username'] == names['a'],
              'A 세션으로 접속', json.dumps(res, ensure_ascii=False)[:160])
        res = api(a, '/api/mail/notices', 'POST', {'title': '일반 유저 공지', 'body': '막혀야 함'})
        check(res['status'] == 403 and res['data'].get('error') == 'forbidden',
              '일반 유저 공지 작성 403 forbidden', json.dumps(res, ensure_ascii=False)[:160])
        res = api(a, '/api/mail/summary')
        check(res['data'].get('isAdmin') is False, '일반 유저 summary isAdmin false',
              json.dumps(res, ensure_ascii=False)[:160])

        res = api(ap, '/api/mail/notices', 'POST', {
            'title': '잇다 메일함이 열렸어요', 'body': '이제 플레이어끼리 쪽지를 주고받을 수 있어요.',
        })
        check(res['status'] == 200 and res['data'].get('notice', {}).get('id'),
              '관리자 공지 작성 200', json.dumps(res, ensure_ascii=False)[:160])
        notice1 = res['data'].get('notice', {})
        res = api(ap, '/api/mail/notices', 'POST', {
            'title': '메일을 보낼 때 지켜 주세요', 'body': '욕설·광고는 지워질 수 있어요.',
        })
        notice2 = res['data'].get('notice', {})
        res = api(a, '/api/mail/notices')
        check(len(res['data'].get('notices', [])) == 2, '공지 2건이 모두에게 보임',
              str(len(res['data'].get('notices', []))))

        # 일반 유저 A: 공지 작성 버튼 없음 · 공지 읽기 · 뱃지 소멸
        open_mail(a)
        check(a.is_visible('#mail-tab-dot-notices'), '안 읽은 공지가 있으면 공지 탭에 점')
        tab(a, 'notices')
        check(not a.is_visible('#mail-notice-new'), '일반 유저에게는 공지 작성 버튼 없음')
        check(a.locator('#mail-list .notice-item').count() == 2, 'A가 공지를 2건 봄',
              str(a.locator('#mail-list .notice-item').count()))
        check(not a.is_visible('#mail-tab-dot-notices'), '공지를 연 뒤 공지 탭 점이 사라짐')
        a.wait_for_timeout(600)
        check(not a.is_visible('#mail-badge'), '공지를 읽은 뒤 빨간 동그라미 소멸')
        res = api(a, '/api/mail/summary')
        check(res['data'].get('unreadNoticeCount') == 0, 'notice_reads 로 공지 읽음 0',
              str(res['data'].get('unreadNoticeCount')))
        shot(a, 'local-desktop-mail-notices')
        a.click('#mail-list .mail-open')
        a.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        check(not a.is_visible('#mail-delete-btn'), '일반 유저는 공지 상세에 삭제 버튼 없음')
        a.click('#mail-detail-back')
        a.wait_for_timeout(700)
        close_mail(a)
        drop(ctx_a)

        # 관리자 UI: 공지 작성 폼으로 한 건 더
        open_mail(ap)
        check(not ap.is_visible('#mail-notice-new'), '받은 메일 탭에서는 공지 작성 버튼이 숨겨짐')
        tab(ap, 'notices')
        check(ap.is_visible('#mail-notice-new'), '관리자에게 공지 작성 버튼이 보임')
        ap.click('#mail-notice-new')
        ap.wait_for_selector('#mail-view-notice:not([hidden])', timeout=5000)
        ap.fill('#mail-notice-title', '주말 점검 안내')
        ap.fill('#mail-notice-body', '토요일 새벽 2시에 잠깐 점검이 있어요.')
        shot(ap, 'local-desktop-mail-notice-form')
        ap.click('#mail-notice-submit')
        ap.wait_for_timeout(1600)
        check(ap.is_visible('#mail-view-list'), '공지 작성 뒤 목록으로 돌아옴')
        check(ap.locator('#mail-list .notice-item').count() == 3, '공지 3건 표시',
              str(ap.locator('#mail-list .notice-item').count()))
        res = api(ap, '/api/mail/notices')
        created_notice = next((n for n in res['data'].get('notices', []) if n['title'] == '주말 점검 안내'), None)
        check(created_notice is not None, '새 공지가 서버에 저장됨')
        ap.click('#mail-list .mail-open')
        ap.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        check(ap.is_visible('#mail-delete-btn'), '관리자는 공지 상세에 삭제 버튼')
        shot(ap, 'local-desktop-mail-notice-detail-admin')
        ap.click('#mail-detail-back')
        ap.wait_for_timeout(600)
        shot(ap, 'local-desktop-mail-notices-admin')
        drop(ctx_admin)

        # ── 3. 게스트 빨간 동그라미 (새 공지) ─────────────────────────
        print('\n· 게스트 빨간 동그라미')
        ctx_guest2, guest2 = open_page()
        guest2.wait_for_timeout(700)
        check(guest2.is_visible('#mail-badge'), '새 공지가 있으면 게스트에게 빨간 동그라미')
        badge_bg = guest2.eval_on_selector('#mail-badge', 'el => getComputedStyle(el).backgroundColor')
        check(badge_bg == 'rgb(216, 57, 43)', '동그라미가 빨간색', badge_bg)
        shot(guest2, 'local-desktop-home-badge')
        shot(guest2, 'local-desktop-mail-icon', cls='.top-actions')
        open_mail(guest2)
        tab(guest2, 'notices')
        guest2.wait_for_timeout(700)
        check(guest2.locator('#mail-list .notice-item').count() == 3, '게스트가 공지 3건을 읽음',
              str(guest2.locator('#mail-list .notice-item').count()))
        check(not guest2.is_visible('#mail-badge'), '게스트도 확인하면 동그라미 소멸')
        close_mail(guest2)
        drop(ctx_guest2)

        # ── 4. A → B 메일 · 빨간 동그라미 ────────────────────────────
        print('\n· 메일 보내기 · 빨간 동그라미')
        ctx_a2, a2 = open_page(names['a'])
        open_mail(a2)
        tab(a2, 'inbox')
        check(a2.is_visible('#mail-compose-btn'), '로그인 유저에게 새 메일 쓰기 버튼')
        a2.click('#mail-compose-btn')
        a2.wait_for_selector('#mail-view-compose:not([hidden])', timeout=5000)
        a2.fill('#mail-to', '@' + names['b'])
        a2.fill('#mail-subject', '잇다에서 처음 보내는 메일')
        a2.fill('#mail-content', '안녕하세요! 끝말잇기 한 판 어때요?')
        shot(a2, 'local-desktop-mail-compose')
        a2.click('#mail-compose-submit')
        a2.wait_for_timeout(1800)
        check(a2.is_visible('#mail-view-list'), '보낸 뒤 목록으로 돌아옴')
        check(a2.locator('#mail-tabs [data-mail-tab="sent"]').get_attribute('aria-selected') == 'true',
              '보낸 뒤 보낸 메일 탭으로 이동')
        check(a2.locator('#mail-list .mail-item').count() == 1, '보낸 메일 1건',
              str(a2.locator('#mail-list .mail-item').count()))
        check('아직 안 읽음' in a2.inner_text('#mail-list'), '보낸 메일에 아직 안 읽음 표시')
        shot(a2, 'local-desktop-mail-sent')
        close_mail(a2)
        drop(ctx_a2)

        ctx_b, b = open_page(names['b'])
        res = api(b, '/api/auth/me')
        check(res['data'].get('user', {}) and res['data']['user']['username'] == names['b'],
              'B 세션으로 접속', json.dumps(res, ensure_ascii=False)[:160])
        res = api(b, '/api/mail/summary')
        check(res['data'].get('unreadMailCount') == 1, 'B의 안 읽은 메일 1통',
              json.dumps(res['data'], ensure_ascii=False)[:160])
        b.wait_for_timeout(700)
        check(b.is_visible('#mail-badge'), 'B 홈에 빨간 동그라미')
        shot(b, 'local-desktop-home-badge-mail')
        open_mail(b)
        check(b.locator('#mail-list .mail-item').count() == 1, 'B 받은 메일 1건',
              str(b.locator('#mail-list .mail-item').count()))
        check(b.locator('#mail-list .mail-item.unread').count() == 1, '받은 메일이 안 읽음 상태')
        shot(b, 'local-desktop-mail-inbox')

        # ── 5. B 읽음 · 답장 ────────────────────────────────────────
        print('\n· 읽음 · 답장')
        # 공지를 먼저 다 읽어도 안 읽은 메일이 남아 있으면 동그라미는 그대로다.
        b.click('#mail-tabs [data-mail-tab="notices"]')
        b.wait_for_timeout(900)
        check(b.is_visible('#mail-badge'), '공지를 읽어도 안 읽은 메일이 있으면 동그라미 유지')
        b.click('#mail-tabs [data-mail-tab="inbox"]')
        b.wait_for_timeout(900)
        b.click('#mail-list .mail-open')
        b.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        check(b.inner_text('#mail-detail-subject') == '잇다에서 처음 보내는 메일',
              '메일 상세 제목', b.inner_text('#mail-detail-subject'))
        check('@' + names['a'] in b.inner_text('#mail-detail-meta'), '보낸 사람 표시',
              b.inner_text('#mail-detail-meta'))
        check('끝말잇기 한 판' in b.inner_text('#mail-detail-body'), '본문 표시')
        b.wait_for_timeout(700)
        res = api(b, '/api/mail/summary')
        check(res['data'].get('unreadMailCount') == 0, '메일을 열면 읽음 처리(안 읽은 0)',
              json.dumps(res['data'], ensure_ascii=False)[:160])
        shot(b, 'local-desktop-mail-detail')
        check(not b.is_visible('#mail-badge'), 'B의 빨간 동그라미 소멸')

        b.click('#mail-reply-btn')
        b.wait_for_selector('#mail-view-compose:not([hidden])', timeout=5000)
        check(b.input_value('#mail-to') == names['a'], '답장 받는 사람 자동 입력',
              b.input_value('#mail-to'))
        check(b.input_value('#mail-subject') == 'Re: 잇다에서 처음 보내는 메일',
              '답장 제목에 Re: 한 번만', b.input_value('#mail-subject'))
        shot(b, 'local-desktop-mail-reply')
        b.fill('#mail-content', '좋아요! 지금 한 판 해요.')
        b.click('#mail-compose-submit')
        b.wait_for_timeout(1800)
        check(b.locator('#mail-tabs [data-mail-tab="sent"]').get_attribute('aria-selected') == 'true',
              '답장을 보낸 뒤 보낸 메일 탭')
        res = api(b, '/api/mail/sent')
        reply = res['data'].get('mails', [{}])[0]
        check(reply.get('replyToId') is not None, '답장이 reply_to_id 로 연결됨',
              json.dumps(reply, ensure_ascii=False)[:160])
        reply_id = reply.get('id')
        close_mail(b)
        drop(ctx_b)

        # ── 6. A 답장 확인 · 삭제 → 휴지통 ─────────────────────────
        print('\n· 답장 확인 · 휴지통')
        ctx_a3, a3 = open_page(names['a'])
        a3.wait_for_timeout(700)
        check(a3.is_visible('#mail-badge'), 'A 홈에 빨간 동그라미(답장 도착)')
        open_mail(a3)
        a3.click('#mail-tabs [data-mail-tab="notices"]')
        a3.wait_for_timeout(900)
        a3.click('#mail-tabs [data-mail-tab="inbox"]')
        a3.wait_for_timeout(900)
        check(a3.locator('#mail-list .mail-item').count() == 1, 'A 받은 메일 1건',
              str(a3.locator('#mail-list .mail-item').count()))
        a3.click('#mail-list .mail-open')
        a3.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        subject = a3.inner_text('#mail-detail-subject')
        check(subject.startswith('Re:') and subject.count('Re:') == 1,
              'A가 받은 답장 제목이 Re: 한 번', subject)
        a3.wait_for_timeout(500)
        check(not a3.is_visible('#mail-badge'), 'A가 답장을 읽으면 빨간 동그라미 소멸')
        a3.click('#mail-delete-btn')
        a3.wait_for_timeout(150)
        check(a3.inner_text('#mail-delete-btn') == '정말 삭제?', '삭제는 한 번 더 확인',
              a3.inner_text('#mail-delete-btn'))
        shot(a3, 'local-desktop-mail-detail-armed')
        a3.click('#mail-delete-btn')
        a3.wait_for_timeout(1500)
        check(a3.is_visible('#mail-view-list'), '삭제 뒤 목록으로')
        check(a3.locator('#mail-list .mail-item').count() == 0, 'A 받은 메일함에서 사라짐',
              str(a3.locator('#mail-list .mail-item').count()))
        rows = d1(f"SELECT recipient_trashed_at, deleted_by_recipient FROM mails WHERE id = '{reply_id}'")
        row = rows[0]['results'][0]
        check(row['recipient_trashed_at'] is not None and row['deleted_by_recipient'] == 0,
              '삭제는 행을 지우지 않고 휴지통 시각만 기록', row)
        tab(a3, 'trash')
        check(a3.locator('#mail-list .mail-item').count() == 1, '휴지통에 1건',
              str(a3.locator('#mail-list .mail-item').count()))
        check('받은 메일' in a3.inner_text('#mail-list'), '휴지통 항목에 받은 메일 표시',
              a3.inner_text('#mail-list')[:80])
        check(a3.is_visible('#mail-trash-empty'), '휴지통 비우기 버튼이 보임')
        check(not a3.is_visible('#mail-compose-btn'), '휴지통 탭에는 새 메일 쓰기 버튼 없음')
        shot(a3, 'local-desktop-mail-trash')

        # ── 6b. 복구 · 완전 삭제 · 휴지통 비우기 ────────────────────
        print('\n· 복구 · 완전 삭제')
        a3.click('#mail-list .mail-item-restore')
        a3.wait_for_timeout(1500)
        check(a3.locator('#mail-list .mail-item').count() == 0, '목록에서 복구하면 휴지통이 빔',
              str(a3.locator('#mail-list .mail-item').count()))
        tab(a3, 'inbox')
        check(a3.locator('#mail-list .mail-item').count() == 1, '복구한 메일이 받은 메일함으로 돌아옴',
              str(a3.locator('#mail-list .mail-item').count()))
        # 다시 휴지통으로 → 상세에서 완전 삭제
        a3.click('#mail-list .mail-open')
        a3.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        a3.click('#mail-delete-btn')
        a3.wait_for_timeout(120)
        a3.click('#mail-delete-btn')
        a3.wait_for_timeout(1400)
        tab(a3, 'trash')
        a3.click('#mail-list .mail-open')
        a3.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        check(a3.inner_text('#mail-delete-btn') == '완전 삭제', '휴지통 상세 버튼은 완전 삭제',
              a3.inner_text('#mail-delete-btn'))
        check(a3.is_visible('#mail-restore-btn') and not a3.is_visible('#mail-reply-btn'),
              '휴지통 상세에는 복구가 있고 답장은 없음')
        a3.click('#mail-delete-btn')
        a3.wait_for_timeout(150)
        check(a3.inner_text('#mail-delete-btn') == '정말 삭제?', '완전 삭제도 한 번 더 확인',
              a3.inner_text('#mail-delete-btn'))
        shot(a3, 'local-desktop-mail-purge-armed')
        a3.click('#mail-delete-btn')
        a3.wait_for_timeout(1500)
        check(a3.locator('#mail-list .mail-item').count() == 0, '완전 삭제 뒤 휴지통이 빔',
              str(a3.locator('#mail-list .mail-item').count()))
        rows = d1(f"SELECT deleted_by_sender, deleted_by_recipient FROM mails WHERE id = '{reply_id}'")
        row = rows[0]['results'][0] if rows and rows[0].get('results') else {}
        check(row.get('deleted_by_recipient') == 1 and row.get('deleted_by_sender') == 0,
              '완전 삭제는 내 쪽 deleted_by_recipient 만 세움(상대 함은 유지)', row)
        close_mail(a3)

        # B 도 자기 쪽에서 지우고 휴지통을 비우면 그때 행이 실제로 사라진다
        ctx_b2, b2 = open_page(names['b'])
        open_mail(b2)
        tab(b2, 'sent')
        b2.wait_for_timeout(600)
        check(b2.locator('#mail-list .mail-item').count() == 1, 'B 보낸 메일 1건',
              str(b2.locator('#mail-list .mail-item').count()))
        b2.click('#mail-list .mail-open')
        b2.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        b2.click('#mail-delete-btn')
        b2.wait_for_timeout(120)
        b2.click('#mail-delete-btn')
        b2.wait_for_timeout(1400)
        check(b2.locator('#mail-list .mail-item').count() == 0, 'B 보낸 메일함에서 사라짐',
              str(b2.locator('#mail-list .mail-item').count()))
        tab(b2, 'trash')
        check(b2.locator('#mail-list .mail-item').count() == 1, 'B 휴지통에 1건',
              str(b2.locator('#mail-list .mail-item').count()))
        check('보낸 메일' in b2.inner_text('#mail-list'), 'B 휴지통 항목에 보낸 메일 표시',
              b2.inner_text('#mail-list')[:80])
        b2.click('#mail-trash-empty')
        b2.wait_for_timeout(150)
        check(b2.inner_text('#mail-trash-empty') == '정말 비울까?', '휴지통 비우기도 한 번 더 확인',
              b2.inner_text('#mail-trash-empty'))
        shot(b2, 'local-desktop-mail-trash-empty-armed')
        b2.click('#mail-trash-empty')
        b2.wait_for_timeout(1700)
        check(b2.locator('#mail-list .mail-item').count() == 0, '휴지통 비우기 뒤 휴지통이 빔',
              str(b2.locator('#mail-list .mail-item').count()))
        rows = d1(f"SELECT COUNT(*) AS n FROM mails WHERE id = '{reply_id}'")
        count = rows[0]['results'][0]['n'] if rows and rows[0].get('results') else -1
        check(count == 0, '양쪽이 완전히 지우면 메일 행이 실제로 삭제', str(count))
        close_mail(b2)

        # ── 7. 보안: XSS · 길이 · SQL 인젝션 시도 ────────────────────
        print('\n· 보안')
        xss_subject = '<img src=x onerror=alert(1)> 제목'
        xss_body = '<script>alert(1)</script> 본문'
        res = api(a3, '/api/mail/send', 'POST', {
            'to': names['b'], 'subject': xss_subject, 'body': xss_body,
        })
        check(res['status'] == 200, '태그가 든 메일도 저장(글자로만 취급)',
              json.dumps(res, ensure_ascii=False)[:160])
        xss_id = res['data'].get('mail', {}).get('id')

        dialogs = []
        b2.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
        open_mail(b2)
        tab(b2, 'inbox')
        b2.wait_for_timeout(600)
        check(b2.locator('#mail-list .mail-item').count() == 2, 'XSS 메일이 목록에 도착',
              str(b2.locator('#mail-list .mail-item').count()))
        list_text = b2.inner_text('#mail-list')
        check('<img src=x onerror=alert(1)>' in list_text, '목록에 태그가 글자로 보임', list_text[:120])
        b2.click('#mail-list .mail-open')
        b2.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        body_text = b2.inner_text('#mail-detail-body')
        check('<script>alert(1)</script>' in body_text, '본문도 태그가 글자로만 보임', body_text[:120])
        check(not dialogs, '스크립트가 실행되지 않음(alert 없음)', str(dialogs[:2]))
        check(b2.eval_on_selector('#mail-detail-body', 'el => el.querySelectorAll("script,img").length') == 0,
              '본문에 실제 script·img 노드 없음')
        shot(b2, 'local-desktop-mail-xss-literal')
        close_mail(b2)
        drop(ctx_b2)

        res = api(a3, '/api/mail/delete', 'POST', {'id': xss_id})
        check(res['status'] == 200, '점검용 XSS 메일 정리', str(res['status']))

        long_subject = 'ㄱ' * 81
        res = api(a3, '/api/mail/send', 'POST', {'to': names['b'], 'subject': long_subject, 'body': '본문'})
        check(res['status'] == 400 and res['data'].get('error') == 'subject_long',
              '제목 81자는 400 subject_long', json.dumps(res, ensure_ascii=False)[:160])
        res = api(a3, '/api/mail/send', 'POST', {'to': names['b'], 'subject': '제목', 'body': 'ㄴ' * 2001})
        check(res['status'] == 400 and res['data'].get('error') == 'body_long',
              '본문 2001자는 400 body_long', json.dumps(res, ensure_ascii=False)[:160])
        res = api(a3, '/api/mail/send', 'POST', {'to': "' OR 1=1 --", 'subject': '제목', 'body': '본문'})
        check(res['status'] == 400 and res['data'].get('error') == 'recipient_invalid',
              'SQL 인젝션 모양 받는 사람은 400', json.dumps(res, ensure_ascii=False)[:160])
        res = api(a3, '/api/mail/send', 'POST', {'to': '@없는아이디9', 'subject': '제목', 'body': '본문'})
        check(res['status'] == 404 and res['data'].get('error') == 'recipient_not_found',
              '없는 아이디는 404 + 친절한 안내', res['data'].get('message', ''))
        rows = d1('SELECT COUNT(*) AS n FROM users')
        check(rows[0]['results'][0]['n'] >= 4, '인젝션 시도 뒤에도 users 표가 그대로',
              str(rows[0]['results'][0]['n']))
        res = api(a3, '/api/mail/inbox')
        check('no-store' in res['cache'], 'inbox 응답이 no-store', res['cache'])
        drop(ctx_a3)

        # 스팸 제한: C 가 짧은 시간에 많이 보내면 429
        ctx_c, c = open_page(names['c'])
        limited_at = None
        first_ok = None
        for i in range(12):
            res = api(c, '/api/mail/send', 'POST', {
                'to': names['b'], 'subject': f'스팸 {i}', 'body': '본문',
            })
            if res['status'] == 200 and first_ok is None:
                first_ok = i
            if res['status'] == 429:
                limited_at = i
                break
        check(first_ok == 0, 'C 의 첫 메일은 정상 발송', str(first_ok))
        check(limited_at is not None and limited_at <= 10,
              '짧은 시간에 많이 보내면 429 로 제한', f'attempt={limited_at}')
        drop(ctx_c)

        # ── 8. 보낸 메일 수정 ──────────────────────────────────
        print('\n· 보낸 메일 수정')
        ctx_a4, a4 = open_page(names['a'])
        res = api(a4, '/api/mail/send', 'POST', {
            'to': names['b'], 'subject': '수정 전 제목', 'body': '수정 전 본문입니다.',
        })
        check(res['status'] == 200, '수정 점검용 메일 발송', res['status'])
        edit_id = res['data'].get('mail', {}).get('id')
        open_mail(a4)
        tab(a4, 'sent')
        a4.wait_for_timeout(700)
        a4.click('#mail-list .mail-open')
        a4.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        check(a4.is_visible('#mail-edit-btn'), '보낸 메일 상세에 수정 버튼')
        check(not a4.is_visible('#mail-reply-btn'), '보낸 메일 상세에는 답장 없음')
        check(a4.inner_text('#mail-list .mail-when') != '', '목록에 시간 표시')
        a4.click('#mail-edit-btn')
        a4.wait_for_selector('#mail-view-edit:not([hidden])', timeout=5000)
        check(a4.input_value('#mail-edit-subject') == '수정 전 제목',
              '수정 화면에 현재 제목이 채워짐', a4.input_value('#mail-edit-subject'))
        check(a4.input_value('#mail-edit-body') == '수정 전 본문입니다.',
              '수정 화면에 현재 본문이 채워짐', a4.input_value('#mail-edit-body'))
        shot(a4, 'local-desktop-mail-edit')
        a4.fill('#mail-edit-subject', '수정한 제목')
        a4.fill('#mail-edit-body', '수정한 본문입니다.\n두 줄째.')
        a4.click('#mail-edit-submit')
        a4.wait_for_timeout(1600)
        check(a4.is_visible('#mail-view-detail'), '수정 저장 뒤 상세로 돌아옴')
        check('수정한 제목' in a4.inner_text('#mail-detail-subject'), '상세 제목이 수정한 값',
              a4.inner_text('#mail-detail-subject'))
        check('수정됨' in a4.inner_text('#mail-detail-subject'), '상세에 수정됨 표시')
        shot(a4, 'local-desktop-mail-edit-done')
        a4.click('#mail-detail-back')
        a4.wait_for_timeout(1000)
        listing = a4.inner_text('#mail-list')
        check('수정한 제목' in listing and '수정됨' in listing,
              '목록에도 수정한 제목·수정됨 표시', listing[:140])
        rows = d1(f"SELECT subject, body, updated_at FROM mails WHERE id = '{edit_id}'")
        row = rows[0]['results'][0]
        check(row['subject'] == '수정한 제목' and row['updated_at'],
              'DB 에 제목과 updated_at 기록', {'subject': row['subject'], 'updated_at': row['updated_at']})
        # 권한·한도: 길이 제한은 발송과 같고, 내가 휴지통에 넣은 메일은 고칠 수 없다
        res = api(a4, '/api/mail/edit', 'POST', {'id': edit_id, 'subject': 'ㄱ' * 81, 'body': '본문'})
        check(res['status'] == 400 and res['data'].get('error') == 'subject_long',
              '수정 제목 81자 400 subject_long', json.dumps(res, ensure_ascii=False)[:140])
        res = api(a4, '/api/mail/edit', 'POST', {'id': edit_id, 'subject': '', 'body': '본문'})
        check(res['status'] == 400 and res['data'].get('error') == 'subject_required',
              '수정 제목 빈 값 400', json.dumps(res, ensure_ascii=False)[:140])
        res = api(a4, '/api/mail/edit', 'POST', {'id': 'm_doesnotexist', 'subject': 'ㄱ', 'body': 'ㄴ'})
        check(res['status'] == 404, '없는 메일 수정 404', res['status'])
        res = api(a4, '/api/mail/trash', 'POST', {'id': edit_id})
        check(res['status'] == 200, '수정 점검 메일을 휴지통으로', res['status'])
        res = api(a4, '/api/mail/edit', 'POST', {'id': edit_id, 'subject': '휴지통 수정', 'body': '본문'})
        check(res['status'] == 404, '휴지통에 넣은 내 메일 수정 404',
              json.dumps(res, ensure_ascii=False)[:140])
        res = api(a4, '/api/mail/restore', 'POST', {'id': edit_id})
        check(res['status'] == 200, '다시 복구 200', res['status'])
        res = api(a4, '/api/mail/notices/edit', 'POST', {'id': 'n_0000', 'title': 't', 'body': 'b'})
        check(res['status'] == 403, '일반 유저 공지 수정 403', res['status'])
        drop(ctx_a4)

        ctx_b4, b4 = open_page(names['b'])
        res = api(b4, '/api/mail/edit', 'POST', {'id': edit_id, 'subject': '남의 메일', 'body': '본문'})
        check(res['status'] == 404, '받는 사람도 보낸 메일 수정 404', res['status'])
        open_mail(b4)
        b4.wait_for_timeout(700)
        received = b4.inner_text('#mail-list')
        check('수정한 제목' in received, 'B 받은 메일함에도 수정한 제목', received[:120])
        check('수정됨' in received, 'B 받은 메일함에도 수정됨 표시')
        b4.click('#mail-list .mail-open')
        b4.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        check('수정한 제목' in b4.inner_text('#mail-detail-subject'), 'B 상세 제목도 수정한 값',
              b4.inner_text('#mail-detail-subject'))
        check(not b4.is_visible('#mail-edit-btn'), '받은 메일 상세에는 수정 버튼 없음')
        check('수정한 본문입니다.' in b4.inner_text('#mail-detail-body'), '수정한 본문이 보임')
        shot(b4, 'local-desktop-mail-received-edited')
        close_mail(b4)
        drop(ctx_b4)

        # ── 9. 공지 수정(관리자) ────────────────────────────────
        print('\n· 공지 수정')
        ctx_ad2, ad = open_page(names['admin'])
        open_mail(ad)
        tab(ad, 'notices')
        ad.wait_for_timeout(800)
        target = ad.locator('#mail-list .mail-item', has_text='잇다 메일함이 열렸어요').first
        target.click()
        ad.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        check(ad.is_visible('#mail-edit-btn'), '관리자 공지 상세에 수정 버튼')
        check(ad.is_visible('#mail-delete-btn'), '관리자 공지 상세에 삭제 버튼도 그대로')
        ad.click('#mail-edit-btn')
        ad.wait_for_selector('#mail-view-notice:not([hidden])', timeout=5000)
        check(ad.inner_text('#mail-notice-heading') == '공지 수정', '공지 수정 화면 제목',
              ad.inner_text('#mail-notice-heading'))
        check(ad.input_value('#mail-notice-title') == '잇다 메일함이 열렸어요', '기존 공지 제목이 채워짐',
              ad.input_value('#mail-notice-title'))
        shot(ad, 'local-desktop-mail-notice-edit')
        ad.fill('#mail-notice-title', '잇다 메일함이 열렸어요 (안내)')
        ad.fill('#mail-notice-body', '이제 플레이어끼리 쪽지를 주고받을 수 있어요. 휴지통과 수정도 생겼어요.')
        ad.click('#mail-notice-submit')
        ad.wait_for_timeout(1700)
        check(ad.is_visible('#mail-view-list'), '공지 수정 뒤 목록으로')
        notices_text = ad.inner_text('#mail-list')
        check('잇다 메일함이 열렸어요 (안내)' in notices_text and '수정됨' in notices_text,
              '공지 목록에 수정한 제목·수정됨 표시', notices_text[:140])
        res = api(ad, '/api/mail/notices')
        edited = next((n for n in res['data'].get('notices', [])
                       if n['title'] == '잇다 메일함이 열렸어요 (안내)'), None)
        check(edited is not None and edited.get('updatedAt'),
              '수정한 공지의 updatedAt 이 내려옴', edited and edited.get('updatedAt'))
        shot(ad, 'local-desktop-mail-notices-edited')
        drop(ctx_ad2)

        # ── 10. 계정 삭제 정리 ──────────────────────────────────────
        print('\n· 계정 삭제 정리')
        ctx_d, dp = open_page(names['d'])
        res = api(dp, '/api/mail/send', 'POST', {
            'to': names['a'], 'subject': '곧 지울 계정의 메일', 'body': '정리 확인용',
        })
        check(res['status'] == 200, '탈퇴할 계정이 메일 발송', str(res['status']))
        d_mail = res['data'].get('mail', {}).get('id')
        api(dp, '/api/mail/notices/read', 'POST', {'all': True})
        me = api(dp, '/api/auth/me')
        d_id = (me['data'].get('user') or {}).get('id', '')
        res = api(dp, '/api/auth/delete', 'POST', {'password': PASSWORD})
        check(res['status'] == 200, '계정 삭제 200', json.dumps(res, ensure_ascii=False)[:160])
        rows = d1(f"SELECT COUNT(*) AS n FROM mails WHERE id = '{d_mail}'")
        check(rows[0]['results'][0]['n'] == 0, '탈퇴 계정의 메일이 정리됨',
              str(rows[0]['results'][0]['n']))
        rows = d1(f"SELECT COUNT(*) AS n FROM notice_reads WHERE user_id = '{d_id}'")
        check(d_id != '' and rows[0]['results'][0]['n'] == 0, '탈퇴 계정의 공지 읽음도 정리됨',
              str(rows[0]['results'][0]['n']))
        drop(ctx_d)

        # ── 9. 모바일 ────────────────────────────────────────────────
        print('\n· 모바일')
        ctx_b3, b3 = open_page(names['b'])
        api(b3, '/api/mail/send', 'POST', {
            'to': names['a'],
            'subject': '모바일에서도 메일함이 잘 보여요',
            'body': '핸드폰에서 메일함을 열면 목록과 본문이 한 화면 안에 들어와요.\n긴 내용도 줄바꿈 그대로 보여요.',
        })
        drop(ctx_b3)

        ctx_m, m = open_page(names['a'], width=390, height=844, mobile=True)
        m.wait_for_timeout(700)
        shot(m, 'local-mobile-home-badge')
        open_mail(m)
        m.wait_for_timeout(700)
        shot(m, 'local-mobile-mail-inbox')
        overflow = m.evaluate('() => ({scroll: document.documentElement.scrollWidth, win: window.innerWidth})')
        check(overflow['scroll'] <= overflow['win'] + 1, '모바일에서 가로 스크롤 없음', json.dumps(overflow))
        box = m.evaluate("() => { const r = document.querySelector('.mail-sheet').getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height), vw: innerWidth, vh: innerHeight}; }")
        check(box['w'] <= box['vw'] + 1 and box['h'] <= box['vh'] + 1, '모바일 메일 창이 화면 안에 들어옴',
              json.dumps(box))
        m.click('#mail-list .mail-open')
        m.wait_for_selector('#mail-view-detail:not([hidden])', timeout=5000)
        shot(m, 'local-mobile-mail-detail')
        m.wait_for_timeout(400)
        m.click('#mail-detail-back')
        m.wait_for_timeout(700)
        m.click('#mail-tabs [data-mail-tab="trash"]')
        m.wait_for_timeout(900)
        trash_text = m.inner_text('#mail-view-list')
        check('휴지통' in trash_text or '비어 있어요' in trash_text,
              '모바일에서 휴지통 탭이 열린다', trash_text[:100])
        tabs = m.evaluate("""() => {
            const bar = document.getElementById('mail-tabs');
            const btns = [...bar.querySelectorAll('[data-mail-tab]')];
            return { overflow: bar.scrollWidth - bar.clientWidth,
                     w: Math.round(bar.getBoundingClientRect().width),
                     tabs: btns.map(b => ({ key: b.dataset.mailTab,
                       clipped: b.scrollWidth > b.clientWidth + 1,
                       w: Math.round(b.getBoundingClientRect().width) })) };
        }""")
        check(tabs['overflow'] <= 1 and all(not t['clipped'] for t in tabs['tabs']),
              '모바일 네 탭(휴지통 포함)이 잘리지 않고 한 줄에 들어옴', tabs)
        shot(m, 'local-mobile-mail-trash')
        m.click('#mail-tabs [data-mail-tab="notices"]')
        m.wait_for_timeout(800)
        shot(m, 'local-mobile-mail-notices')
        m.click('#btn-mail-close')
        m.wait_for_timeout(300)
        m.click('#btn-mail')
        m.wait_for_selector('#ov-mail:not([hidden])', timeout=5000)
        m.click('#mail-tabs [data-mail-tab="inbox"]')
        m.wait_for_timeout(700)
        m.click('#mail-compose-btn')
        m.wait_for_selector('#mail-view-compose:not([hidden])', timeout=5000)
        shot(m, 'local-mobile-mail-compose')
        drop(ctx_m)

        # ── 정리: 점검 데이터 ────────────────────────────────────────
        for name in created:
            d1(f"DELETE FROM notice_reads WHERE user_id IN (SELECT id FROM users WHERE username = '{name}')")
            d1(f"DELETE FROM mails WHERE sender_id IN (SELECT id FROM users WHERE username = '{name}') OR recipient_id IN (SELECT id FROM users WHERE username = '{name}')")
            d1(f"DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username = '{name}')")
            d1(f"DELETE FROM users WHERE username = '{name}'")
        for notice in (notice1, notice2, created_notice or {}):
            if notice.get('id'):
                d1(f"DELETE FROM notice_reads WHERE notice_id = '{notice['id']}'")
                d1(f"DELETE FROM notices WHERE id = '{notice['id']}'")
        d1("DELETE FROM auth_throttle WHERE key LIKE 'register:%' OR key LIKE 'mail%'")

        browser.close()

    print(f'\n결과: {PASS} 통과 · {FAIL} 실패')
    print('스크린샷:', json.dumps(SHOTS, ensure_ascii=False, indent=1))
    return 0 if FAIL == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', action='store_true', default=True)
    ap.add_argument('--shots-dir', default='/workspace/downloads/itda/2026-11-25-mail-v2')
    ap.add_argument('--headed', action='store_true')
    args = ap.parse_args()
    global SHOT_DIR
    SHOT_DIR = args.shots_dir

    made_config = ensure_local_config()
    d1_file(os.path.join('db', 'schema.sql'))
    apply_migrations()
    proc = start_local()
    try:
        code = run(headless=not args.headed)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        if made_config:
            try:
                os.remove(os.path.join(ROOT, 'wrangler.toml'))
            except OSError:
                pass
    sys.exit(code)


if __name__ == '__main__':
    main()
