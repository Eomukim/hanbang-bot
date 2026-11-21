import functools, http.server, os, socketserver, threading, json
from playwright.sync_api import sync_playwright

ROOT='/workspace/work/kkutu-killer'
h=functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
s=socketserver.ThreadingTCPServer(('127.0.0.1',0),h); s.daemon_threads=True
port=s.server_address[1]; threading.Thread(target=s.serve_forever,daemon=True).start()

with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/workspace/.local/pw/chromium-1255/chrome-linux64/chrome',args=['--no-sandbox'])
    pg=b.new_page(viewport={'width':390,'height':844}, device_scale_factor=2)
    pg.goto(f'http://127.0.0.1:{port}/index.html')
    pg.wait_for_function('window.__KK && window.__KK.ready', timeout=60000)
    # simulate: quick game end then new game
    pg.evaluate("window.__KK.startGame({level:4, first:'me', startChar:'가'})")
    pg.wait_for_timeout(400)
    pg.fill('#word-input','가가'); pg.click('#btn-submit')
    pg.wait_for_timeout(3200)
    print('after end overlays', pg.evaluate("""() => [...document.querySelectorAll('.overlay')].map(o => ({id:o.id, hidden:o.hidden, op:getComputedStyle(o).opacity, disp:getComputedStyle(o).display}))"""))
    pg.evaluate("window.__KK.app.hideResult(); window.__KK.app.show('setup')")
    pg.evaluate("window.__KK.startGame({level:1, first:'bot'})")
    pg.wait_for_timeout(2500)
    print('new game overlays', pg.evaluate("""() => [...document.querySelectorAll('.overlay')].map(o => ({id:o.id, hidden:o.hidden, op:getComputedStyle(o).opacity, disp:getComputedStyle(o).display}))"""))
    print('screens', pg.evaluate("""() => [...document.querySelectorAll('.screen')].map(o => ({id:o.id, hidden:o.hidden, disp:getComputedStyle(o).display, op:getComputedStyle(o).opacity}))"""))
    print('elements at 200,300', pg.evaluate("""() => document.elementsFromPoint(200,300).slice(0,6).map(e=>e.id||e.className||e.tagName)"""))
    pg.screenshot(path='/workspace/work/kkutu-killer/downloads/debug-ghost.png')
    b.close()
s.shutdown()
