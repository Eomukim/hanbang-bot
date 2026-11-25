/**
 * POST /api/account/profile
 * 내 닉네임과 프로필 사진을 바꾼다. 로그인한 본인만, 자기 행만 바꾼다.
 *
 * body (하나 이상):
 *   - nickname: 1~16자(앞뒤 공백 정리, 제어문자·제로폭 글자 금지)
 *   - avatar:   `data:image/(png|jpeg|webp);base64,...` Data URL (문자열 28KB·이미지 20KB 이하)
 *   - removeAvatar: true 이면 사진을 지우고 글자 아바타로 되돌린다
 *
 * 아이디(`@username`)는 로그인·검색의 고유 식별자라 여기서 바꾸지 않는다.
 * 사진은 화면(js/account.js)이 160×160 정사각 WebP/JPEG 로 줄여 보내고, 서버는 형식과
 * 실제 파일 머리(매직바이트)를 다시 확인한다 — SVG·HTML·스크립트는 저장되지 않는다.
 */
import {
  ok,
  fail,
  readJson,
  currentSession,
  publicUser,
  hitThrottle,
  clientIp,
} from '../../_lib/auth.js';
import { validateNickname, validateAvatar } from '../../_lib/social.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '계정 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인한 상태에서만 프로필을 바꿀 수 있어요.');

  const ip = clientIp(request) || 'unknown';
  const perIp = await hitThrottle(env, `profile:ip:${ip}`, 60, 600);
  if (!perIp.allowed) {
    return fail(429, 'rate_limited', '프로필을 너무 자주 바꾸고 있어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(perIp.retryAfter),
    });
  }
  const perUser = await hitThrottle(env, `profile:u:${session.id}`, 20, 600);
  if (!perUser.allowed) {
    return fail(429, 'rate_limited', '프로필을 너무 자주 바꾸고 있어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(perUser.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const sets = [];
  const binds = [];
  const changed = {};

  if (body.nickname !== undefined) {
    const checked = validateNickname(body.nickname);
    if (!checked.ok) return fail(400, checked.error, checked.message);
    sets.push('nickname = ?');
    binds.push(checked.nickname);
    changed.nickname = checked.nickname;
  }

  const removeAvatar = body.removeAvatar === true;
  if (removeAvatar && body.avatar !== undefined) {
    return fail(400, 'avatar_conflict', '사진을 지울지 바꿀지 하나만 골라 주세요.');
  }
  if (removeAvatar) {
    sets.push('avatar_data = NULL', 'avatar_updated_at = ?');
    binds.push(Date.now());
    changed.avatarRemoved = true;
  } else if (body.avatar !== undefined) {
    const checked = validateAvatar(body.avatar);
    if (!checked.ok) return fail(400, checked.error, checked.message);
    sets.push('avatar_data = ?', 'avatar_updated_at = ?');
    binds.push(body.avatar, Date.now());
    changed.avatarUpdated = true;
  }

  if (!sets.length) {
    return fail(400, 'nothing_to_change', '바꿀 내용이 없어요.');
  }

  sets.push('updated_at = ?');
  binds.push(new Date().toISOString());
  await env.DB.prepare(`UPDATE users SET ${sets.join(', ')} WHERE id = ?`)
    .bind(...binds, session.id).run();

  const row = await env.DB.prepare(
    `SELECT id, username, display_name, nickname, avatar_updated_at, google_sub, created_at
       FROM users WHERE id = ?`,
  ).bind(session.id).first();
  if (!row) return fail(404, 'not_found', '계정을 찾지 못했어요.');

  return ok({ user: publicUser(row), changed });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'POST' });
}
