/** 4단계 봇. 난이도마다 단어를 고르는 방식과 반응이 다르다. */

export const LEVELS = [
  {
    id: 1,
    name: '쉬움',
    face: '🙂',
    label: 'Lv.1 순한 봇',
    desc: '한방 단어는 절대 안 씀 · 쉬운 2~3글자',
    botName: '킬러봇 주니어',
  },
  {
    id: 2,
    name: '보통',
    face: '😐',
    label: 'Lv.2 보통',
    desc: '가끔 긴 단어 · 초반엔 한방 금지',
    botName: '킬러봇',
  },
  {
    id: 3,
    name: '어려움',
    face: '😏',
    label: 'Lv.3 어려움',
    desc: '외통수로 몰아넣고 결정타',
    botName: '킬러봇 X',
  },
  {
    id: 4,
    name: '지옥',
    face: '😈',
    label: 'Lv.4 즉사',
    desc: '한방 단어가 있으면 100% 즉사',
    botName: '한방 킬러',
  },
];

export function levelInfo(level) {
  return LEVELS.find((l) => l.id === level) || LEVELS[1];
}

const LINES = {
  1: {
    start: ['시작해요! 어렵지 않게 갈게요.', '끝말잇기 좋아해요. 가볍게 해요!'],
    good: ['오, 그 단어 알아요!', '좋아요, 계속해 봐요.', '음… 생각했어요.'],
    long: ['긴 단어네요! 대단해요.', '와, 그건 몰랐어요.'],
    combo: ['계속 맞히시네요…', '저 좀 도와주세요…'],
    bad: ['어? 그건 사전에 없어요.', '앗, 다시 해봐요!'],
    blocked: ['앗… 제가 막혔어요.', '단어가 안 떠올라요…'],
    win: ['제가 이겼어요!', '이겼다!'],
    lose: ['졌어요… 다음엔 더 잘할게요.'],
    timeout: ['시간이 다 됐어요…'],
  },
  2: {
    start: ['좋아, 시작하지.', '한 판 붙자고.'],
    good: ['나쁘지 않은데.', '그 정도야 뭐.', '계속 가 보자.'],
    long: ['긴 걸 갖고 왔네.', '제법인데.'],
    combo: ['흐름을 타고 있네.', '슬슬 집중해야겠어.'],
    bad: ['그건 없어.', '사전을 다시 봐.'],
    blocked: ['…막혔나?', '여기서 막히면 안 되는데.'],
    win: ['내 승리야.', '이번엔 나였다.'],
    lose: ['…인정하지.', '한 수 배웠네.'],
    timeout: ['시간 초과. 게임 끝이야.'],
  },
  3: {
    start: ['어디, 얼마나 버티는지 볼까.', '시작해 볼까.'],
    good: ['예상했어.', '그걸 피해 가네.', '아직이야.'],
    long: ['길게 가는군.', '좋아, 그 길로 가자.'],
    combo: ['제법인데? 슬슬 위험해.', '흐름 좋네. 곧 끊길 거야.'],
    bad: ['그건 안 돼.', '아깝게 빗나갔네.'],
    blocked: ['…여기서 막혔어? 아쉽네.', '막혔네.'],
    win: ['예정된 결말이야.', '내가 이겼어.'],
    lose: ['…이건 예상 밖이네.', '네가 한 수 위였어.'],
    timeout: ['시간이 없어. 끝.'],
  },
  4: {
    start: ['시작해. 오래 버텨 봐.', '한 방이면 충분해.', '준비됐어?'],
    good: ['…그 정도?', '한 번 더.'],
    long: ['길어도 소용없어.', '그래서?'],
    combo: ['재밌어. 곧 끝나.'],
    bad: ['틀렸어.', '그런 단어는 없어.'],
    blocked: ['막혔지.', '끝이야.'],
    oneShot: ['한방.', '끝.', '이게 지옥이야.', '잘 가.'],
    win: ['다음엔 오지 마.', '한 방이면 충분했지.'],
    lose: ['…말이 안 되는데.', '…….'],
    timeout: ['시간. 끝.'],
  },
};

export function botLine(level, event, rng = Math.random) {
  const table = LINES[level] || LINES[2];
  const list = table[event];
  if (!list || !list.length) return '';
  return list[Math.floor(rng() * list.length)];
}

const pick = (arr, rng) => arr[Math.floor(rng() * arr.length)];

const delayBetween = (a, b, rng) => a + rng() * (b - a);

export class Bot {
  constructor({ level, dict, rng = Math.random }) {
    this.level = level;
    this.dict = dict;
    this.rng = rng;
  }

  /**
   * @returns {{word: string, delay: number, kind: string} | null}
   */
  choose({ needChar, used, turn }) {
    const cands = this.dict.candidatesFor(needChar, used);
    if (!cands.length) return null;
    const dict = this.dict;
    const rng = this.rng;
    const endCount = (w) => dict.countFrom(w.charAt(w.length - 1));
    const oneShot = cands.filter((w) => endCount(w) === 0);

    if (this.level === 4) {
      if (oneShot.length) {
        return { word: pick(oneShot, rng), delay: delayBetween(200, 480, rng), kind: 'oneshot' };
      }
      // 한방이 없으면: 상대가 받아치기 가장 어려운 최소 후속 단어, 길이 우선
      let best = null;
      let bestKey = Infinity;
      for (const w of cands) {
        const key = endCount(w) * 100 - w.length;
        if (key < bestKey) {
          bestKey = key;
          best = w;
        }
      }
      return { word: best, delay: delayBetween(200, 500, rng), kind: 'outer' };
    }

    if (this.level === 3) {
      if (turn >= 4 && oneShot.length && rng() < 0.85) {
        return { word: pick(oneShot, rng), delay: delayBetween(700, 1300, rng), kind: 'oneshot' };
      }
      const induced = cands.filter((w) => {
        const n = endCount(w);
        return n >= 1 && n <= 3;
      });
      if (induced.length && rng() < 0.7) {
        return { word: pick(induced, rng), delay: delayBetween(700, 1400, rng), kind: 'press' };
      }
      const tough = cands.filter((w) => {
        const n = endCount(w);
        return n > 0 && n <= 30;
      });
      const pool = tough.length ? tough : cands.filter((w) => endCount(w) > 0);
      return { word: pick(pool.length ? pool : cands, rng), delay: delayBetween(750, 1400, rng), kind: 'press' };
    }

    if (this.level === 2) {
      if (turn > 3 && oneShot.length && rng() < 0.1) {
        return { word: pick(oneShot, rng), delay: delayBetween(1000, 1700, rng), kind: 'oneshot' };
      }
      const longWords = cands.filter((w) => w.length >= 4 && endCount(w) > 5);
      if (longWords.length && rng() < 0.22) {
        return { word: pick(longWords, rng), delay: delayBetween(1000, 1800, rng), kind: 'long' };
      }
      const easy = cands.filter((w) => w.length <= 3 && endCount(w) >= 25);
      const pool = easy.length ? easy : cands.filter((w) => endCount(w) > 0);
      return {
        word: pick(pool.length ? pool : cands, rng),
        delay: delayBetween(1000, 1800, rng),
        kind: 'normal',
      };
    }

    // 레벨 1: 한방 금지, 후속 단어가 많은 2~3글자
    const safe = cands.filter((w) => {
      const n = endCount(w);
      return n >= 40 && w.length <= 3;
    });
    if (safe.length) return { word: pick(safe, rng), delay: delayBetween(1500, 2500, rng), kind: 'normal' };

    const safer = cands.filter((w) => {
      const n = endCount(w);
      return n >= 15 && w.length <= 4;
    });
    if (safer.length) return { word: pick(safer, rng), delay: delayBetween(1500, 2500, rng), kind: 'normal' };

    const notDead = cands.filter((w) => endCount(w) > 0);
    return {
      word: pick(notDead.length ? notDead : cands, rng),
      delay: delayBetween(1500, 2500, rng),
      kind: 'normal',
    };
  }
}
