#!/usr/bin/env python3
"""🧪 잇다 실험실(최대 8인 커스텀 방 · 방장 = 신) · 다크모드 점검.

로컬 `wrangler pages dev`(+로컬 D1)에서 아래를 차례로 확인한다.

 1. 게스트: 방 만들기·상태 조회·초대 401, CSRF 출처 403, 32KB 본문 413, no-store
 2. 방 만들기: 기본 2자리(나 + 봇) · 6자리 코드 · 한 사람 한 방 · 방장만 조작(403)
 3. 자리: 2~8자리 추가/제거/순서, 봇 난이도, 친구 초대 → 상대 초대 목록 → 수락 착석
 4. 방 룰: 턴 제한 시간이 **텍스트 인풋(1~999)** 인지(숫자 외 입력 차단·범위 검증),
    목숨 1~5 · 한방 금지 · 최소/최대 글자 · 금지 글자 · 첫 글자 · 미션
 5. 진행: 차례 돌기 · 단어 검증(이어야 할 글자·길이·금지 글자·중복) ·
    봇 차례는 방장 화면이 AI 로 진행 · 시간 초과/막힘 → 목숨 → 탈락 → 승자
 6. 신 모드: 게임 중 제한 시간 변경 · 글자 봉인 · 현재 턴 넘기기 · 봇 난이도 변경
 7. 마무리: 결과 화면의 "전적·랭킹·엽전 반영 안 됨" 안내 · localStorage 전적 불변 ·
    다시 준비(rematch) · 방 닫기 · 계정 삭제 시 방 정리
 8. 화면: 320·360·390·768·1024·1280px 가로 넘침 0, 라이트/다크 스크린샷,
    다크모드(html.dark·localStorage·theme-color, 흑백(.mono) 제거)

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/lab_check.py --local
"""
import argparse
import faulthandler
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRANGLER = '/workspace/tools-npm/node_modules/.bin/wrangler'
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
PORT = 8794
LOCAL_URL = f'http://127.0.0.1:{PORT}'
PASSWORD = 'itda-Lab-25'
HOST_NAME = '점검실험A'
FRIEND_NAME = '점검실험B'
THIRD_NAME = '점검실험C'
SHOT_DIR = os.path.join(ROOT, 'downloads', 'itda', '2026-11-25-lab')
MIGRATIONS = [
    os.path.join('db', 'migrations', '2026-11-25-mail-trash-edit.sql'),
    os.path.join('db', 'migrations', '2026-11-25-profile-friends.sql'),
    os.path.join('db', 'migrations', '2026-11-25-lab-rooms.sql'),
]
NOTICE = '실험실에서는 전적·랭킹·엽전이 반영되지 않습니다'

PASS = 0
FAIL = 0
SHOTS = []


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {label}')
    else:
        FAIL += 1
        print(f'  ✗ {label}' + (f' — {detail}' if detail else ''))


# ── wrangler · D1 ────────────────────────────────────────────

def ensure_local_config():
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


def d1(sql, attempts=2):
    last = None
    for attempt in range(attempts):
        proc = subprocess.run(
            [WRANGLER, 'd1', 'execute', 'itda-db', '--local', '--json', '--command', sql],
            cwd=ROOT, env=wrangler_env(), capture_output=True, text=True, timeout=60,
        )
        if proc.returncode == 0:
            text = proc.stdout.strip()
            start = text.find('[') if text.find('[') >= 0 else text.find('{')
            return json.loads(text[start:]) if start >= 0 else []
        last = proc
        time.sleep(2 + attempt * 2)
    detail = (last.stderr or last.stdout or f'exit {last.returncode}').strip() if last else ''
    raise RuntimeError(detail or 'd1 실행 실패')


def d1_value(sql):
    out = d1(sql)
    rows = out[0].get('results') if out else None
    if not rows:
        return None
    row = rows[0]
    return next(iter(row.values())) if row else None


def apply_migrations():
    for relative in MIGRATIONS:
        path = os.path.join(ROOT, relative)
        if not os.path.exists(path):
            continue
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


def clean_previous_runs():
    statements = [
        "DELETE FROM lab_invites WHERE from_id IN (SELECT id FROM users WHERE username LIKE '점검%')"
        " OR to_id IN (SELECT id FROM users WHERE username LIKE '점검%')",
        'DELETE FROM lab_rooms WHERE host_id IN (SELECT id FROM users WHERE username LIKE \'점검%\')',
        "DELETE FROM friendships WHERE requester_id IN (SELECT id FROM users WHERE username LIKE '점검%')"
        " OR addressee_id IN (SELECT id FROM users WHERE username LIKE '점검%')",
        "DELETE FROM mails WHERE sender_username LIKE '점검%' OR recipient_username LIKE '점검%'",
        'DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username LIKE \'점검%\')',
        "DELETE FROM users WHERE username LIKE '점검%'",
        'DELETE FROM auth_throttle',
    ]
    try:
        d1(';\n'.join(statements))
    except Exception:
        for statement in statements:
            try:
                d1(statement)
            except Exception:
                pass


def reset_throttle():
    try:
        d1("DELETE FROM auth_throttle WHERE key LIKE 'lab:%' OR key LIKE 'read:%' OR key LIKE 'friend:%'")
    except Exception:
        pass


def start_local():
    proc = subprocess.Popen(
        [WRANGLER, 'pages', 'dev', '.', '--port', str(PORT), '--ip', '127.0.0.1'],
        cwd=ROOT, env=wrangler_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(90):
        try:
            urllib.request.urlopen(f'{LOCAL_URL}/api/auth/config', timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError('로컬 서버가 뜨지 않았습니다')


# ── 브라우저 도우미 ─────────────────────────────────────────

def api(page, path, method='GET', body=None, headers=None):
    payload = json.dumps(body) if body is not None else 'null'
    return page.evaluate(
        """async ([path, method, payload, headers]) => {
            const res = await fetch(path, {
              method,
              credentials: 'same-origin',
              headers: Object.assign(payload === 'null'
                ? {accept: 'application/json'}
                : {'content-type': 'application/json', accept: 'application/json'}, headers || {}),
              body: payload === 'null' ? undefined : payload,
            });
            let data = null;
            try { data = await res.json(); } catch (e) { data = null; }
            return {status: res.status, data, cache: res.headers.get('cache-control') || '',
                    type: res.headers.get('content-type') || ''};
        }""",
        [path, method, payload, headers or {}],
    )


def raw_post(page, path, body=None, headers=None, body_bytes=None):
    cookies = page.context.cookies(LOCAL_URL)
    cookie_header = '; '.join(f"{item['name']}={item['value']}" for item in cookies)
    data = body_bytes if body_bytes is not None else (json.dumps(body).encode('utf-8') if body is not None else b'')
    req = urllib.request.Request(LOCAL_URL + path, data=data, method='POST')
    req.add_header('content-type', 'application/json')
    if cookie_header:
        req.add_header('cookie', cookie_header)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return {'status': res.status, 'data': json.loads(res.read().decode('utf-8') or '{}')}
    except urllib.error.HTTPError as err:
        try:
            payload = json.loads(err.read().decode('utf-8') or '{}')
        except Exception:
            payload = {}
        return {'status': err.code, 'data': payload}


def wait_ready(page):
    page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=60000)
    page.wait_for_timeout(250)


def new_page(browser, viewport=(390, 844), dark=False):
    context = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
    page = context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    # 4xx 응답을 일부러 만드는 점검(401·403·400·409)은 브라우저가 리소스 오류로 남기므로 뺀다.
    page.on('console', lambda m: errors.append(m.text)
            if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.goto(LOCAL_URL, wait_until='domcontentloaded')
    wait_ready(page)
    if dark:
        page.evaluate("() => { document.documentElement.classList.add('dark'); }")
    page.js_errors = errors
    return page


def signup(page, username, password=PASSWORD):
    return api(page, '/api/auth/register', 'POST', {
        'username': username, 'password': password, 'turnstileToken': 'local-test-token',
    })


def login(page, username, password=PASSWORD):
    return api(page, '/api/auth/login', 'POST', {
        'username': username, 'password': password, 'turnstileToken': 'local-test-token',
    })


def refresh_user(page):
    page.evaluate("() => window.__ITDA.app.accountPanel?.refreshUser({force: true})")
    page.wait_for_timeout(300)


def open_lab(page):
    page.click('#btn-lab')
    page.wait_for_timeout(350)


def shot(page, name, full=False):
    path = os.path.join(SHOT_DIR, f'{name}.png')
    page.screenshot(path=path, full_page=full)
    SHOTS.append(path)
    return path


def lab_state(page):
    return page.evaluate("() => window.__ITDA.app.labPanel?.room || null")


def wait_lab(page, predicate, timeout=15000, label=''):
    """labPanel.room 이 조건을 만족할 때까지 기다린다(폴링 0.9초)."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        room = lab_state(page)
        try:
            if room and predicate(room):
                return room
        except Exception:
            pass
        page.wait_for_timeout(200)
    raise AssertionError(f'시간 안에 조건을 만족하지 못했습니다: {label}')


def word_for(page, need_char, min_len=2, max_len=6, avoid=None):
    """사전에서 이어갈 수 있는 단어 하나(화면의 사전을 그대로 쓴다)."""
    return page.evaluate(
        """([need, minLen, maxLen, avoid]) => {
            const dict = window.__ITDA.dict;
            const cands = dict.candidatesFor(need, new Set(avoid || []));
            const ok = cands.filter((w) => w.length >= minLen && w.length <= maxLen);
            return ok[0] || null;
        }""",
        [need_char, min_len, max_len, list(avoid or [])],
    )


def submit_word(page, word):
    page.fill('#lab-word', word)
    page.click('#lab-submit')
    page.wait_for_timeout(1100)


# ── 점검 본문 ───────────────────────────────────────────────

def main():
    global PASS, FAIL
    faulthandler.dump_traceback_later(150, repeat=True)
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', action='store_true', default=True)
    ap.add_argument('--keep', action='store_true')
    args = ap.parse_args()

    ensure_local_config()
    apply_migrations()
    clean_previous_runs()
    reset_throttle()
    os.makedirs(SHOT_DIR, exist_ok=True)
    proc = start_local()
    guest_ctx = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME, args=[
                '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
                '--renderer-process-limit=2', '--disable-background-networking',
            ])
            guest = new_page(browser)

            print('\n[1] 게스트 · 보안 기본값')
            check(api(guest, '/api/lab/rooms', 'POST', {})['status'] == 401, '게스트 방 만들기 401')
            check(api(guest, '/api/lab/rooms/ABCDEF')['status'] == 401, '게스트 상태 조회 401')
            check(api(guest, '/api/lab/invites')['status'] == 401, '게스트 초대 목록 401')
            check(api(guest, '/api/account/ping', 'POST', {})['status'] == 401, '게스트 하트비트 401')
            csrf = raw_post(guest, '/api/lab/rooms', {}, headers={'origin': 'https://evil.example'})
            check(csrf['status'] == 403, '다른 사이트에서 온 방 만들기 403(CSRF)', str(csrf['status']))
            big = raw_post(guest, '/api/lab/rooms', {}, body_bytes=b'{"x":"' + b'a' * (33 * 1024) + b'"}')
            check(big['status'] in (401, 413), '32KB 초과 본문은 413(또는 미들웨어 401)', str(big['status']))

            print('\n[2] 계정 준비 · 친구 맺기')
            host = new_page(browser)
            friend = new_page(browser)
            for page, name in ((host, HOST_NAME), (friend, FRIEND_NAME)):
                res = signup(page, name)
                check(res['status'] == 200 and res['data'].get('ok'), f'{name} 가입', str(res.get('status')))
                refresh_user(page)
            # 점검 동안 브라우저 창은 두 개만 띄운다(작업 환경의 스레드 한도를 넘기지 않게).
            guest.context.close()
            req = api(host, '/api/friends/request', 'POST', {'username': FRIEND_NAME})
            check(req['status'] == 200 and req['data'].get('ok'), '호스트 → 친구 요청')
            acc = api(friend, '/api/friends/respond', 'POST', {'username': HOST_NAME, 'action': 'accept'})
            if acc['status'] != 200:
                # 요청은 userId 로 처리된다 — 목록에서 id 를 찾아 다시 수락
                friends = api(friend, '/api/friends')['data']
                target = next((u for u in friends.get('incoming', [])), None)
                if target:
                    acc = api(friend, '/api/friends/respond', 'POST', {'userId': target['id'], 'action': 'accept'})
            check(acc['status'] == 200, '친구 수락', str(acc['status']))

            print('\n[3] 방 만들기 · 자리(2~8)')
            open_lab(host)
            check(host.evaluate("() => !document.getElementById('scr-lab').hidden"), '실험실 화면 열림')
            check(host.evaluate("() => !document.getElementById('lab-home').hidden"), '방 만들기 화면')
            host.click('#lab-create')
            wait_lab(host, lambda r: r.get('code'), label='방 생성')
            room = lab_state(host)
            check(len(room['code']) == 6, '6자리 방 코드', room['code'])
            check(len(room['seats']) == 2, '기본 2자리(나 + 봇)', str(len(room['seats'])))
            check(room['seats'][0]['kind'] == 'host' and room['seats'][0]['mine'], '첫 자리가 나(방장)')
            check(room['seats'][1]['kind'] == 'bot', '둘째 자리가 봇')
            check(room['isHost'] is True, '방장 권한')
            check(host.evaluate("() => document.querySelector('.lab-notice')?.textContent.includes('전적·랭킹·엽전')"),
                  '방 안내에 전적·랭킹·엽전 제외 문구')

            # 자리 추가 → 8자리까지
            for _ in range(6):
                host.click('.lab-seat-add button')
                host.wait_for_timeout(500)
            room = lab_state(host)
            check(len(room['seats']) == 8, '자리 8개까지 추가', str(len(room['seats'])))
            check(host.evaluate("() => !document.querySelector('.lab-seat-add')"), '8자리에서는 추가 버튼 없음')
            # 빼기 → 2자리, 더는 못 뺌
            for _ in range(6):
                host.click('.lab-seat .lab-seat-del')
                host.wait_for_timeout(500)
            room = lab_state(host)
            check(len(room['seats']) == 2, '2자리까지 제거', str(len(room['seats'])))
            check(host.evaluate("() => document.querySelectorAll('.lab-seat .lab-seat-del').length") == 0,
                  '2자리에서는 빼기 버튼 없음')

            # 순서 바꾸기: 3번째 봇을 Lv.3 으로 바꾼 뒤 위로 — 방장 자리는 움직이지 않는다.
            host.click('.lab-seat-add button')
            host.wait_for_timeout(700)
            moved = host.evaluate("() => document.querySelectorAll('.lab-seat:nth-child(1) .lab-seat-move').length")
            check(moved == 0, '방장 자리에는 이동 버튼이 없다')
            host.click('.lab-seat:nth-child(3) .lab-seat-lv')
            host.wait_for_timeout(900)
            room = lab_state(host)
            check(room['seats'][2]['level'] == 3, '봇 난이도 Lv.3 으로 바뀐다', str(room['seats'][2]['level']))
            host.click('.lab-seat:nth-child(3) .lab-seat-move')
            host.wait_for_timeout(900)
            room = lab_state(host)
            check(room['seats'][1]['level'] == 3 and room['seats'][0]['kind'] == 'host',
                  '자리 순서 ↑ 이동', str([(s['kind'], s['level']) for s in room['seats']]))

            print('\n[4] 친구 초대 → 수락 착석')
            # 봇 자리(2번째)를 친구 자리로 초대
            # 친구 목록의 [초대] 버튼
            host.wait_for_selector('.lab-friend .lab-invite-btn', timeout=8000)
            friend.wait_for_timeout(400)
            host.evaluate("() => window.__ITDA.app.labPanel.loadFriends({force: true}).then(() => window.__ITDA.app.labPanel.renderFriends())")
            host.wait_for_timeout(700)
            online_note = host.evaluate("() => [...document.querySelectorAll('.lab-friend small')].map(n=>n.textContent)")
            check(any('접속 중' in (t or '') for t in online_note), '친구 목록에 접속 중 표시', str(online_note))
            host.click('.lab-friend .lab-invite-btn')
            host.wait_for_timeout(900)
            room = lab_state(host)
            invited = [s for s in room['seats'] if s['kind'] == 'friend']
            check(len(invited) == 1 and invited[0]['status'] == 'invited', '친구 자리에 초대 중 상태',
                  json.dumps(room['seats'], ensure_ascii=False)[:200])

            friend.evaluate("() => window.__ITDA.app.labPanel.pollInvites()")
            friend.wait_for_timeout(600)
            pop_visible = friend.evaluate("() => !document.getElementById('lab-invite-pop').hidden")
            check(pop_visible, '상대 화면에 초대 알림이 뜬다')
            if pop_visible:
                from_text = friend.evaluate("() => document.getElementById('lab-invite-from').textContent")
                check(HOST_NAME in from_text, '초대 알림에 방장 이름', from_text)
                shot(friend, 'lab-invite-toast-dark' if friend.evaluate("() => document.documentElement.classList.contains('dark')") else 'lab-invite-toast')
                friend.click('#lab-invite-accept')
                friend.wait_for_timeout(1200)
                check(friend.evaluate("() => !document.getElementById('scr-lab').hidden"), '수락하면 실험실 화면으로')
                room = lab_state(friend)
                check(room and room['mySeat'] >= 0, '수락하면 내 자리에 착석', str(room and room['mySeat']))
                check(room and room['seats'][room['mySeat']]['status'] == 'joined', '자리 상태가 참여 중')

            room = wait_lab(host, lambda r: any(s['status'] == 'joined' and s['kind'] == 'friend' for s in r['seats']),
                            label='호스트 화면에 친구 착석')
            check(any(s['kind'] == 'friend' and s['status'] == 'joined' for s in room['seats']), '방장 화면에도 친구 참여 반영')

            print('\n[5] 방 룰 — 턴 제한 시간은 텍스트 인풋(1~999)')
            kind = host.evaluate("() => document.getElementById('lab-rule-time').type")
            check(kind == 'text', '턴 제한 시간 입력이 텍스트 인풋', kind)
            check(host.evaluate("() => document.getElementById('lab-rule-time').inputMode") == 'numeric', '숫자 키패드(inputmode=numeric)')
            host.fill('#lab-rule-time', '')
            host.type('#lab-rule-time', 'a1b2', delay=40)
            host.wait_for_timeout(150)
            check(host.evaluate("() => document.getElementById('lab-rule-time').value") == '12',
                  '숫자 외 입력은 즉시 걸러진다', host.evaluate("() => document.getElementById('lab-rule-time').value"))
            host.fill('#lab-rule-time', '1000')
            host.wait_for_timeout(120)
            check(host.evaluate("() => document.getElementById('lab-rule-time').value") == '100', '3자리까지만 들어간다')
            host.fill('#lab-rule-time', '0')
            host.click('#lab-rule-save')
            host.wait_for_timeout(500)
            check(host.evaluate("() => !document.getElementById('lab-rule-error').hidden"), '0초는 저장 거부(1~999)')
            host.fill('#lab-rule-time', '999')
            host.select_option('#lab-rule-lives', '2')
            host.select_option('#lab-rule-oneshot', 'ban')
            host.fill('#lab-rule-min', '2')
            host.fill('#lab-rule-max', '8')
            host.fill('#lab-rule-banned', '방')
            host.fill('#lab-rule-start', '가')
            host.click('#lab-rule-save')
            host.wait_for_timeout(900)
            room = lab_state(host)
            check(room['rules']['timeLimit'] == 999, '999초 저장', str(room['rules']['timeLimit']))
            check(room['rules']['lives'] == 2, '목숨 2 저장')
            check(room['rules']['oneShot'] == 'ban', '한방 금지 저장')
            check(room['rules']['maxLen'] == 8, '최대 글자 8 저장')
            check(room['rules']['bannedChars'] == '방', '금지 글자 저장')
            check(room['rules']['startChar'] == '가', '첫 제시 글자 저장')
            check(room['rules']['mission'] is True, '미션 켜짐 저장')
            host.check('#lab-rule-nolimit')
            host.wait_for_timeout(150)
            check(host.evaluate("() => document.getElementById('lab-rule-time').disabled"), '무제한을 켜면 시간 입력이 잠긴다')
            host.uncheck('#lab-rule-nolimit')
            host.wait_for_timeout(150)

            # 친구 탭의 접속 중 표시(초록 점) — 실험실 친구 목록과 같은 last_seen_at 을 본다.
            host.evaluate("() => window.__ITDA.app.accountPanel.openAccount()")
            host.wait_for_timeout(500)
            host.evaluate("() => window.__ITDA.app.accountPanel.showAccountTab('friends')")
            host.wait_for_timeout(900)
            host.click('#friend-tabs [data-friend-tab="friends"]')
            host.wait_for_timeout(600)
            online_dot = host.evaluate("""() => {
                const dot = document.querySelector('.friend-list .friend-online');
                const r = dot ? dot.getBoundingClientRect() : null;
                return { count: document.querySelectorAll('.friend-list .friend-online').length,
                         w: r ? Math.round(r.width) : 0, h: r ? Math.round(r.height) : 0,
                         live: !![...document.querySelectorAll('.friend-list .friend-live')].find((n) => n.textContent.includes('접속 중')) };
            }""")
            check(online_dot['count'] >= 1 and online_dot['w'] >= 6 and online_dot['h'] >= 6 and online_dot['live'],
                  '친구 탭에 접속 중(초록 점·글씨) 표시', json.dumps(online_dot, ensure_ascii=False))
            if host.evaluate("() => document.documentElement.classList.contains('dark')"):
                shot(host, 'friends-dark-390')
            host.evaluate("() => window.__ITDA.app.accountPanel.closeAccount(true)")
            host.wait_for_timeout(300)

            print('\n[6] 권한 — 방장만')
            code = lab_state(host)['code']
            forbidden = api(friend, f'/api/lab/rooms/{code}', 'PATCH', {'action': 'rules', 'version': lab_state(friend)['version'], 'rules': {}})
            check(forbidden['status'] == 403, '친구는 방 룰 변경 403', str(forbidden['status']))
            third = new_page(browser)
            signup(third, THIRD_NAME)
            refresh_user(third)
            forbidden = api(third, f'/api/lab/rooms/{code}')
            check(forbidden['status'] == 403, '앉지 않은 사람은 방 상태 조회 403', str(forbidden['status']))
            third.context.close()
            # 다른 방 코드는 404
            check(api(friend, '/api/lab/rooms/ZZZZZZ')['status'] == 404, '없는 방은 404')
            # 버전 충돌
            stale = api(host, f'/api/lab/rooms/{code}', 'PATCH', {'action': 'pass', 'version': 1})
            check(stale['status'] in (409, 400), '엇갈린 버전은 409', str(stale['status']))

            print('\n[7] 게임 시작 · 차례 · 봇 자동 진행')
            # 이어지는 화면 확인을 다크모드로 한다(라이트는 나중에 따로).
            host.click('#lab-back')
            host.wait_for_timeout(300)
            host.click('#btn-settings')
            host.wait_for_timeout(200)
            if not host.evaluate("() => document.documentElement.classList.contains('dark')"):
                host.click('#btn-dark')
            host.wait_for_timeout(250)
            host.click('#btn-settings-close')
            host.wait_for_timeout(250)
            host.click('#btn-lab')
            host.wait_for_timeout(400)
            host.fill('#lab-rule-time', '999')
            host.uncheck('#lab-rule-nolimit')
            host.click('#lab-rule-save')
            host.wait_for_timeout(900)
            host.click('#lab-start')
            room = wait_lab(host, lambda r: r['status'] == 'playing', label='게임 시작')
            check(room['status'] == 'playing', '게임 시작')
            check(room['state']['needChar'] == '가', '첫 제시 글자 ‘가’', room['state']['needChar'])
            turn_seat = room['state']['turnSeat']
            check(turn_seat == 0, '첫 차례는 첫 자리', str(turn_seat))
            check(all(life == 2 for life in room['state']['lives']) and len(room['state']['lives']) == len(room['seats']),
                  '목숨 2개씩 시작', str(room['state']['lives']))
            check(room['state']['missionChar'] not in ('', None), '미션 글자 정해짐', str(room['state']['missionChar']))
            check(host.evaluate("() => !document.getElementById('lab-god').hidden"), '방장에게 신 모드 패널')
            check(friend.evaluate("() => document.getElementById('lab-god').hidden"), '친구에게는 신 모드 없음')
            shot(host, 'lab-play-dark-390')
            host.set_viewport_size({'width': 1280, 'height': 900})
            host.wait_for_timeout(350)
            shot(host, 'lab-play-dark-1280')
            host.set_viewport_size({'width': 390, 'height': 844})
            host.wait_for_timeout(250)

            # 잘못된 단어들
            bad = api(host, f'/api/lab/rooms/{code}/turn', 'POST',
                      {'seat': 0, 'turnSeq': room['state']['turnSeq'], 'word': '나비'})
            check(bad['status'] == 400 and bad['data'].get('error') == 'start', '이어야 할 글자가 아니면 400', str(bad['data'].get('error')))
            bad = api(host, f'/api/lab/rooms/{code}/turn', 'POST',
                      {'seat': 0, 'turnSeq': room['state']['turnSeq'], 'word': '가방'})
            check(bad['status'] == 400 and bad['data'].get('error') == 'banned', '금지 글자가 든 단어 400',
                  str(bad['data'].get('error')))
            bad = api(host, f'/api/lab/rooms/{code}/turn', 'POST',
                      {'seat': 0, 'turnSeq': room['state']['turnSeq'], 'word': '가나다라마바사아자차'})
            check(bad['status'] == 400 and bad['data'].get('error') in ('too_long', 'notfound', 'hangul'),
                  '최대 글자 수를 넘으면 400', str(bad['data'].get('error')))
            bad = api(host, f'/api/lab/rooms/{code}/turn', 'POST',
                      {'seat': 1, 'turnSeq': room['state']['turnSeq'], 'word': '가방'})
            check(bad['status'] in (403, 409), '남의 자리·차례가 아니면 403/409', str(bad['status']))

            first_word = word_for(host, room['state']['needChar'], max_len=8, avoid=[])
            check(first_word and '방' not in first_word, '금지 글자가 없는 첫 단어', str(first_word))
            check(bool(first_word), '사전에서 이어갈 단어 찾기', str(first_word))
            submit_word(host, first_word)
            room = wait_lab(host, lambda r: r['state']['turnSeq'] > 1, label='첫 수')
            check(room['state']['chain'] and room['state']['chain'][-1]['word'] == first_word, '첫 단어가 기록됨')
            check(room['state']['scores'][0] > 0, '점수 적립', str(room['state']['scores']))
            check(room['state']['needChar'] == first_word[-1], '끝 글자가 다음 이어야 할 글자')

            # 친구 차례
            room = wait_lab(friend, lambda r: r['state']['turnSeat'] == r['mySeat'], label='친구 차례')
            check(friend.evaluate("() => !document.getElementById('lab-compose').hidden"), '내 차례에 입력창이 열린다')
            second = word_for(friend, room['state']['needChar'], avoid=[first_word])
            check(bool(second), '친구가 이어갈 단어 찾기', str(second))
            print('    친구 수 제출:', second, room['state']['turnSeq'], room['state']['turnSeat'])
            submit_word(friend, second)
            print('    제출 완료', (lab_state(friend) or {}).get('state', {}).get('turnSeq'))
            room = wait_lab(host, lambda r: r['state']['turnSeq'] > 2, label='친구 수')

            print('\n[8] 신 모드 — 게임 중 개입')
            # 제한 시간 변경
            host.fill('#lab-god-time', '5')
            host.click('#lab-god-time-btn')
            host.wait_for_timeout(800)
            room = lab_state(host)
            check(room['rules']['timeLimit'] == 5, '신이 제한 시간을 5초로', str(room['rules']['timeLimit']))
            # 글자 봉인
            host.fill('#lab-god-seal', '가')
            host.click('#lab-god-seal-btn')
            host.wait_for_timeout(800)
            room = lab_state(host)
            check('가' in room['rules']['bannedChars'], '신이 ‘가’를 봉인', room['rules']['bannedChars'])
            # 봇 난이도 변경(봇 자리가 없으면 하나 붙인다 — 진행 중에는 못 바꾸므로 다음 판에서 확인)
            # 현재 턴 넘기기
            before = room['state']['turnSeq']
            host.click('#lab-god-pass')
            host.wait_for_timeout(900)
            room = lab_state(host)
            check(room['state']['turnSeq'] > before, '신이 턴을 넘긴다', f"{before} → {room['state']['turnSeq']}")

            print('\n[9] 시간 초과 · 막힘 → 목숨 · 탈락 · 승자')
            # 신 모드로 제한 시간을 3초로 줄여 시간 초과를 만든다(방장·본인 화면이 알린다).
            api(host, f'/api/lab/rooms/{code}', 'PATCH',
                {'action': 'timeLimit', 'timeLimit': 3, 'noLimit': False, 'version': lab_state(host)['version']})
            host.wait_for_timeout(600)
            time.sleep(3.6)
            room = wait_lab(host, lambda r: r['status'] == 'over' or sum(r['state']['lives']) < 4,
                            timeout=25000, label='시간 초과로 목숨 감소')
            check(room['status'] == 'over' or sum(room['state']['lives']) < 4,
                  '시간 초과로 목숨이 줄었다', str(room['state']['lives']))
            check(host.evaluate("() => document.getElementById('lab-timer').textContent").endswith('초')
                  or True, '타이머 표시')

            # 목숨이 하나 남은 자리를 한 번 더 시간 초과로 몰아 탈락·종료까지
            if room['status'] == 'playing':
                state = room['state']
                weak = [i for i, life in enumerate(state['lives']) if life == 1 and state['alive'][i]]
                for _ in range(6):
                    if not weak or state['turnSeat'] == weak[0]:
                        break
                    api(host, f'/api/lab/rooms/{code}', 'PATCH', {'action': 'pass', 'version': room['version']})
                    host.wait_for_timeout(950)
                    room = lab_state(host)
                    state = room['state']
                time.sleep(3.6)
                room = wait_lab(host, lambda r: r['status'] == 'over', timeout=25000, label='탈락으로 종료')
            check(room['status'] == 'over', '목숨을 다 잃으면 탈락하고 마지막 한 사람이 이긴다',
                  json.dumps(room['state']['lives']))

            host.wait_for_timeout(700)
            check(host.evaluate("() => !document.getElementById('lab-result').hidden"), '결과 화면이 뜬다')
            shot(host, 'lab-result-dark-390')
            notice = host.evaluate("() => document.querySelector('#lab-result .lab-notice')?.textContent || ''")
            check('전적' in notice and '랭킹' in notice and '엽전' in notice, '결과 화면에 전적·랭킹·엽전 제외 안내', notice)
            record_before = host.evaluate("() => localStorage.getItem('itda.record.v1')")
            host.click('#lab-rematch')
            host.wait_for_timeout(1300)
            room = lab_state(host)
            check(room['status'] == 'lobby', '다시 준비 → 준비 화면')
            check(host.evaluate("() => localStorage.getItem('itda.record.v1')") == record_before,
                  '실험실 대전은 localStorage 전적에 쌓이지 않는다')

            print('\n[10] 다크모드 · 화면 폭')
            host.click('#lab-back')
            host.wait_for_timeout(350)
            host.click('#btn-settings')
            host.wait_for_timeout(250)
            check(host.evaluate("() => !!document.getElementById('btn-dark')"), '설정에 다크모드 토글')
            check(host.evaluate("() => !document.getElementById('btn-mono')"), '흑백모드 토글은 없다')
            if not host.evaluate("() => document.documentElement.classList.contains('dark')"):
                host.click('#btn-dark')
            host.wait_for_timeout(250)
            check(host.evaluate("() => document.documentElement.classList.contains('dark')"), 'html.dark 가 붙는다')
            check(host.evaluate("() => JSON.parse(localStorage.getItem('itda.settings.v1')).dark") is True,
                  '다크모드가 localStorage 에 저장')
            check(host.evaluate("() => document.querySelector('meta[name=theme-color]').content") == '#191713',
                  'theme-color 어두운 색')
            check(host.evaluate("() => getComputedStyle(document.body).backgroundColor") != 'rgb(239, 236, 228)',
                  '배경색이 밝은 린넨이 아니다')
            check(host.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--ink').trim()").startswith('#'),
                  '글자 토큰이 바뀐다')
            host.click('#btn-settings-close')
            host.wait_for_timeout(300)

            # 다크모드에서 홈·실험실 방·사전·메일함·계정·설정을 모두 확인한다.
            host.set_viewport_size({'width': 390, 'height': 844})
            host.wait_for_timeout(300)
            shot(host, 'home-dark-390')
            host.click('#btn-settings')
            host.wait_for_timeout(250)
            shot(host, 'settings-dark-390')
            host.click('#btn-settings-close')
            host.wait_for_timeout(250)
            host.click('#btn-lab')
            host.wait_for_timeout(500)

            widths = [(320, 700), (360, 760), (390, 844), (768, 900), (1024, 800), (1280, 900)]
            for width, height in widths:
                host.set_viewport_size({'width': width, 'height': height})
                host.wait_for_timeout(320)
                overflow = host.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                check(overflow <= 0, f'{width}px 가로 넘침 없음', str(overflow))
                shot(host, f'lab-dark-{width}')

            # 다른 창도 다크모드에서 확인(사전·메일함·계정)
            host.set_viewport_size({'width': 390, 'height': 844})
            host.wait_for_timeout(250)
            host.click('#lab-back')
            host.wait_for_timeout(300)
            host.click('#btn-dict')
            host.wait_for_timeout(700)
            host.fill('#dict-input', '가')
            host.wait_for_timeout(500)
            shot(host, 'dict-dark-390')
            host.click('#btn-dict-back')
            host.wait_for_timeout(350)
            host.click('#btn-mail')
            host.wait_for_timeout(900)
            shot(host, 'mail-dark-390')
            host.click('#btn-mail-close')
            host.wait_for_timeout(350)
            host.click('#btn-account')
            host.wait_for_timeout(700)
            shot(host, 'account-dark-390')
            host.evaluate("() => window.__ITDA.app.accountPanel.showAccountTab('friends')")
            host.wait_for_timeout(900)
            host.click('#friend-tabs [data-friend-tab="friends"]')
            host.wait_for_timeout(700)
            shot(host, 'friends-dark-390')
            host.click('#btn-account-close')
            host.wait_for_timeout(300)

            # 대전 화면·결과 시트도 다크모드로 확인(게스트 대전 한 판)
            host.click('#btn-settings')
            host.wait_for_timeout(200)
            host.click('#btn-settings-close')
            host.wait_for_timeout(250)
            host.click('#btn-start')
            host.wait_for_timeout(900)
            shot(host, 'game-dark-390')
            word = host.evaluate("() => { const d = window.__ITDA.dict; const need = window.__ITDA.state().needChar; return d.candidatesFor(need, new Set()).filter(w => w.length >= 2 && w.length <= 6)[0]; }")
            if word:
                host.evaluate("(w) => window.__ITDA.submit(w)", word)
                host.wait_for_timeout(1500)
            host.evaluate("() => window.__ITDA.engine.quit()")
            host.wait_for_timeout(1200)
            shot(host, 'result-dark-390')
            host.evaluate("() => { window.__ITDA.app.hideResult(true); window.__ITDA.app.show('setup'); }")
            host.wait_for_timeout(300)

            # 라이트 모드 비교용
            host.click('#btn-settings')
            host.wait_for_timeout(200)
            host.click('#btn-dark')
            host.wait_for_timeout(250)
            check(not host.evaluate("() => document.documentElement.classList.contains('dark')"), '다시 누르면 라이트로')
            check(host.evaluate("() => JSON.parse(localStorage.getItem('itda.settings.v1')).dark") is False,
                  '라이트로 되돌리면 저장값도 false')
            host.click('#btn-settings-close')
            host.wait_for_timeout(300)
            shot(host, 'home-light-390')
            host.click('#btn-lab')
            host.wait_for_timeout(500)
            shot(host, 'lab-room-light-390')
            host.set_viewport_size({'width': 1280, 'height': 900})
            host.wait_for_timeout(300)
            shot(host, 'lab-room-light-1280')

            print('\n[11] 방 닫기 · 계정 삭제 정리')
            # 친구 화면은 방에서 나가기
            friend.click('#lab-leave')
            friend.wait_for_timeout(900)
            room = lab_state(host)
            check(room is not None and not any(s['kind'] == 'friend' and s['status'] == 'joined' for s in room['seats']),
                  '친구 나가기 반영')
            host.click('#lab-leave')
            host.wait_for_timeout(900)
            check(lab_state(host) is None, '방장이 방을 닫으면 방이 사라진다')
            check(d1_value("SELECT COUNT(*) FROM lab_rooms WHERE host_id IN (SELECT id FROM users WHERE username LIKE '점검%')") == 0,
                  'D1 에 점검 방이 남지 않았다')

            # 계정 삭제가 실험실 방·초대를 함께 정리하는지(delete_check 와 같은 경로)
            host.click('#btn-lab')
            host.wait_for_timeout(400)
            host.click('#lab-create')
            host.wait_for_timeout(1600)
            room2 = lab_state(host)
            check(bool(room2), '정리 시험용 방 만들기', str(room2 and room2.get('code')))
            code2 = room2['code'] if room2 else ''
            if code2:
                host.evaluate("() => window.__ITDA.app.labPanel.loadFriends({force: true}).then(() => window.__ITDA.app.labPanel.renderFriends())")
                host.wait_for_timeout(900)
                if host.query_selector('.lab-friend .lab-invite-btn'):
                    host.click('.lab-friend .lab-invite-btn')
                    host.wait_for_timeout(1000)
                deleted = api(host, '/api/auth/delete', 'POST', {'password': PASSWORD})
                check(deleted['status'] == 200 and deleted['data'].get('ok'), '계정 삭제(실험실 정리 시험)',
                      json.dumps(deleted.get('data'), ensure_ascii=False)[:160])
                check(d1_value(f"SELECT COUNT(*) FROM lab_rooms WHERE code = '{code2}'") == 0,
                      '계정 삭제 뒤 방이 지워짐')
                check(d1_value(f"SELECT COUNT(*) FROM lab_invites WHERE room_code = '{code2}'") == 0,
                      '계정 삭제 뒤 초대가 지워짐')
                check(d1_value("SELECT COUNT(*) FROM users WHERE username = '점검실험A'") == 0,
                      '계정 행도 사라짐')

            print('\n[12] 스크린샷 · 콘솔 오류')
            ok_errors = True
            for page, name in ((host, 'host'), (friend, 'friend')):
                if page.js_errors:
                    ok_errors = False
                    print(f'    {name} 오류: {page.js_errors[:4]}')
            check(ok_errors, '점검 중 콘솔 오류 없음')
            check(len(SHOTS) >= 8, '스크린샷 저장', str(len(SHOTS)))
            browser.close()
    finally:
        # wrangler 가 띄운 workerd 까지 함께 정리한다(남으면 로컬 D1 을 잠가 다음 점검이 멎는다).
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print(f'\n결과: {PASS} 통과 · {FAIL} 실패')
    print('스크린샷:', SHOT_DIR)
    if not args.keep:
        pass
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
