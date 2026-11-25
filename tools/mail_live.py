#!/usr/bin/env python3
"""라이브(https://itda-play.pages.dev) 메일함 점검 + 보고용 스크린샷.

- 게스트: 메일함 버튼 · 공지 탭(비어 있음) · 받은 메일에 로그인 안내 · 보호 API 401/403
- 점검용 계정 두 개를 실제 회원가입으로 만들어 A → B 메일, 읽음·답장(Re:)까지 확인하고
  끝나면 두 계정을 지워 메일까지 정리한다.
  단, 운영의 Turnstile 은 사람 확인 체크박스를 띄울 때가 있다. 이 스크립트는 그 확인을
  대신 풀지 않는다(봇 방지를 우회하지 않는다). 토큰이 저절로 오지 않으면 계정 부분만
  건너뛰고 게스트 점검만 마친다 — 로그인 흐름은 tools/mail_check.py(로컬)가 전부 덮는다.

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/mail_live.py
"""
import json
import os
import random
import string
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
URL = os.environ.get('ITDA_URL', 'https://itda-play.pages.dev')
SHOT_DIR = os.environ.get('ITDA_SHOTS', '/workspace/downloads/itda/2026-11-24-mail')
PASSWORD = 'itda-Mail-24'

PASS = 0
FAIL = 0
SHOTS = {}


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {label}')
    else:
        FAIL += 1
        print(f'  ✗ {label}' + (f' — {detail}' if detail else ''))


def shot(page, name, cls=None):
    path = os.path.join(SHOT_DIR, f'{name}.png')
    if cls:
        page.locator(cls).screenshot(path=path)
    else:
        page.screenshot(path=path, full_page=False)
    SHOTS[name] = path


def api(page, path, method='GET', body=None):
    payload = json.dumps(body) if body is not None else 'null'
    return page.evaluate(
        """async ([path, method, payload]) => {
            const res = await fetch(path, {
              method, credentials: 'same-origin',
              headers: payload === 'null' ? {accept: 'application/json'}
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
    page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=90000)
    page.wait_for_timeout(400)


def wait_turnstile(page, timeout=45):
    try:
        page.wait_for_function(
            """() => {
                const input = document.querySelector('#auth-turnstile input[name="cf-turnstile-response"]');
                return !!input && String(input.value).length > 10;
            }""",
            timeout=timeout * 1000,
        )
        return True
    except Exception:
        return False


def solve_turnstile(page, timeout=12):
    """사람 확인이 저절로 통과할 때만 기다린다(체크박스는 대신 눌러 주지 않는다)."""
    return wait_turnstile(page, timeout=timeout)


def signup_ui(page, username):
    page.click('#btn-account')
    page.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
    page.click('#auth-tabs [data-mode="signup"]')
    page.fill('#auth-username', username)
    page.fill('#auth-password', PASSWORD)
    page.fill('#auth-password2', PASSWORD)
    ok_token = solve_turnstile(page)
    page.click('#auth-submit')
    try:
        page.wait_for_function("() => document.getElementById('ov-auth').hidden === true", timeout=30000)
        return True, ok_token
    except Exception:
        return False, ok_token


def login_ui(page, username):
    page.click('#btn-account')
    page.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
    page.click('#auth-tabs [data-mode="login"]')
    page.fill('#auth-username', username)
    page.fill('#auth-password', PASSWORD)
    ok_token = solve_turnstile(page)
    page.click('#auth-submit')
    try:
        page.wait_for_function("() => document.getElementById('ov-auth').hidden === true", timeout=30000)
        return True, ok_token
    except Exception:
        return False, ok_token


def open_mail(page):
    page.click('#btn-mail')
    page.wait_for_selector('#ov-mail:not([hidden])', timeout=8000)
    page.wait_for_timeout(600)


def run(headless=True):
    os.makedirs(SHOT_DIR, exist_ok=True)
    name_a = '점검메일' + ''.join(random.choice(string.digits) for _ in range(5))
    name_b = '점검쪽지' + ''.join(random.choice(string.digits) for _ in range(5))
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=headless,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])

        def new_ctx(width=1280, height=900, mobile=False):
            return browser.new_context(viewport={'width': width, 'height': height},
                                       device_scale_factor=2 if mobile else 1,
                                       is_mobile=mobile, has_touch=mobile, locale='ko-KR')

        # ── 게스트 ──────────────────────────────────────────────
        print('· 라이브 게스트')
        ctx = new_ctx()
        guest = ctx.new_page()
        guest.on('pageerror', lambda e: errors.append(str(e)))
        guest.goto(URL, wait_until='domcontentloaded')
        wait_ready(guest)
        order = guest.eval_on_selector_all('.top-actions .top-btn', 'els => els.map(e => e.id)')
        check(order[:5] == ['btn-settings', 'btn-dict', 'btn-lab', 'btn-mail', 'btn-account'],
              '상단 버튼: 설정 · 사전 · 메일 · 계정', json.dumps(order))
        check(guest.is_visible('#btn-mail') and guest.inner_text('#btn-mail').strip() == '',
              '메일함 버튼은 아이콘만')
        shot(guest, 'live-desktop-home')
        shot(guest, 'live-desktop-top-actions', cls='.top-actions')
        res = api(guest, '/api/mail/summary')
        check(res['status'] == 200 and res['data'].get('signedIn') is False, '게스트 summary 200',
              json.dumps(res, ensure_ascii=False)[:160])
        res = api(guest, '/api/mail/inbox')
        check(res['status'] == 401, '게스트 받은 메일 401', str(res['status']))
        res = api(guest, '/api/mail/trash')
        check(res['status'] == 401, '게스트 휴지통 목록 401', str(res['status']))
        res = api(guest, '/api/mail/trash', 'POST', {'id': 'm_0000'})
        check(res['status'] == 401, '게스트 휴지통 이동 401', str(res['status']))
        res = api(guest, '/api/mail/edit', 'POST', {'id': 'm_0000', 'subject': 'x', 'body': 'y'})
        check(res['status'] == 401, '게스트 메일 수정 401', str(res['status']))
        res = api(guest, '/api/mail/notices/edit', 'POST', {'id': 'n_0000', 'title': 'x', 'body': 'y'})
        check(res['status'] == 403, '게스트 공지 수정 403', str(res['status']))
        res = api(guest, '/api/mail/notices', 'POST', {'title': 'x', 'body': 'y'})
        check(res['status'] == 403, '게스트 공지 작성 403', str(res['status']))
        open_mail(guest)
        check(guest.get_attribute('#mail-tabs [data-mail-tab="notices"]', 'aria-selected') == 'true',
              '게스트는 공지 탭부터')
        shot(guest, 'live-desktop-mail-notices')
        guest.click('#mail-tabs [data-mail-tab="inbox"]')
        guest.wait_for_timeout(900)
        check(guest.is_visible('#mail-login-btn'), '게스트 받은 메일에 로그인 버튼')
        shot(guest, 'live-desktop-mail-guest-inbox')
        guest.click('#mail-tabs [data-mail-tab="trash"]')
        guest.wait_for_timeout(900)
        check(guest.is_visible('#mail-login-btn') and '로그인' in guest.inner_text('#mail-empty-title'),
              '게스트 휴지통에도 로그인 안내')
        tabs = guest.evaluate("""() => { const bar = document.getElementById('mail-tabs');
            return { overflow: bar.scrollWidth - bar.clientWidth,
                     keys: [...bar.querySelectorAll('[data-mail-tab]')].map(b => b.dataset.mailTab) }; }""")
        check(tabs['keys'] == ['inbox', 'sent', 'trash', 'notices'] and tabs['overflow'] <= 1,
              '라이브: 네 탭(휴지통 포함)이 한 줄에', tabs)
        shot(guest, 'live-desktop-mail-guest-trash')
        ctx.close()

        # ── 두 계정 만들기 ───────────────────────────────────────
        print('· 라이브 점검 계정 (실제 회원가입)')
        ctx_a = new_ctx()
        a = ctx_a.new_page()
        a.on('pageerror', lambda e: errors.append(str(e)))
        a.goto(URL, wait_until='domcontentloaded')
        wait_ready(a)
        ok_a, tok_a = signup_ui(a, name_a)
        if not ok_a:
            print('  · Turnstile 사람 확인이 필요해 계정 부분은 건너뜁니다(게스트 점검만).')
            print(f'\n결과: {PASS} 통과 · {FAIL} 실패 (계정 부분 건너뜀)')
            print('스크린샷:', json.dumps(SHOTS, ensure_ascii=False, indent=1))
            return 0 if FAIL == 0 else 1
        check(ok_a, f'{name_a} 가입', 'turnstile=' + str(tok_a))
        me = api(a, '/api/auth/me')
        check((me['data'].get('user') or {}).get('username') == name_a, 'A 세션 확인',
              json.dumps(me, ensure_ascii=False)[:160])

        ctx_b = new_ctx()
        b = ctx_b.new_page()
        b.on('pageerror', lambda e: errors.append(str(e)))
        b.goto(URL, wait_until='domcontentloaded')
        wait_ready(b)
        ok_b, tok_b = signup_ui(b, name_b)
        check(ok_b, f'{name_b} 가입', 'turnstile=' + str(tok_b))

        if ok_a and ok_b:
            # ── A → B 메일 ──────────────────────────────────────
            print('· 라이브 메일 주고받기')
            open_mail(a)
            a.click('#mail-tabs [data-mail-tab="inbox"]')
            a.wait_for_timeout(900)
            a.click('#mail-compose-btn')
            a.wait_for_selector('#mail-view-compose:not([hidden])', timeout=8000)
            a.fill('#mail-to', '@' + name_b)
            a.fill('#mail-subject', '잇다 메일함이 열렸어요')
            a.fill('#mail-content', '안녕하세요! 이제 잇다에서도 쪽지를 주고받을 수 있어요.\n한 판 붙어요!')
            shot(a, 'live-desktop-mail-compose')
            a.click('#mail-compose-submit')
            a.wait_for_timeout(2200)
            check(a.is_visible('#mail-view-list') and
                  a.locator('#mail-tabs [data-mail-tab="sent"]').get_attribute('aria-selected') == 'true',
                  '보낸 뒤 보낸 메일 탭')
            check(a.locator('#mail-list .mail-item').count() >= 1, '보낸 메일 목록에 1통',
                  str(a.locator('#mail-list .mail-item').count()))
            shot(a, 'live-desktop-mail-sent')

            b.reload(wait_until='domcontentloaded')
            wait_ready(b)
            b.wait_for_timeout(900)
            check(b.is_visible('#mail-badge'), 'B 홈에 빨간 동그라미')
            shot(b, 'live-desktop-home-badge')
            open_mail(b)
            b.wait_for_timeout(600)
            check(b.locator('#mail-list .mail-item.unread').count() >= 1, 'B 받은 메일이 안 읽음')
            shot(b, 'live-desktop-mail-inbox')
            b.click('#mail-list .mail-open')
            b.wait_for_selector('#mail-view-detail:not([hidden])', timeout=8000)
            check(b.inner_text('#mail-detail-subject') == '잇다 메일함이 열렸어요', 'B 메일 상세 제목',
                  b.inner_text('#mail-detail-subject'))
            shot(b, 'live-desktop-mail-detail')
            b.wait_for_timeout(600)
            b.click('#mail-reply-btn')
            b.wait_for_selector('#mail-view-compose:not([hidden])', timeout=8000)
            check(b.input_value('#mail-to') == name_a and b.input_value('#mail-subject').startswith('Re: '),
                  '답장 자동 입력(받는 사람·Re:)',
                  f"{b.input_value('#mail-to')} / {b.input_value('#mail-subject')}")
            shot(b, 'live-desktop-mail-reply')
            b.fill('#mail-content', '좋아요. 지금 한 판 해요!')
            b.click('#mail-compose-submit')
            b.wait_for_timeout(2200)

            a.reload(wait_until='domcontentloaded')
            wait_ready(a)
            a.wait_for_timeout(900)
            check(a.is_visible('#mail-badge'), 'A 홈에 답장 도착 동그라미')
            open_mail(a)
            a.wait_for_timeout(600)
            check(a.locator('#mail-list .mail-item').count() >= 1, 'A 받은 메일 1통',
                  str(a.locator('#mail-list .mail-item').count()))
            a.click('#mail-list .mail-open')
            a.wait_for_selector('#mail-view-detail:not([hidden])', timeout=8000)
            check(a.inner_text('#mail-detail-subject').startswith('Re: '), 'A가 받은 답장 제목',
                  a.inner_text('#mail-detail-subject'))

            # ── 모바일 ──────────────────────────────────────────
            print('· 라이브 모바일')
            ctx_m = new_ctx(390, 844, mobile=True)
            m = ctx_m.new_page()
            m.goto(URL, wait_until='domcontentloaded')
            wait_ready(m)
            ok_m, _ = login_ui(m, name_a)
            check(ok_m, '모바일에서 A 로그인')
            m.reload(wait_until='domcontentloaded')
            wait_ready(m)
            m.wait_for_timeout(900)
            shot(m, 'live-mobile-home-badge')
            open_mail(m)
            m.wait_for_timeout(700)
            shot(m, 'live-mobile-mail-inbox')
            overflow = m.evaluate('() => ({scroll: document.documentElement.scrollWidth, win: window.innerWidth})')
            check(overflow['scroll'] <= overflow['win'] + 1, '모바일 가로 스크롤 없음', json.dumps(overflow))
            m.click('#mail-list .mail-open')
            m.wait_for_selector('#mail-view-detail:not([hidden])', timeout=8000)
            shot(m, 'live-mobile-mail-detail')
            m.click('#mail-tabs [data-mail-tab="notices"]')
            m.wait_for_timeout(900)
            shot(m, 'live-mobile-mail-notices')
            ctx_m.close()

        # ── 정리: 점검 계정 삭제(메일도 함께 지워짐) ────────────
        print('· 라이브 점검 계정 정리')
        for page, name in ((a, name_a), (b, name_b)):
            res = api(page, '/api/auth/delete', 'POST', {'password': PASSWORD})
            check(res['status'] == 200, f'{name} 계정 삭제', json.dumps(res, ensure_ascii=False)[:160])
        check(not errors, '콘솔·페이지 오류 없음', ' / '.join(errors[:3]))
        ctx_a.close()
        ctx_b.close()
        browser.close()

    print(f'\n결과: {PASS} 통과 · {FAIL} 실패')
    print('스크린샷:', json.dumps(SHOTS, ensure_ascii=False, indent=1))
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(run())
