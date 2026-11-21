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
    .replace(/\s+/g, '')
    .trim();
}

export const ERR = {
  EMPTY: { code: 'empty', message: '단어를 입력해 주세요.' },
  TOO_SHORT: { code: 'short', message: '두 글자 이상이어야 해요.' },
  NOT_HANGUL: { code: 'hangul', message: '한글로 된 단어만 쓸 수 있어요.' },
  WRONG_START: { code: 'start', message: '이어야 할 글자로 시작해야 해요.' },
  NOT_FOUND: { code: 'notfound', message: '사전에 없는 단어예요. 내 단어장에 추가할 수 있어요.' },
  USED: { code: 'used', message: '이미 나온 단어예요.' },
};
