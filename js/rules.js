/** 끝말잇기 규칙: 한글 음절 분해와 두음법칙. */

const BASE = 0xac00;
const CHOSEONG = 19;
const JUNGSEONG = 21;
const JONGSEONG = 28;
const RIEUL = 5;
const NIEUN = 2;
const IEUNG = 11;

/**
 * 중성 순서: ㅏ0 ㅐ1 ㅑ2 ㅒ3 ㅓ4 ㅔ5 ㅕ6 ㅖ7 ㅗ8 ㅘ9 ㅙ10 ㅚ11
 *             ㅛ12 ㅜ13 ㅝ14 ㅞ15 ㅟ16 ㅠ17 ㅡ18 ㅢ19 ㅣ20
 * ㄹ·ㄴ 뒤에서 ㅇ으로 바뀌는 모음: ㅑ ㅒ ㅕ ㅖ ㅛ ㅠ ㅣ
 */
const I_VOWELS = new Set([2, 3, 6, 7, 12, 17, 20]);

export const HANGUL_ONLY = /^[가-힣]+$/;

/**
 * 낼 수 있는 단어: 한글로 시작해 한글로 끝나고, 중간에는 한글·숫자·영문자를 쓸 수 있다.
 * 끄코 오픈DB에는 `가락1동`, `…볼륨3코스믹어벤저스`, 71글자 `너바나더밴드…17년전으로돌`
 * 처럼 숫자가 섞인 표제어가 1만여 개 있고, 끄투코리아에서도 그대로 쓰는 단어다.
 * (첫·끝 글자가 한글이어야 하는 이유: 다음 차례는 늘 끝 글자로 이어가고, 사전 구간도
 *  시작 글자로 나눠 두었기 때문이다.)
 */
export const WORD_PATTERN = /^[가-힣][가-힣0-9A-Za-z]*[가-힣]$/;

/** 제로폭 문자(복사·붙여넣기에서 섞여 들어오는 보이지 않는 글자) */
const ZERO_WIDTH = /[\u200b-\u200f\u2060\ufeff]/g;
/** 전각 영숫자(U+FF10~FF19, FF21~FF3A, FF41~FF5A) → 반각 */
const FULLWIDTH_ALNUM = /[\uff10-\uff19\uff21-\uff3a\uff41-\uff5a]/g;

/** 음절 하나를 초성·중성·종성으로 나눈다. 한글이 아니면 null. */
export function decompose(ch) {
  const k = ch.charCodeAt(0) - BASE;
  if (k < 0 || k >= CHOSEONG * JUNGSEONG * JONGSEONG) return null;
  return [Math.floor(k / (JUNGSEONG * JONGSEONG)), Math.floor((k % (JUNGSEONG * JONGSEONG)) / JONGSEONG), k % JONGSEONG];
}

export function compose(cho, jung, jong) {
  return String.fromCharCode(BASE + (cho * JUNGSEONG + jung) * JONGSEONG + jong);
}

/**
 * 표준 두음법칙을 적용한 대체 음절.
 *  ㄹ + ㅑㅒㅕㅖㅛㅠㅣ → ㅇ  (리→이, 료→요)
 *  ㄹ + 그 밖의 모음    → ㄴ  (라→나, 로→노)
 *  ㄴ + ㅑㅒㅕㅖㅛㅠㅣ → ㅇ  (녀→여, 니→이)
 * 해당 없으면 null.
 */
export function twoeumOf(ch) {
  if (ch.length !== 1) return null;
  const parts = decompose(ch);
  if (!parts) return null;
  const [cho, jung, jong] = parts;
  if (cho === RIEUL) {
    return compose(I_VOWELS.has(jung) ? IEUNG : NIEUN, jung, jong);
  }
  if (cho === NIEUN && I_VOWELS.has(jung)) {
    return compose(IEUNG, jung, jong);
  }
  return null;
}

/** 이 글자로 시작해도 되는 음절 목록 (원래 글자 + 두음 변환 글자). */
export function allowedStarts(ch) {
  const alt = twoeumOf(ch);
  return alt && alt !== ch ? [ch, alt] : [ch];
}

export function normalizeWord(raw) {
  return String(raw || '')
    .normalize('NFC')
    .replace(ZERO_WIDTH, '')
    .replace(FULLWIDTH_ALNUM, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/\s+/g, '')
    .trim();
}

/** 미션 글자 후보: 실제 끝말잇기 미션과 같은 14종. */
export const MISSION_CHARS = ['가', '나', '다', '라', '마', '바', '사', '아', '자', '차', '카', '타', '파', '하'];

/** 단어 안에 미션 글자가 몇 번 들어 있는지. */
export function missionHits(word, ch) {
  if (!ch) return 0;
  let n = 0;
  for (const c of String(word || '')) if (c === ch) n += 1;
  return n;
}

/** 중첩 배수: 0회 1 · 1회 1.5(+50%) · 2회 ×2 · 3회 ×3 … 겹친 만큼 커진다. */
export function missionMultiplier(hits) {
  if (hits <= 0) return 1;
  return hits === 1 ? 1.5 : hits;
}

export const ERR = {
  EMPTY: { code: 'empty', message: '단어를 입력해 주세요.' },
  TOO_SHORT: { code: 'short', message: '두 글자 이상이어야 해요.' },
  NOT_HANGUL: { code: 'hangul', message: '한글로 시작하고 한글로 끝나는 단어만 쓸 수 있어요.' },
  WRONG_START: { code: 'start', message: '이어야 할 글자로 시작해야 해요.' },
  NOT_FOUND: { code: 'notfound', message: '사전에 없는 단어예요.' },
  USED: { code: 'used', message: '이미 나온 단어예요.' },
};
