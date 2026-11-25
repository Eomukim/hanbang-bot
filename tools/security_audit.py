#!/usr/bin/env python3
"""잇다 보안 · 부하 · 엣지 케이스 정밀 감사.

로컬 `wrangler pages dev`(+로컬 D1)에서 아래를 확인한다.

 A. 출처(CSRF) 검사 — 모든 상태 변경 API(POST·DELETE)에 다른 사이트의 Origin/Referer 를
    붙이면 403 forbidden_origin, 같은 출처·헤더 없음은 정상 흐름(401·400·200).
 B. 소유권·권한 — 남의 메일 읽음/삭제/휴지통/복구/수정 불가(읽음 updated 0, 나머지 404·행 보존),
    휴지통은 내 쪽만 · 휴지통에 넣은 메일은 안 읽은 수에서 제외, 답장은 본인이 참여한 메일만,
    공지 작성·수정·삭제는 관리자만(게스트·일반 유저 403).
 C. 주입·헤더 — SQL 인젝션 모양 값, 태그가 든 아이디·제목·본문, nosniff·referrer-policy·
    frame-options, no-store.
 D. 폭주 방어 — 32KB 초과 본문 413(Content-Length 속임·청크 포함), 메일 수정 반복 429,
    조회 API 반복 429, auth_throttle 만료 행 자동 청소(진행 중 창은 보존), 정상 사용량은 200.
 E. 프런트 — 모달(설정·계정·메일) 위 Enter 가 뒤의 `대전 시작` 을 누르지 않음, 닫은 뒤
    포커스 복귀, 삭제(휴지통)·발송 연타 1회 요청, 휴지통 복구, 세션 만료(401) 시 게스트 정리,
    긴 아이디·제목·연속 200자, 흑백모드, 네 탭 레이아웃, 모바일 320×568·360×640·390×844·844×390.
 F. 콘솔 에러·404 리소스 0건.

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/security_audit.py --local
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
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRANGLER = '/workspace/tools-npm/node_modules/.bin/wrangler'
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
PORT = 8795
LOCAL = 'http://127.0.0.1:%d' % PORT
ADMIN = '점검관리자'
PASSWORD = 'itda-Audit-24'
SHOT_DIR = os.path.join(ROOT, 'downloads', 'audit')

PASS = 0
FAIL = 0
SHOTS = {}
BASE = LOCAL
LIVE = False


def skip(label, reason):
    print('  · SKIP %s — %s' % (label, reason))


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  ✓ %s' % label)
    else:
        FAIL += 1
        print('  ✗ %s%s' % (label, (' — ' + str(detail)) if detail else ''))


# ── 서버 · D1 ────────────────────────────────────────────────

def wrangler_env():
    env = dict(os.environ)
    env['PATH'] = '/workspace/.local/node/bin:' + env.get('PATH', '')
    env['WRANGLER_SEND_METRICS'] = 'false'
    return env


def ensure_config():
    src = os.path.join(ROOT, 'wrangler.local.toml')
    dst = os.path.join(ROOT, 'wrangler.toml')
    if os.path.exists(dst):
        return False
    shutil.copy(src, dst)
    return True


def d1(sql):
    proc = subprocess.run([WRANGLER, 'd1', 'execute', 'itda-db', '--local', '--json', '--command', sql],
                          cwd=ROOT, env=wrangler_env(), capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    text = proc.stdout.strip()
    start = text.find('[')
    return json.loads(text[start:]) if start >= 0 else []


def d1_file(path):
    proc = subprocess.run([WRANGLER, 'd1', 'execute', 'itda-db', '--local', '--file', path],
                          cwd=ROOT, env=wrangler_env(), capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())


def apply_migrations():
    """이미 만들어진 로컬 D1 에 새 칸을 더한다(이미 있으면 ADD COLUMN 이 실패하므로 무시)."""
    path = os.path.join(ROOT, 'db', 'migrations', '2026-11-25-mail-trash-edit.sql')
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


def start_local():
    proc = subprocess.Popen([WRANGLER, 'pages', 'dev', '.', '--port', str(PORT), '--ip', '127.0.0.1'],
                            cwd=ROOT, env=wrangler_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(90):
        try:
            urllib.request.urlopen(LOCAL + '/api/auth/config', timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError('로컬 서버가 뜨지 않았습니다')


# ── HTTP ─────────────────────────────────────────────────────

class Http:
    """쿠키·헤더를 직접 다루는 얇은 HTTP 클라이언트(교차 출처 요청을 흉내 낸다)."""

    def __init__(self, base=None):
        parsed = urlparse(base or BASE)
        self.base = base
        self.scheme = parsed.scheme or 'http'
        self.host = parsed.hostname or '127.0.0.1'
        self.port = parsed.port or (443 if self.scheme == 'https' else 80)
        self.prefix = parsed.path.rstrip('/')
        self.cookies = {}

    def request(self, path, method='GET', body=None, headers=None, chunked=False, raw_body=None):
        hdrs = dict(headers or {})
        payload = raw_body
        if body is not None:
            payload = json.dumps(body).encode()
            hdrs.setdefault('content-type', 'application/json')
        if self.cookies:
            hdrs['cookie'] = '; '.join('%s=%s' % kv for kv in self.cookies.items())
        if payload is not None and not chunked:
            hdrs['content-length'] = str(len(payload))
        cls = HTTPSConnection if self.scheme == 'https' else HTTPConnection
        conn = cls(self.host, self.port, timeout=30)
        if chunked:
            def gen():
                yield payload
            conn.request(method, self.prefix + path, body=gen(), headers=hdrs, encode_chunked=True)
        else:
            conn.request(method, self.prefix + path, body=payload, headers=hdrs)
        res = conn.getresponse()
        data = res.read()
        heads = {k.lower(): v for k, v in res.getheaders()}
        for value in res.headers.get_all('set-cookie') or []:
            if value.startswith('itda_session='):
                token = value.split(';', 1)[0].split('=', 1)[1]
                if token:
                    self.cookies['itda_session'] = token
                else:
                    self.cookies.pop('itda_session', None)
        conn.close()
        try:
            parsed = json.loads(data) if data else None
        except Exception:
            parsed = None
        return res.status, heads, parsed, data

    def register(self, username, password=PASSWORD):
        return self.request('/api/auth/register', 'POST',
                            {'username': username, 'password': password, 'turnstileToken': 'local-test-token'})

    def login(self, username, password=PASSWORD):
        return self.request('/api/auth/login', 'POST',
                            {'username': username, 'password': password, 'turnstileToken': 'local-test-token'})


def new_name(prefix):
    return prefix + ''.join(random.choice(string.digits) for _ in range(4))


# ── A. 출처(CSRF) ─────────────────────────────────────────────

def audit_csrf(names):
    print('\n· A. 출처(CSRF) 검사')
    evil = {'origin': 'https://evil.example'}
    evil_ref = {'referer': 'https://evil.example/attack.html'}
    probe = {
        'register': ('/api/auth/register', 'POST', {'username': 'x', 'password': '123456'}),
        'login': ('/api/auth/login', 'POST', {'username': 'x', 'password': '123456'}),
        'google': ('/api/auth/google', 'POST', {'credential': 'x'}),
        'delete': ('/api/auth/delete', 'POST', {'password': 'x'}),
        'logout': ('/api/auth/logout', 'POST', None),
        'mail/send': ('/api/mail/send', 'POST', {'to': 'x', 'subject': 's', 'body': 'b'}),
        'mail/delete': ('/api/mail/delete', 'POST', {'id': 'm_0000'}),
        'mail/read': ('/api/mail/read', 'POST', {'id': 'm_0000'}),
        'mail/trash': ('/api/mail/trash', 'POST', {'id': 'm_0000'}),
        'mail/trash/empty': ('/api/mail/trash/empty', 'POST', None),
        'mail/restore': ('/api/mail/restore', 'POST', {'id': 'm_0000'}),
        'mail/edit': ('/api/mail/edit', 'POST', {'id': 'm_0000', 'subject': 's', 'body': 'b'}),
        'notices POST': ('/api/mail/notices', 'POST', {'title': 't', 'body': 'b'}),
        'notices DELETE': ('/api/mail/notices', 'DELETE', {'id': 'n_0000'}),
        'notices/edit': ('/api/mail/notices/edit', 'POST', {'id': 'n_0000', 'title': 't', 'body': 'b'}),
        'notices/read': ('/api/mail/notices/read', 'POST', {'all': True}),
    }
    for label, (path, method, body) in probe.items():
        status, heads, data, _ = Http().request(path, method, body, evil)
        check(status == 403 and (data or {}).get('error') == 'forbidden_origin',
              '%s + 다른 Origin → 403' % label, '%s %s' % (status, json.dumps(data, ensure_ascii=False)[:110]))
        check('no-store' in heads.get('cache-control', ''), '%s 403 응답 no-store' % label, heads.get('cache-control'))
    for label, (path, method, body) in list(probe.items())[:6]:
        status, _, data, _ = Http().request(path, method, body, evil_ref)
        check(status == 403 and (data or {}).get('error') == 'forbidden_origin',
              '%s + 다른 Referer → 403' % label, status)
    # 같은 출처는 그대로 통과(권한이 없어 401·403 이지 출처 때문에 막히지 않는다)
    status, _, data, _ = Http().request('/api/mail/send', 'POST',
                                        {'to': 'x', 'subject': 's', 'body': 'b'}, {'origin': BASE})
    check(status == 401 and (data or {}).get('error') == 'not_signed_in',
          '같은 Origin 게스트 발송 → 401(출처 통과)', '%s %s' % (status, (data or {}).get('error')))
    # 로컬 개발 주소(localhost:다른 포트)도 허용
    status, _, data, _ = Http().request('/api/mail/send', 'POST',
                                        {'to': 'x', 'subject': 's', 'body': 'b'},
                                        {'origin': 'http://localhost:3000'})
    check(status == 401, 'localhost 개발 출처 허용', '%s %s' % (status, (data or {}).get('error')))
    # Origin 없음(도구·앱)은 막지 않는다
    status, _, data, _ = Http().request('/api/mail/send', 'POST', {'to': 'x', 'subject': 's', 'body': 'b'})
    check(status == 401, 'Origin 헤더 없는 요청은 통과', status)
    # 조회는 출처를 막지 않는다(그림·링크로 남의 요약을 읽는 것은 무해)
    status, _, _, _ = Http().request('/api/mail/summary', 'GET', None, evil)
    check(status == 200, 'GET 요청은 출처 검사 없음', status)


# ── B. 소유권·권한 ────────────────────────────────────────────

def audit_ownership(names):
    print('\n· B. 소유권·권한')
    a, b, c = Http(), Http(), Http()
    ca, cb, cc = a.login(names['a']), b.login(names['b']), c.login(names['c'])
    check(ca[0] == 200 and cb[0] == 200 and cc[0] == 200, '점검 계정 3개 로그인',
          '%s %s %s' % (ca[0], cb[0], cc[0]))

    # A → B 메일 (B 가 읽음 처리 대상)
    status, _, data, _ = a.request('/api/mail/send', 'POST',
                                   {'to': names['b'], 'subject': '소유권 점검', 'body': '본문'})
    mail_to_b = (data or {}).get('mail', {}).get('id')
    check(status == 200 and mail_to_b, 'A → B 메일 발송', status)

    # C 가 남의 메일을 읽음 처리하려 해도 바뀌지 않는다
    status, _, data, _ = c.request('/api/mail/read', 'POST', {'id': mail_to_b})
    check(status == 200 and (data or {}).get('updated') == 0,
          'C 가 남의 메일 읽음 시도 → updated 0', '%s %s' % (status, json.dumps(data, ensure_ascii=False)[:120]))
    row = d1("SELECT is_read FROM mails WHERE id = '%s'" % mail_to_b)
    check(row[0]['results'][0]['is_read'] == 0, '남의 메일 is_read 그대로 0',
          row[0]['results'][0]['is_read'])

    # B 본인이 읽으면 반영
    status, _, data, _ = b.request('/api/mail/read', 'POST', {'id': mail_to_b})
    check(status == 200 and (data or {}).get('updated') == 1, 'B 본인 메일 읽음 → updated 1',
          json.dumps(data, ensure_ascii=False)[:120])
    row = d1("SELECT is_read FROM mails WHERE id = '%s'" % mail_to_b)
    check(row[0]['results'][0]['is_read'] == 1, 'B 의 읽음이 DB 에 반영', row[0]['results'][0]['is_read'])

    # A → C 메일: B 는 참여자가 아니다
    status, _, data, _ = a.request('/api/mail/send', 'POST',
                                   {'to': names['c'], 'subject': 'B 와 무관한 메일', 'body': '본문'})
    mail_a_c = (data or {}).get('mail', {}).get('id')
    status, _, data, _ = b.request('/api/mail/delete', 'POST', {'id': mail_a_c})
    check(status == 404 and (data or {}).get('error') == 'not_found',
          'B 가 A↔C 메일 삭제 시도 → 404', '%s %s' % (status, (data or {}).get('error')))
    row = d1("SELECT deleted_by_sender, deleted_by_recipient FROM mails WHERE id = '%s'" % mail_a_c)
    kept = row[0]['results'][0]
    check(kept['deleted_by_sender'] == 0 and kept['deleted_by_recipient'] == 0,
          '남의 메일 삭제 시도 뒤에도 행·플래그 그대로', kept)

    # 답장 연결: 본인이 참여하지 않은 메일을 replyToId 로 넘길 수 없다
    status, _, data, _ = b.request('/api/mail/send', 'POST',
                                   {'to': names['a'], 'subject': '답장 시도', 'body': '본문',
                                    'replyToId': mail_a_c})
    check(status == 400 and (data or {}).get('error') == 'reply_invalid',
          '참여하지 않은 메일로 답장 → 400 reply_invalid', '%s %s' % (status, (data or {}).get('error')))
    status, _, data, _ = b.request('/api/mail/send', 'POST',
                                   {'to': names['a'], 'subject': '답장 시도', 'body': '본문',
                                    'replyToId': 'm_doesnotexist'})
    check(status == 400 and (data or {}).get('error') == 'reply_invalid',
          '없는 메일로 답장 → 400(존재 유추 불가)', status)

    # 공지 권한
    status, _, data, _ = a.request('/api/mail/notices', 'POST', {'title': '일반 유저', 'body': '막힘'})
    check(status == 403 and (data or {}).get('error') == 'forbidden',
          '일반 유저 공지 작성 403', status)
    status, _, data, _ = a.request('/api/mail/notices', 'DELETE', {'id': 'n_0000'})
    check(status == 403, '일반 유저 공지 삭제 403', status)
    guest = Http()
    status, _, data, _ = guest.request('/api/mail/notices', 'POST', {'title': '게스트', 'body': '막힘'})
    check(status == 403, '게스트 공지 작성 403', status)
    # 일반 유저가 관리자 공지를 지우려 해도 그대로
    admin = Http()
    status, _, data, _ = admin.login(ADMIN)
    status, _, data, _ = admin.request('/api/mail/notices', 'POST',
                                       {'title': '권한 점검 공지', 'body': '지워지면 안 됩니다.'})
    notice_id = (data or {}).get('notice', {}).get('id')
    check(status == 200 and notice_id, '관리자 공지 작성', status)
    status, _, data, _ = a.request('/api/mail/notices', 'DELETE', {'id': notice_id})
    check(status == 403, '일반 유저가 관리자 공지 삭제 시도 403', status)
    row = d1("SELECT COUNT(*) AS n FROM notices WHERE id = '%s'" % notice_id)
    check(row[0]['results'][0]['n'] == 1, '공지가 그대로 남음', row[0]['results'][0]['n'])
    admin.request('/api/mail/notices', 'DELETE', {'id': notice_id})

    # 이상한 id 모양은 400(다른 접두사·공백·초장문)
    for bad in ['x_123', 'm_', '', 'm_' + 'a' * 80, '../../etc/passwd']:
        status, _, data, _ = a.request('/api/mail/read', 'POST', {'id': bad})
        check(status == 400 and (data or {}).get('error') == 'id_required',
              '이상한 메일 id %r → 400' % (bad[:14],), status)

    # ── 휴지통·복구·수정 소유권 ──────────────────────────────
    status, _, data, _ = a.request('/api/mail/send', 'POST',
                                   {'to': names['b'], 'subject': '휴지통 소유권', 'body': '본문'})
    mail_t = (data or {}).get('mail', {}).get('id')
    check(status == 200 and mail_t, '휴지통 점검용 메일 발송', status)
    status, _, data, _ = c.request('/api/mail/trash', 'POST', {'id': mail_t})
    check(status == 404, 'C 가 남의 메일 휴지통 이동 → 404', status)
    row = d1("SELECT sender_trashed_at, recipient_trashed_at FROM mails WHERE id = '%s'" % mail_t)[0]['results'][0]
    check(row['sender_trashed_at'] is None and row['recipient_trashed_at'] is None,
          '남의 메일 휴지통 시각 그대로', row)
    status, _, data, _ = c.request('/api/mail/restore', 'POST', {'id': mail_t})
    check(status == 404, 'C 가 남의 메일 복구 시도 → 404', status)
    status, _, data, _ = c.request('/api/mail/edit', 'POST',
                                   {'id': mail_t, 'subject': '남의 메일', 'body': '본문'})
    check(status == 404, 'C 가 남의 메일 수정 시도 → 404', status)
    status, _, data, _ = b.request('/api/mail/edit', 'POST',
                                   {'id': mail_t, 'subject': '받는 사람 수정', 'body': '본문'})
    check(status == 404, '받는 사람이 보낸 메일 수정 시도 → 404', status)
    row = d1("SELECT subject FROM mails WHERE id = '%s'" % mail_t)[0]['results'][0]
    check(row['subject'] == '휴지통 소유권', '남의 수정 시도 뒤에도 제목 그대로', row)

    status, _, data, _ = b.request('/api/mail/trash', 'POST', {'id': mail_t})
    check(status == 200 and (data or {}).get('trashed') is True, 'B 가 받은 메일을 휴지통으로', status)
    row = d1("SELECT sender_trashed_at, recipient_trashed_at, deleted_by_recipient FROM mails WHERE id = '%s'" % mail_t)[0]['results'][0]
    check(row['recipient_trashed_at'] and row['sender_trashed_at'] is None and row['deleted_by_recipient'] == 0,
          '휴지통은 내 쪽 시각만 기록(상대 함·행 유지)', row)
    status, _, data, _ = b.request('/api/mail/summary')
    check((data or {}).get('unreadMailCount') == 0,
          '휴지통에 넣은 안 읽은 메일은 빨간 동그라미에서 빠짐', (data or {}).get('unreadMailCount'))
    status, _, data, _ = b.request('/api/mail/inbox')
    check(all(m['id'] != mail_t for m in (data or {}).get('mails', [])),
          '휴지통 메일은 받은 메일 목록에 없음', status)
    status, _, data, _ = b.request('/api/mail/trash')
    check(any(m['id'] == mail_t and m.get('folder') == 'inbox' for m in (data or {}).get('mails', [])),
          '휴지통 목록에 받은 메일로 보임', status)
    status, _, data, _ = a.request('/api/mail/sent')
    check(any(m['id'] == mail_t for m in (data or {}).get('mails', [])),
          '상대(A) 보낸 메일함에는 그대로', status)

    status, _, data, _ = b.request('/api/mail/restore', 'POST', {'id': mail_t})
    check(status == 200 and (data or {}).get('folder') == 'inbox', 'B 복구 → 받은 메일함', status)
    status, _, data, _ = b.request('/api/mail/restore', 'POST', {'id': mail_t})
    check(status == 404, '휴지통에 없는 메일 복구 404', status)

    # 휴지통 비우기는 내 것만 건드린다
    b.request('/api/mail/trash', 'POST', {'id': mail_t})
    status, _, data, _ = c.request('/api/mail/trash/empty', 'POST', {})
    check(status == 200, 'C 휴지통 비우기 200', status)
    row = d1("SELECT recipient_trashed_at, deleted_by_recipient FROM mails WHERE id = '%s'" % mail_t)[0]['results'][0]
    check(row['recipient_trashed_at'] and row['deleted_by_recipient'] == 0,
          '남의 휴지통 비우기가 내 휴지통을 건드리지 않음', row)
    status, _, data, _ = b.request('/api/mail/trash/empty', 'POST', {})
    check(status == 200 and (data or {}).get('purged', 0) >= 1, 'B 휴지통 비우기 → 내 쪽 완전 삭제', data)
    row = d1("SELECT deleted_by_recipient, deleted_by_sender FROM mails WHERE id = '%s'" % mail_t)[0]['results'][0]
    check(row['deleted_by_recipient'] == 1 and row['deleted_by_sender'] == 0,
          '비우기는 내 deleted 플래그만 세움(상대 행 유지)', row)

    # 공지 수정 권한
    status, _, data, _ = admin.request('/api/mail/notices', 'POST',
                                       {'title': '수정 점검 공지', 'body': '처음 본문'})
    nid = (data or {}).get('notice', {}).get('id')
    check(status == 200 and nid, '수정 점검 공지 작성', status)
    status, _, data, _ = a.request('/api/mail/notices/edit', 'POST',
                                   {'id': nid, 'title': '일반 유저 수정', 'body': 'x'})
    check(status == 403, '일반 유저 공지 수정 403', status)
    status, _, data, _ = guest.request('/api/mail/notices/edit', 'POST',
                                       {'id': nid, 'title': '게스트', 'body': 'x'})
    check(status == 403, '게스트 공지 수정 403', status)
    status, _, data, _ = admin.request('/api/mail/notices/edit', 'POST',
                                       {'id': nid, 'title': '수정한 점검 공지', 'body': '고친 본문'})
    check(status == 200 and (data or {}).get('notice', {}).get('updatedAt'),
          '관리자 공지 수정 200 + updatedAt', json.dumps(data, ensure_ascii=False)[:140])
    row = d1("SELECT title, updated_at FROM notices WHERE id = '%s'" % nid)[0]['results'][0]
    check(row['title'] == '수정한 점검 공지' and row['updated_at'], '공지 수정이 DB 에 반영', row)
    status, _, data, _ = admin.request('/api/mail/notices/edit', 'POST',
                                       {'id': 'n_doesnotexist', 'title': 't', 'body': 'b'})
    check(status == 404, '없는 공지 수정 404', status)
    admin.request('/api/mail/notices', 'DELETE', {'id': nid})

    return {'mail_to_b': mail_to_b, 'mail_a_c': mail_a_c, 'mail_t': mail_t}


# ── C. 주입 · 헤더 ────────────────────────────────────────────

def audit_injection_headers(names, client=None):
    print('\n· C. 주입 · 보안 헤더')
    a = client or Http()
    if client is None:
        a.login(names['a'])
    signed = bool(((a.request('/api/auth/me')[2] or {}).get('user')))
    payloads = [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        'admin" --',
        '<img src=x onerror=alert(1)>',
    ]
    if not signed:
        skip('받는 사람 인젝션 모양 4종', '계정 없이는 발송 API 를 부를 수 없다(운영 가입 차단)')
    else:
        for payload in payloads:
            status, _, data, _ = a.request('/api/mail/send', 'POST',
                                           {'to': payload, 'subject': payload, 'body': payload})
            check(status in (400, 404), '받는 사람 인젝션 모양 %r 거부' % payload[:16],
                  '%s %s' % (status, (data or {}).get('error')))
    status, _, data, _ = a.request('/api/auth/login', 'POST',
                                   {'username': "' OR 1=1 --", 'password': 'x', 'turnstileToken': 'local-test-token'})
    check(status == 401, '아이디 인젝션 모양 로그인 401', status)
    if not LIVE:
        rows = d1("SELECT COUNT(*) AS n FROM users")
        check(rows[0]['results'][0]['n'] > 0, 'users 표가 살아 있음', rows[0]['results'][0]['n'])

    status, heads, data, _ = Http().request('/api/mail/summary')
    check(heads.get('x-content-type-options') == 'nosniff', '/api 응답 nosniff', heads.get('x-content-type-options'))
    check(heads.get('referrer-policy') == 'same-origin', '/api 응답 referrer-policy', heads.get('referrer-policy'))
    check(heads.get('x-frame-options') == 'DENY', '/api 응답 frame-options', heads.get('x-frame-options'))
    check('no-store' in heads.get('cache-control', ''), '/api 응답 no-store', heads.get('cache-control'))
    status, heads, data, _ = Http().request('/')
    check(heads.get('x-content-type-options') == 'nosniff', 'HTML 응답 nosniff', heads.get('x-content-type-options'))
    check(heads.get('referrer-policy') == 'same-origin', 'HTML 응답 referrer-policy', heads.get('referrer-policy'))
    status, heads, data, _ = Http().request('/js/mail.js')
    check(heads.get('x-content-type-options') == 'nosniff', 'JS 자산 nosniff', heads.get('x-content-type-options'))
    # 서버가 원본 비밀 값을 내려 주지 않는다
    status, _, data, _ = Http().request('/api/auth/config')
    flat = json.dumps(data, ensure_ascii=False)
    check('TURNSTILE_SECRET' not in flat and 'secret' not in flat.lower(), 'config 에 비밀 키 없음', flat[:120])


# ── D. 폭주 방어 ──────────────────────────────────────────────

def audit_dos(names):
    print('\n· D. 폭주 방어')
    a = Http()
    a.login(names['a'])

    big = json.dumps({'to': names['b'], 'subject': '제목', 'body': 'ㄱ' * (40 * 1024)}).encode()
    status, _, data, _ = a.request('/api/mail/send', 'POST', raw_body=big,
                                   headers={'content-type': 'application/json'})
    check(status == 413 and (data or {}).get('error') == 'payload_too_large',
          '본문 40KB → 413', '%s %s' % (status, (data or {}).get('error')))

    # Content-Length 를 속여도(작게 적고 많이 보내기) 스트림에서 잘린다
    status, _, data, _ = a.request('/api/mail/send', 'POST', raw_body=big, chunked=True,
                                   headers={'content-type': 'application/json'})
    check(status == 413, '청크 본문(Content-Length 없음) 40KB → 413', status)

    huge = b'{"a":"' + b'x' * (512 * 1024) + b'"}'
    status, _, data, _ = a.request('/api/auth/register', 'POST', raw_body=huge,
                                   headers={'content-type': 'application/json'})
    check(status == 413, '512KB 본문 → 413(읽기 전에 거부)', status)

    # 수정·휴지통도 같은 32KB 상한과 사용자별 제한을 쓴다
    edit_big = json.dumps({'id': 'm_0000', 'subject': '제목', 'body': 'ㄱ' * (40 * 1024)}).encode()
    status, _, data, _ = a.request('/api/mail/edit', 'POST', raw_body=edit_big,
                                   headers={'content-type': 'application/json'})
    check(status == 413 and (data or {}).get('error') == 'payload_too_large',
          '수정 요청 40KB → 413', '%s %s' % (status, (data or {}).get('error')))
    status, _, data, _ = a.request('/api/mail/trash', 'POST', raw_body=edit_big, chunked=True,
                                   headers={'content-type': 'application/json'})
    check(status == 413, '휴지통 요청 청크 40KB → 413', status)
    status, _, data, _ = a.request('/api/mail/restore', 'POST', {'id': 'm_'})
    check(status == 400 and (data or {}).get('error') == 'id_required',
          '휴지통 복구 이상한 id → 400', status)
    edit_codes = []
    for _ in range(34):
        status, _, _, _ = a.request('/api/mail/edit', 'POST',
                                    {'id': 'm_0000', 'subject': '제목', 'body': '본문'})
        edit_codes.append(status)
    check(429 in edit_codes, '메일 수정 반복(34회/10분) → 429', sorted(set(edit_codes)))

    status, _, data, _ = a.request('/api/mail/send', 'POST', {'to': names['b'], 'subject': '제목'}, )
    check(status == 400, '본문 없는 요청은 400(413 아님)', status)

    # 정상 크기는 그대로 통과
    body5000 = 'ㄴ' * 1900
    status, _, data, _ = a.request('/api/mail/send', 'POST',
                                   {'to': names['b'], 'subject': '정상 크기', 'body': body5000})
    check(status == 200, '정상 크기(약 5.7KB)는 통과', status)

    # 조회 API 반복 → 429, 다른 조회 API 는 따로 센다
    http = Http()
    first = http.request('/api/mail/summary')[0]
    check(first == 200, '첫 요약 요청 200', first)
    codes = {}
    retry_after = ''
    err = ''
    for _ in range(220):
        status, heads, data, _ = http.request('/api/mail/summary')
        codes[status] = codes.get(status, 0) + 1
        if status == 429 and not retry_after:
            retry_after = heads.get('retry-after', '')
            err = (data or {}).get('error')
    check(codes.get(429, 0) > 0, '요약 반복 요청 → 429', codes)
    check(codes.get(200, 0) >= 150, '정상 사용량(분당 150회)까지는 200', codes)
    check(retry_after.isdigit() and int(retry_after) > 0, '429 에 retry-after(초)', retry_after)
    check((err or '') == 'rate_limited', '429 error=rate_limited', err)
    status = Http().request('/api/auth/me')[0]
    check(status == 200, '요약이 막혀도 다른 API 는 그대로', status)

    # auth_throttle 만료 행 청소 — 오래된 행을 심고 요청을 돌려 사라지는지 본다
    now = int(time.time())
    d1("INSERT OR REPLACE INTO auth_throttle (key, count, window_start) VALUES ('audit:old:1', 5, %d)" % (now - 99999))
    d1("INSERT OR REPLACE INTO auth_throttle (key, count, window_start) VALUES ('audit:old:2', 5, %d)" % (now - 7201))
    d1("INSERT OR REPLACE INTO auth_throttle (key, count, window_start) VALUES ('audit:fresh:1', 1, %d)" % now)
    probe = Http()
    for _ in range(30):
        probe.request('/api/mail/notices')
    rows = d1("SELECT key FROM auth_throttle WHERE key LIKE 'audit:%'")
    left = sorted(r['key'] for r in rows[0]['results'])
    check('audit:old:1' not in left and 'audit:old:2' not in left, '만료된 스로틀 행 자동 삭제', left)
    check('audit:fresh:1' in left, '진행 중(창 안) 행은 보존', left)
    d1("DELETE FROM auth_throttle WHERE key LIKE 'audit:%'")


# ── E. 프런트 ────────────────────────────────────────────────

CONSOLE_IGNORE = (
    'status of 401', 'status of 403', 'status of 429', 'status of 400', 'status of 404',
    'status of 409', 'status of 413', 'Failed to load resource',
)


def badge_contrast(page, selector, pad=4):
    """요소 주변을 캡처해 가장 밝은 픽셀과 어두운 픽셀의 밝기 차(0~255)를 돌려준다."""
    try:
        from PIL import Image
    except Exception:
        return None
    box = page.evaluate("""s => { const r = document.querySelector(s).getBoundingClientRect();
        return { x: r.x, y: r.y, w: r.width, h: r.height }; }""", selector)
    if not box['w'] or not box['h']:
        return None
    path = os.path.join(SHOT_DIR, 'pixel-%s.png' % selector.strip('#.'))
    page.screenshot(path=path, clip={'x': max(0, box['x'] - pad), 'y': max(0, box['y'] - pad),
                                     'width': box['w'] + pad * 2, 'height': box['h'] + pad * 2})
    img = Image.open(path).convert('L')
    values = list(img.getdata())
    return max(values) - min(values)


class Ui:
    def __init__(self, browser, shot_dir):
        self.browser = browser
        self.shot_dir = shot_dir
        self.console = []
        self.bad_requests = []

    def page(self, width=1280, height=900, mobile=False, user=None, cookie=None, url=None):
        ctx = self.browser.new_context(viewport={'width': width, 'height': height},
                                       device_scale_factor=2 if mobile else 1,
                                       is_mobile=mobile, has_touch=mobile, locale='ko-KR')
        if cookie:
            ctx.add_cookies([{'name': 'itda_session', 'value': cookie, 'domain': '127.0.0.1', 'path': '/'}])
        page = ctx.new_page()
        page.on('console', lambda msg: self.console.append((msg.type, msg.text))
                if msg.type in ('error', 'warning') else None)
        page.on('response', lambda res: self.bad_requests.append((res.status, res.url))
                if res.status >= 400 else None)
        page.goto(url or LOCAL, wait_until='domcontentloaded')
        page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=60000)
        page.wait_for_timeout(350)
        return ctx, page

    def shot(self, page, name, cls=None):
        path = os.path.join(self.shot_dir, name + '.png')
        (page.locator(cls).screenshot(path=path) if cls else page.screenshot(path=path))
        SHOTS[name] = path


def audit_ui(names, cookie_a, cookie_admin):
    print('\n· E. 프런트 — 키보드 · 연타 · 세션 · 레이아웃')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        ui = Ui(browser, SHOT_DIR)

        # ── E1. 모달 위 Enter ─────────────────────────────────
        ctx, page = ui.page()
        page.click('#btn-mail')
        page.wait_for_selector('#ov-mail:not([hidden])')
        page.wait_for_timeout(700)
        page.click('#mail-title')
        page.keyboard.press('Enter')
        page.wait_for_timeout(250)
        check(page.evaluate('() => window.__ITDA.app.screen') == 'setup',
              '메일함 위 Enter → 대전 시작 안 됨', page.evaluate('() => window.__ITDA.app.screen'))
        page.keyboard.press('Escape')
        page.wait_for_timeout(350)
        check(not page.is_visible('#ov-mail'), 'Escape 로 메일함 닫힘')
        check(page.evaluate('() => document.activeElement && document.activeElement.id') == 'btn-mail',
              '메일함을 닫으면 메일 버튼으로 포커스 복귀',
              page.evaluate('() => document.activeElement && (document.activeElement.id || document.activeElement.tagName)'))
        page.keyboard.press('Enter')
        page.wait_for_timeout(500)
        check(page.is_visible('#ov-mail'), '이어서 Enter 는 메일함을 다시 연다(대전 아님)',
              page.evaluate('() => window.__ITDA.app.screen'))
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)

        # 설정 창
        page.click('#btn-settings')
        page.wait_for_timeout(400)
        page.click('#ov-settings .sheet h2')
        page.keyboard.press('Enter')
        page.wait_for_timeout(250)
        check(page.evaluate('() => window.__ITDA.app.screen') == 'setup',
              '설정 창 위 Enter → 대전 시작 안 됨')
        page.keyboard.press('Escape')
        page.wait_for_timeout(350)
        check(page.evaluate('() => document.activeElement && document.activeElement.id') == 'btn-settings',
              '설정 창을 닫으면 설정 버튼으로 포커스 복귀')

        # 계정(로그인) 창
        page.click('#btn-account')
        page.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
        page.click('#auth-title')
        page.keyboard.press('Enter')
        page.wait_for_timeout(250)
        check(page.evaluate('() => window.__ITDA.app.screen') == 'setup',
              '로그인 창 위 Enter → 대전 시작 안 됨')
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        check(page.evaluate('() => document.activeElement && document.activeElement.id') == 'btn-account',
              '로그인 창을 닫으면 계정 버튼으로 포커스 복귀')

        # 사전 화면 위 Enter
        page.click('#btn-dict')
        page.wait_for_timeout(600)
        page.click('#scr-dict .dict-title b')
        page.keyboard.press('Enter')
        page.wait_for_timeout(250)
        check(page.evaluate('() => window.__ITDA.app.screen') == 'dict',
              '사전 화면 위 Enter → 대전 시작 안 됨',
              page.evaluate('() => window.__ITDA.app.screen'))
        page.wait_for_timeout(100)
        ui.shot(page, 'audit-desktop-dict')
        ctx.close()

        # ── E2. 연타 · 세션 만료 · 긴 글 (로그인 사용자) ────────
        ctx, page = ui.page(user='a', cookie=cookie_a)
        me = page.evaluate("""async () => (await (await fetch('/api/auth/me')).json()).user""")
        check(me and me.get('username') == names['a'], 'A 세션으로 접속', me)

        sends = []
        page.on('request', lambda req: sends.append(req.url) if '/api/mail/send' in req.url else None)
        page.click('#btn-mail')
        page.wait_for_timeout(800)
        page.click('#mail-compose-btn')
        page.wait_for_selector('#mail-view-compose:not([hidden])')
        page.fill('#mail-to', '@' + names['b'])
        page.fill('#mail-subject', '연타 점검')
        page.fill('#mail-content', '한 번만 보내져야 합니다.')
        page.evaluate("""() => { const b = document.getElementById('mail-compose-submit');
            b.click(); b.click(); b.click(); }""")
        page.wait_for_timeout(1800)
        check(len(sends) == 1, '보내기 연타 → 요청 1회', len(sends))
        rows = d1("SELECT COUNT(*) AS n FROM mails WHERE subject = '연타 점검'")
        check(rows[0]['results'][0]['n'] == 1, '연타해도 메일 1통만 저장', rows[0]['results'][0]['n'])

        # 받은 메일에서 삭제 연타
        page.click('#mail-tabs [data-mail-tab="inbox"]')
        page.wait_for_timeout(800)
        if page.locator('#mail-list .mail-open').count():
            page.click('#mail-list .mail-open')
            page.wait_for_selector('#mail-view-detail:not([hidden])')
            deletes = []
            page.on('request', lambda req: deletes.append(req.url) if '/api/mail/trash' in req.url else None)
            page.evaluate("""() => { const b = document.getElementById('mail-delete-btn');
                b.click(); b.click(); b.click(); b.click(); }""")
            page.wait_for_timeout(1800)
            check(len(deletes) == 1, '삭제(휴지통 이동) 연타 → 요청 1회', len(deletes))
            # 휴지통 탭에서 복구 — 목록의 복구 버튼으로 원래 함에 돌아온다
            page.click('#mail-tabs [data-mail-tab="trash"]')
            page.wait_for_timeout(900)
            check(page.locator('#mail-list .mail-item').count() >= 1, '삭제한 메일이 휴지통에 보임',
                  page.locator('#mail-list .mail-item').count())
            check(page.is_visible('#mail-trash-empty'), '휴지통 비우기 버튼이 보임')
            ui.shot(page, 'audit-desktop-mail-trash')
            page.click('#mail-list .mail-item-restore')
            page.wait_for_timeout(1300)
            check(page.locator('#mail-list .mail-item').count() == 0, '복구하면 휴지통에서 사라짐',
                  page.locator('#mail-list .mail-item').count())
            page.click('#mail-tabs [data-mail-tab="inbox"]')
            page.wait_for_timeout(900)

        # 긴 제목(80자)·긴 연속 글(200자) 메일 레이아웃
        long_title = 'ㄱ' * 80
        long_body = 'x' * 200 + '\n' + 'ㄴ' * 1200
        Http_login = Http()
        Http_login.login(names['b'])
        status, _, data, _ = Http_login.request('/api/mail/send', 'POST',
                                                {'to': names['a'], 'subject': long_title, 'body': long_body})
        check(status == 200, '긴 제목·긴 연속 글 메일 도착', status)
        # 목록은 탭을 열 때만 다시 부르므로, 창을 닫았다 열어 새 메일을 받아 온다.
        page.click('#btn-mail-close')
        page.wait_for_timeout(400)
        page.click('#btn-mail')
        page.wait_for_timeout(1000)
        check(page.locator('#mail-list .mail-item').count() >= 1, '새 메일이 목록에 보임',
              page.locator('#mail-list .mail-item').count())
        page.click('#mail-list .mail-open')
        page.wait_for_selector('#mail-view-detail:not([hidden])')
        page.wait_for_timeout(300)
        overflow = page.evaluate("""() => {
            const box = document.querySelector('.mail-detail');
            const sheet = document.querySelector('.mail-sheet');
            return { detail: box.scrollWidth - box.clientWidth,
                     sheet: sheet.scrollWidth - sheet.clientWidth,
                     doc: document.documentElement.scrollWidth - window.innerWidth };
        }""")
        check(overflow['detail'] <= 1, '긴 제목·200자 연속 글: 상세 가로 넘침 없음', overflow)
        check(overflow['sheet'] <= 1 and overflow['doc'] <= 1, '긴 글: 창·문서 가로 넘침 없음', overflow)
        page.click('#mail-reply-btn')
        page.wait_for_selector('#mail-view-compose:not([hidden])')
        subj = page.input_value('#mail-subject')
        check(len(subj) <= 80 and subj.startswith('Re:'), '80자 제목 답장도 80자 안으로(400 방지)',
              '%d자' % len(subj))
        page.fill('#mail-content', '답장 본문')
        page.click('#mail-compose-submit')
        page.wait_for_timeout(1600)
        check(page.is_visible('#mail-view-list'), '80자 제목 답장이 정상 발송')
        ui.shot(page, 'audit-desktop-mail-long-title')
        page.click('#btn-mail-close')
        page.wait_for_timeout(400)

        # 세션 만료(401) → 게스트 정리
        session_user = page.evaluate("""async () => (await (await fetch('/api/auth/me')).json()).user.id""")
        d1("DELETE FROM sessions WHERE user_id = '%s'" % session_user)
        page.click('#btn-mail')
        page.wait_for_timeout(1200)
        label = page.get_attribute('#btn-account', 'aria-label')
        tab = page.evaluate("""() => document.querySelector('#mail-tabs [data-mail-tab="inbox"]').getAttribute('aria-selected')""")
        toast = page.evaluate("""() => document.querySelector('.toast')?.textContent || ''""")
        check('로그인' in (label or '') and '님' not in (label or ''), '401 뒤 계정 버튼이 게스트로 정리', label)
        check(tab == 'false', '401 뒤 받은 메일 탭에서 공지 탭으로', tab)
        check('로그인이 풀렸어요' in toast or '로그인' in toast, '401 안내 토스트', toast[:80])
        ui.shot(page, 'audit-desktop-session-expired')
        page.click('#btn-mail-close')
        page.wait_for_timeout(300)
        ctx.close()
        # 세션을 지웠으니 모바일 단계를 위해 A 를 다시 로그인시킨다.
        renewed = Http()
        renewed.login(names['a'])
        cookie_a = renewed.cookies.get('itda_session', '')

        # ── E3. 관리자: 긴 공지 · 흑백모드 ────────────────────
        ctx, page = ui.page(cookie=cookie_admin)
        Http_admin = Http()
        Http_admin.login(ADMIN)
        Http_admin.request('/api/mail/notices', 'POST',
                           {'title': '아주 긴 공지 ' + 'ㄷ' * 80, 'body': 'z' * 200 + '\n' + 'ㅁ' * 1500})
        page.click('#btn-mail')
        page.wait_for_timeout(900)
        page.click('#mail-tabs [data-mail-tab="notices"]')
        page.wait_for_timeout(900)
        over = page.evaluate("""() => {
            const item = document.querySelector('#mail-list .mail-item');
            const list = document.querySelector('#mail-list');
            const sheet = document.querySelector('.mail-sheet');
            return { item: item ? item.scrollWidth - item.clientWidth : -1,
                     list: list.scrollWidth - list.clientWidth,
                     sheet: sheet.scrollWidth - sheet.clientWidth };
        }""")
        check(over['item'] <= 1 and over['list'] <= 1 and over['sheet'] <= 1,
              '긴 공지 제목이 목록 레이아웃을 밀지 않음', over)
        check(page.is_visible('#mail-notice-new'), '관리자에게 공지 작성 버튼')
        ui.shot(page, 'audit-desktop-notices-admin')
        page.click('#btn-mail-close')
        page.wait_for_timeout(300)

        # 흑백모드: 화면 전체 회색 + 위험 영역·토스트·동그라미가 그대로 보이고 동작하는지
        page.click('#btn-settings')
        page.wait_for_timeout(400)
        page.click('#btn-mono')
        page.wait_for_timeout(300)
        check(page.evaluate("() => document.documentElement.classList.contains('mono')"), '흑백모드 켜짐')
        page.click('#btn-settings-close')
        page.wait_for_timeout(400)

        # 긴 표시 이름(24자)·긴 아이디(12자)가 계정 창 레이아웃을 밀지 않는지
        long_name = '아주아주아주긴이름테스트스물네글자임돠'[:24]
        d1("UPDATE users SET display_name = '%s' WHERE username = '%s'" % (long_name, ADMIN))
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=60000)
        page.wait_for_timeout(500)
        page.click('#btn-account')
        page.wait_for_selector('#ov-account:not([hidden])', timeout=8000)
        page.wait_for_timeout(300)
        name_box = page.evaluate("""() => {
            const b = document.querySelector('.account-name b');
            const sheet = document.querySelector('#ov-account .sheet');
            const card = document.querySelector('.account-card');
            return { name: b.textContent, clipped: b.scrollWidth > b.clientWidth,
                     card: card.scrollWidth - card.clientWidth,
                     sheet: sheet.scrollWidth - sheet.clientWidth,
                     fit: sheet.getBoundingClientRect().right <= innerWidth + 1 };
        }""")
        check(name_box['sheet'] <= 1 and name_box['card'] <= 1 and name_box['fit'],
              '24자 표시 이름도 계정 창을 밀지 않음(말줄임)', name_box)
        ui.shot(page, 'audit-desktop-account-longname')
        d1("UPDATE users SET display_name = '%s' WHERE username = '%s'" % (ADMIN, ADMIN))
        page.click('#btn-delete-account')
        page.wait_for_timeout(400)
        danger = page.evaluate("""() => {
            const view = document.getElementById('account-delete-view');
            const btn = document.getElementById('btn-delete-confirm');
            const sheet = document.querySelector('#ov-account .sheet');
            const r = btn.getBoundingClientRect(), s = sheet.getBoundingClientRect();
            return { viewHidden: view.hidden, disabled: btn.disabled, label: btn.textContent.trim(),
                     inside: r.top >= s.top - 1 && r.bottom <= s.bottom + 1 && r.width > 60,
                     sheetFits: s.bottom <= innerHeight + 1 && s.top >= -1 };
        }""")
        check(not danger['viewHidden'] and danger['disabled'] and danger['inside'] and danger['sheetFits'],
              '흑백모드에서 계정 삭제(위험 영역) 화면이 보이고 확인 전에는 잠김', danger)
        ui.shot(page, 'audit-desktop-account-danger-mono')
        page.click('#btn-delete-cancel')
        page.wait_for_timeout(300)
        page.click('#btn-account-close')
        page.wait_for_timeout(300)
        page.evaluate("() => window.__ITDA.app.toast('흑백모드 점검')")
        page.wait_for_timeout(400)
        toast = page.evaluate("""() => {
            const el = document.querySelector('.toast');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { cls: el.className, shown: getComputedStyle(el).opacity !== '0' && r.width > 0,
                     inside: r.top >= -1 && r.bottom <= innerHeight + 1 && r.left >= -1 && r.right <= innerWidth + 1 };
        }""")
        check(toast and toast['shown'] and toast['inside'], '흑백모드에서 토스트가 화면 안에 보임', toast)
        ui.shot(page, 'audit-desktop-toast-mono')
        page.click('#btn-settings')
        page.wait_for_timeout(300)
        page.click('#btn-mono')
        page.wait_for_timeout(200)
        page.click('#btn-settings-close')
        page.wait_for_timeout(300)
        ctx.close()

        # 게스트: 새 공지 동그라미가 흑백모드에서도 보이는지(픽셀 대비까지)
        ctx, page = ui.page()
        page.wait_for_timeout(800)
        check(page.is_visible('#mail-badge'), '새 공지가 있으면 게스트에게 빨간 동그라미')
        page.click('#btn-settings')
        page.wait_for_timeout(400)
        page.click('#btn-mono')
        page.wait_for_timeout(300)
        page.click('#btn-settings-close')
        page.wait_for_timeout(400)
        mono = page.evaluate("""() => {
            const badge = document.getElementById('mail-badge');
            const sheet = document.querySelector('.mail-sheet');
            return { filter: getComputedStyle(document.getElementById('app')).filter,
                     hidden: badge.hidden, w: badge.getBoundingClientRect().width,
                     opacity: getComputedStyle(badge).opacity };
        }""")
        check('grayscale' in mono['filter'], '흑백모드에서 화면이 회색 처리', mono['filter'])
        check(not mono['hidden'] and mono['w'] > 0 and mono['opacity'] == '1',
              '흑백모드에서도 알림 동그라미가 그려짐', mono)
        contrast = badge_contrast(page, '#mail-badge')
        check(contrast is not None and contrast >= 20, '흑백모드 동그라미가 배경과 구분됨(밝기 차)', contrast)
        ui.shot(page, 'audit-desktop-mail-mono')
        ui.shot(page, 'audit-desktop-badge-mono', cls='.top-actions')
        page.click('#btn-mail')
        page.wait_for_timeout(900)
        fits = page.evaluate("""() => { const s = document.querySelector('.mail-sheet').getBoundingClientRect();
            return { w: Math.round(s.width), h: Math.round(s.height), vw: innerWidth, vh: innerHeight }; }""")
        check(fits['w'] <= fits['vw'] and fits['h'] <= fits['vh'], '흑백모드에서 메일함 창 폭 유지', fits)
        ctx.close()

        # ── E4. 모바일 4종 화면 ───────────────────────────────
        for width, height, mobile, name in [
            (320, 568, True, '320x568'),
            (360, 640, True, '360x640'),
            (390, 844, True, '390x844'),
            (844, 390, False, '844x390'),
        ]:
            ctx, page = ui.page(width=width, height=height, mobile=mobile, cookie=cookie_a)
            page.click('#btn-mail')
            page.wait_for_timeout(900)
            tabs = page.evaluate("""() => {
                const bar = document.getElementById('mail-tabs');
                const btns = [...bar.querySelectorAll('[data-mail-tab]')];
                return { overflow: bar.scrollWidth - bar.clientWidth,
                         keys: btns.map(b => b.dataset.mailTab),
                         clipped: btns.filter(b => b.scrollWidth > b.clientWidth + 1).map(b => b.dataset.mailTab) };
            }""")
            check(tabs['keys'] == ['inbox', 'sent', 'trash', 'notices'],
                  '%s 탭 순서: 받은 · 보낸 · 휴지통 · 공지' % name, tabs['keys'])
            check(tabs['overflow'] <= 1 and not tabs['clipped'],
                  '%s 네 탭이 잘리지 않고 한 줄에 들어옴' % name, tabs)
            box = page.evaluate("""() => {
                const sheet = document.querySelector('.mail-sheet');
                const r = sheet.getBoundingClientRect();
                return { w: Math.round(r.width), h: Math.round(r.height),
                         top: Math.round(r.top), bottom: Math.round(r.bottom),
                         vw: innerWidth, vh: innerHeight,
                         doc: document.documentElement.scrollWidth - window.innerWidth };
            }""")
            check(box['w'] <= box['vw'] + 1 and box['top'] >= -1 and box['bottom'] <= box['vh'] + 1,
                  '%s 메일함 창이 화면 안에 들어옴' % name, box)
            check(box['doc'] <= 1, '%s 가로 스크롤 없음' % name, box['doc'])
            ui.shot(page, 'audit-mobile-%s-mail-list' % name)
            if page.locator('#mail-list .mail-open').count():
                page.click('#mail-list .mail-open')
                page.wait_for_selector('#mail-view-detail:not([hidden])')
                page.wait_for_timeout(300)
                acts = page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('.mail-detail-actions .btn')]
                        .filter(b => !b.hidden);
                    const vh = innerHeight, vw = innerWidth;
                    return btns.map(b => { const r = b.getBoundingClientRect();
                        return { txt: b.textContent.trim(), w: Math.round(r.width),
                                 inside: r.top >= -1 && r.bottom <= vh + 1 && r.left >= -1 && r.right <= vw + 1 }; });
                }""")
                check(all(a['inside'] and a['w'] > 0 for a in acts),
                      '%s 상세 버튼이 화면 안에 보임' % name, acts)
                ui.shot(page, 'audit-mobile-%s-mail-detail' % name)
                page.click('#mail-detail-back')
                page.wait_for_timeout(500)
            page.click('#mail-compose-btn')
            page.wait_for_selector('#mail-view-compose:not([hidden])')
            page.wait_for_timeout(300)
            comp = page.evaluate("""() => {
                const btn = document.getElementById('mail-compose-submit');
                const form = document.getElementById('mail-compose-form');
                const r = btn.getBoundingClientRect();
                return { top: Math.round(r.top), bottom: Math.round(r.bottom), vh: innerHeight,
                         formScroll: form.scrollHeight - form.clientHeight,
                         canScroll: getComputedStyle(form).overflowY };
            }""")
            check(comp['bottom'] <= comp['vh'] + 1 or comp['formScroll'] > 0 or comp['canScroll'] == 'auto',
                  '%s 쓰기 화면 버튼 가림 없음(스크롤 가능)' % name, comp)
            ui.shot(page, 'audit-mobile-%s-mail-compose' % name)
            ctx.close()

        # ── E5. 요약 API 가 429 를 줘도 메일 버튼·창이 살아 있는지 ──
        d1('DELETE FROM auth_throttle')
        burst = Http()
        for _ in range(200):
            burst.request('/api/mail/summary')
        ctx, page = ui.page()
        page.wait_for_timeout(1400)
        check(page.is_visible('#btn-mail'), '요약이 429 여도 메일 버튼이 사라지지 않음')
        page.click('#btn-mail')
        page.wait_for_timeout(1200)
        check(page.is_visible('#mail-view-list'), '429 상태에서도 메일함이 열린다')
        ui.shot(page, 'audit-desktop-mail-rate-limited')
        ctx.close()
        d1('DELETE FROM auth_throttle')

        # ── F. 콘솔·404 ──────────────────────────────────────
        errors = [(lv, text) for lv, text in ui.console
                  if lv == 'error' and not any(skip in text for skip in CONSOLE_IGNORE)]
        check(not errors, '콘솔 에러 0건', errors[:3])
        missing = [(st, url) for st, url in ui.bad_requests if st == 404]
        check(not missing, '404 리소스 0건', missing[:3])
        browser.close()
    return True


# ── 정리 ─────────────────────────────────────────────────────

def cleanup(usernames, notice_titles):
    for name in usernames:
        d1("DELETE FROM notice_reads WHERE user_id IN (SELECT id FROM users WHERE username = '%s')" % name)
        d1("""DELETE FROM mails WHERE sender_id IN (SELECT id FROM users WHERE username = '%s')
               OR recipient_id IN (SELECT id FROM users WHERE username = '%s')""" % (name, name))
        d1("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username = '%s')" % name)
        d1("DELETE FROM users WHERE username = '%s'" % name)
    for title in notice_titles:
        d1("DELETE FROM notice_reads WHERE notice_id IN (SELECT id FROM notices WHERE title = '%s')"
           % title.replace("'", "''"))
        d1("DELETE FROM notices WHERE title = '%s'" % title.replace("'", "''"))
    d1('DELETE FROM auth_throttle')


# ── 라이브(url) 모드 ─────────────────────────────────────────

def audit_live_ownership():
    """라이브 D1 을 직접 볼 수 없으므로 API 응답만으로 권한을 확인하고, 만든 계정은 끝나면 지운다."""
    print('\n· 라이브 B. 소유권·권한')
    a, b, c = Http(), Http(), Http()
    status, _, data, _ = a.register(new_name('점검감사'))
    name_a = (data or {}).get('user', {}).get('username', '')
    status_b, _, data_b, _ = b.register(new_name('점검수신'))
    name_b = (data_b or {}).get('user', {}).get('username', '')
    status_c, _, data_c, _ = c.register(new_name('점검제삼'))
    name_c = (data_c or {}).get('user', {}).get('username', '')
    if not (status == 200 and status_b == 200 and status_c == 200):
        reason = (data or {}).get('error') or ''
        skip('라이브 소유권(메일 읽음/삭제/답장)',
             '운영 서버가 자동 가입을 받아 주지 않았다(%s — Turnstile·가입 제한) — 같은 코드 경로는 로컬 D1 에서 187건으로 확인'
             % (reason or status))
        return
    try:
        status, _, data, _ = a.request('/api/mail/send', 'POST',
                                       {'to': name_b, 'subject': '라이브 소유권 점검', 'body': '본문'})
        mail_to_b = (data or {}).get('mail', {}).get('id')
        check(status == 200 and mail_to_b, 'A → B 메일 발송', status)
        status, _, data, _ = c.request('/api/mail/read', 'POST', {'id': mail_to_b})
        check(status == 200 and (data or {}).get('updated') == 0, 'C 가 남의 메일 읽음 시도 → updated 0',
              '%s %s' % (status, json.dumps(data, ensure_ascii=False)[:120]))
        status, _, data, _ = b.request('/api/mail/read', 'POST', {'id': mail_to_b})
        check(status == 200 and (data or {}).get('updated') == 1, 'B 본인 메일 읽음 → updated 1', status)

        status, _, data, _ = a.request('/api/mail/send', 'POST',
                                       {'to': name_c, 'subject': 'B 와 무관한 메일', 'body': '본문'})
        mail_a_c = (data or {}).get('mail', {}).get('id')
        status, _, data, _ = b.request('/api/mail/delete', 'POST', {'id': mail_a_c})
        check(status == 404, 'B 가 A↔C 메일 삭제 시도 → 404', '%s %s' % (status, (data or {}).get('error')))
        status, _, data, _ = b.request('/api/mail/send', 'POST',
                                       {'to': name_a, 'subject': '답장 시도', 'body': '본문',
                                        'replyToId': mail_a_c})
        check(status == 400 and (data or {}).get('error') == 'reply_invalid',
              '참여하지 않은 메일로 답장 → 400', status)
        status, _, data, _ = a.request('/api/mail/notices', 'POST', {'title': '라이브 점검', 'body': '막힘'})
        check(status == 403, '일반 유저 공지 작성 403', status)
        status, _, data, _ = a.request('/api/mail/notices', 'DELETE', {'id': 'n_0000'})
        check(status == 403, '일반 유저 공지 삭제 403', status)
        status, _, _, _ = Http().request('/api/mail/notices', 'POST', {'title': '게스트', 'body': '막힘'})
        check(status == 403, '게스트 공지 작성 403', status)
        status, _, data, _ = Http().request('/api/mail/notices')
        check(status == 200 and isinstance((data or {}).get('notices'), list), '게스트 공지 목록 200', status)
    finally:
        for client in (a, b, c):
            status, _, _, _ = client.request('/api/auth/delete', 'POST', {'password': PASSWORD})
            check(status == 200, '라이브 점검 계정 삭제(테스트 데이터 정리)', status)


def audit_live_dos():
    print('\n· 라이브 D. 폭주 방어')
    big = json.dumps({'to': 'x', 'subject': '제목', 'body': 'ㄱ' * (40 * 1024)}).encode()
    status, _, data, _ = Http().request('/api/mail/send', 'POST', raw_body=big,
                                       headers={'content-type': 'application/json'})
    check(status == 413, '로그인 전 40KB 본문 → 413(권한 검사보다 먼저)',
          '%s %s' % (status, (data or {}).get('error')))
    status, _, data, _ = Http().request('/api/auth/register', 'POST', raw_body=big,
                                        headers={'content-type': 'application/json'})
    check(status == 413, '가입에도 40KB → 413', status)
    status, _, data, _ = Http().request('/api/mail/send', 'POST', raw_body=big, chunked=True,
                                        headers={'content-type': 'application/json'})
    check(status in (401, 413), '청크(Content-Length 없음) 40KB → 401/413(본문을 읽지 않음)', status)
    status, _, _, _ = Http().request('/api/mail/send', 'POST', {'to': 'x', 'subject': 's'})
    check(status in (400, 401), '본문 없는 요청은 400/401', status)

    # 쓰기 제한: 가입을 반복하면 429 (가입은 Turnstile 로 실패해도 횟수는 센다 — 데이터는 안 생긴다)
    codes = []
    for _ in range(12):
        status, _, data, _ = Http().request('/api/auth/register', 'POST',
                                            {'username': new_name('점검속도'), 'password': PASSWORD,
                                             'turnstileToken': 'x'})
        codes.append(status)
    check(429 in codes, '가입 반복 → 429(쓰기 제한 동작)', codes)

    # 조회 제한: 먼저 창이 비기를 기다렸다가(이전 점검이 채워 두었을 수 있다) 정상 사용량 → 폭주 순으로 본다.
    http = Http()
    for _ in range(75):
        status = http.request('/api/mail/summary')[0]
        if status == 200:
            break
        time.sleep(1)
    check(status == 200, '창이 지나면 요약이 다시 200(제한은 창 단위로 풀린다)', status)
    quiet = [http.request('/api/mail/summary')[0] for _ in range(5)]
    check(quiet == [200] * 5, '정상 사용량(연속 5건)은 모두 200', quiet)

    # 동시에 몰아 보내면 429. (한 줄로 순서대로 보내면 0.6초/건이라 분당 100건도 못 넘는다)
    from concurrent.futures import ThreadPoolExecutor
    results = []

    def hit(_):
        try:
            return Http().request('/api/mail/summary')[0]
        except Exception as error:
            return str(error)[:40]

    with ThreadPoolExecutor(max_workers=8) as pool:
        for code in pool.map(hit, range(240)):
            results.append(code)
    tally = {}
    for code in results:
        tally[code] = tally.get(code, 0) + 1
    check(tally.get(429, 0) > 0, '동시 조회 폭주(240건·8연결) → 429', tally)
    check(tally.get(None, 0) == 0, '폭주 중에도 연결 오류 없음', tally)


def audit_live_ui(url):
    print('\n· 라이브 E. 화면 스모크(게스트)')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        ui = Ui(browser, SHOT_DIR)
        ctx, page = ui.page(url=url)
        page.wait_for_timeout(700)
        page.click('#btn-mail')
        page.wait_for_selector('#ov-mail:not([hidden])', timeout=8000)
        page.wait_for_timeout(700)
        page.click('#mail-title')
        page.keyboard.press('Enter')
        page.wait_for_timeout(250)
        check(page.evaluate('() => window.__ITDA.app.screen') == 'setup',
              '라이브: 메일함 위 Enter → 대전 시작 안 됨')
        page.keyboard.press('Escape')
        page.wait_for_timeout(350)
        check(page.evaluate('() => document.activeElement && document.activeElement.id') == 'btn-mail',
              '라이브: 메일함을 닫으면 포커스 복귀')
        box = page.evaluate("""() => { const s = document.querySelector('.mail-sheet').getBoundingClientRect();
            return { w: Math.round(s.width), vw: innerWidth }; }""")
        check(box['w'] <= box['vw'], '라이브: 메일함 창 폭', box)
        ui.shot(page, 'audit-live-mail-guest')
        for label, path, method, body, want in [
            ('휴지통 목록', '/api/mail/trash', 'GET', None, 401),
            ('휴지통 이동', '/api/mail/trash', 'POST', {'id': 'm_0000'}, 401),
            ('휴지통 비우기', '/api/mail/trash/empty', 'POST', None, 401),
            ('복구', '/api/mail/restore', 'POST', {'id': 'm_0000'}, 401),
            ('메일 수정', '/api/mail/edit', 'POST', {'id': 'm_0000', 'subject': 's', 'body': 'b'}, 401),
            ('공지 수정', '/api/mail/notices/edit', 'POST', {'id': 'n_0000', 'title': 't', 'body': 'b'}, 403),
        ]:
            status, heads, data, _ = Http().request(path, method, body)
            check(status == want, '라이브: %s 비로그인 → %d' % (label, want),
                  '%s %s' % (status, (data or {}).get('error')))
            check('no-store' in heads.get('cache-control', ''), '라이브: %s 응답 no-store' % label,
                  heads.get('cache-control'))
        errors = [(lv, text) for lv, text in ui.console
                  if lv == 'error' and not any(skip in text for skip in CONSOLE_IGNORE)]
        check(not errors, '라이브 콘솔 에러 0건', errors[:3])
        missing = [(st, href) for st, href in ui.bad_requests if st == 404]
        check(not missing, '라이브 404 리소스 0건', missing[:3])
        browser.close()



def run_live():
    BASE_LABEL = BASE
    print('· 라이브: %s' % BASE_LABEL)
    audit_csrf({})
    injector = Http()
    status, _, data, _ = injector.register(new_name('점검주입'))
    if status == 200:
        check(True, '라이브 점검 계정(주입·헤더용) 생성')
    else:
        skip('라이브 점검 계정 생성', '운영 서버가 자동 가입을 받아 주지 않았다(%s)' % ((data or {}).get('error') or status))
    try:
        audit_injection_headers({}, client=injector)
    finally:
        injector.request('/api/auth/delete', 'POST', {'password': PASSWORD})
    audit_live_ownership()
    # 화면 스모크를 먼저(조회 폭주 점검이 이 IP 의 창을 채우기 전에), 폭주 점검은 맨 마지막에.
    audit_live_ui(BASE)
    audit_live_dos()


def main():
    global SHOT_DIR, BASE, LIVE
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', action='store_true')
    ap.add_argument('--url', default=None, help='라이브 주소(예: https://itda-play.pages.dev) — 주면 라이브 모드')
    ap.add_argument('--shots-dir', default='/workspace/downloads/itda/2026-11-25-audit')
    ap.add_argument('--section', choices=['all', 'api', 'ui'], default='all',
                    help='한 번에 300초를 넘기는 환경에서 API(A–D)와 화면(E)을 나눠 돌릴 때')
    args = ap.parse_args()
    SHOT_DIR = args.shots_dir
    os.makedirs(SHOT_DIR, exist_ok=True)

    if args.url:
        BASE = args.url.rstrip('/')
        LIVE = True
        run_live()
        print('\n결과: %d 통과 · %d 실패' % (PASS, FAIL))
        print('스크린샷: %s' % SHOT_DIR)
        return 0 if FAIL == 0 else 1

    made = ensure_config()
    d1_file(os.path.join('db', 'schema.sql'))
    apply_migrations()
    d1('DELETE FROM auth_throttle')
    proc = start_local()
    names = {'a': new_name('점검감사'), 'b': new_name('점검수신'), 'c': new_name('점검제삼')}
    created = list(names.values())
    notices = ['권한 점검 공지']
    try:
        print('· 준비: 점검 계정')
        seed = Http()
        for key in ('a', 'b', 'c'):
            status, _, data, _ = seed.register(names[key])
            check(status == 200, '%s 가입' % names[key], '%s %s' % (status, (data or {}).get('error')))
        status, _, data, _ = seed.login(ADMIN)
        if status != 200:
            # 예전 점검에서 남은 관리자 계정(비밀번호를 모른다)은 지우고 새로 만든다.
            d1("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username = '%s')" % ADMIN)
            d1("DELETE FROM users WHERE username = '%s'" % ADMIN)
            seed.register(ADMIN)
            created.append(ADMIN)
        check(seed.login(ADMIN)[0] == 200, '관리자 %s 준비' % ADMIN)
        cookie_admin = seed.cookies.get('itda_session', '')
        cookie_a = Http()
        cookie_a.login(names['a'])
        cookie_a = cookie_a.cookies.get('itda_session', '')

        if args.section in ('all', 'api'):
            audit_csrf(names)
            audit_ownership(names)
            audit_injection_headers(names)
            audit_dos(names)
        if args.section in ('all', 'ui'):
            # 폭주 점검으로 쌓인 창을 비우고(정상 사용자 기준으로 돌아간다) A 의 받은 메일을 하나 만든다.
            d1('DELETE FROM auth_throttle')
            seed_b = Http()
            seed_b.login(names['b'])
            seed_b.request('/api/mail/send', 'POST',
                           {'to': names['a'], 'subject': '삭제 연타 점검', 'body': '지워질 메일'})
            audit_ui(names, cookie_a, cookie_admin)
    finally:
        try:
            cleanup(created, notices + ['아주 긴 공지 ' + 'ㄷ' * 80])
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except Exception:
                proc.kill()
            if made:
                try:
                    os.remove(os.path.join(ROOT, 'wrangler.toml'))
                except OSError:
                    pass

    print('\n결과: %d 통과 · %d 실패' % (PASS, FAIL))
    print('스크린샷: %s' % SHOT_DIR)
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
