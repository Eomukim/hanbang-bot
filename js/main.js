/** 진입점: 사전을 불러오고 앱을 붙인다. */

import { Dictionary } from './data.js';
import { App } from './ui.js';
import { Sfx } from './audio.js';
import { loadSettings, loadCustom, loadRecord } from './store.js';

async function boot() {
  const settings = loadSettings();
  const custom = loadCustom();
  const record = loadRecord();
  const sfx = new Sfx(settings.sound);

  const dict = new Dictionary();
  dict.setCustom(custom);

  const app = new App({ dict, settings, custom, record, sfx });
  app.mount();
  app.show('loading');

  try {
    await dict.load({
      onProgress: ({ ratio, words }) => app.setProgress(ratio, words),
    });
  } catch (error) {
    app.showLoadError(
      `단어 사전을 불러오지 못했습니다.\n${error?.message || error}\n네트워크를 확인한 뒤 새로고침해 주세요.`,
    );
    return;
  }

  app.el['dict-count'].textContent = dict.size.toLocaleString('ko-KR');
  app.show('setup');

  // 검증·자동화용 손잡이
  window.__KK = {
    app,
    dict,
    get engine() { return app.engine; },
    startGame: (opts) => app.startGame(opts || {}),
    submit: (word) => app.engine?.playMe(word),
    state: () => app.engine?.snapshot() ?? null,
    ready: true,
  };
}

boot();
