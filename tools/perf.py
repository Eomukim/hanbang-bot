"""성능 측정: 사전 로드, 판정, 봇 결정 시간."""
import functools, http.server, socketserver, threading, json
from playwright.sync_api import sync_playwright

ROOT = '/workspace/work/hanbang-bot'
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
s = socketserver.ThreadingTCPServer(('127.0.0.1', 0), h); s.daemon_threads = True
port = s.server_address[1]
threading.Thread(target=s.serve_forever, daemon=True).start()

with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/workspace/.local/pw/chromium-1255/chrome-linux64/chrome', args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 390, 'height': 844})
    t0 = pg.evaluate('performance.now()') if False else None
    pg.goto(f'http://127.0.0.1:{port}/index.html', wait_until='domcontentloaded')
    pg.wait_for_function('window.__HB && window.__HB.ready', timeout=90000)
    print('load timing:', pg.evaluate("""() => {
        const nav = performance.getEntriesByType('navigation')[0];
        const res = performance.getEntriesByType('resource').map(r => ({n: r.name.split('/').pop(), d: Math.round(r.duration), size: r.transferSize}));
        return {dom: Math.round(nav.domContentLoadedEventEnd), words: res.find(r=>r.n==='words.txt'), stats: res.find(r=>r.n==='stats.json')};
    }"""))

    print('validate x2000:', pg.evaluate("""() => {
        const d = window.__HB.dict;
        const words = d.candidatesFor('가', new Set()).slice(0, 2000);
        const t = performance.now();
        let ok = 0;
        for (const w of words) if (d.has(w)) ok++;
        return {ms: +(performance.now() - t).toFixed(1), n: words.length, ok};
    }"""))

    print('bot choose x50:', pg.evaluate("""async () => {
        const d = window.__HB.dict;
        const m = await import('./js/bot.js');
        const out = {};
        for (const lv of [1,2,3,4]) {
            const bot = new m.Bot({level: lv, dict: d});
            const used = new Set();
            const t = performance.now();
            let n = 0, one = 0;
            for (let i = 0; i < 50; i++) {
                const mv = bot.choose({needChar: '가', used, turn: 5});
                if (mv) { n++; if (d.isOneShot(mv.word)) one++; }
            }
            out['lv'+lv] = {msAvg: +((performance.now() - t) / 50).toFixed(3), n, one};
        }
        return out;
    }"""))

    print('turns:', pg.evaluate("""() => ({oneShot: window.__HB.dict.stats.oneShotCount, induced: window.__HB.dict.stats.inducedCount, total: window.__HB.dict.size, starts: window.__HB.dict.stats.starts})"""))
    b.close()
s.shutdown()
