/* ===== Admin Session Guard =====
 * 用在 admin.html <head> 里，同步执行（早于 admin.js）。
 * 未登录或会话过期则跳 login.html。
 * 会话信息由 scripts/auth.js 写入 localStorage['cm_auth']。
 */

(function guard() {
  try {
    const raw = localStorage.getItem("cm_auth");
    if (!raw) throw new Error("no session");
    const payload = JSON.parse(raw);
    if (!payload || typeof payload.expires_at !== "number") throw new Error("bad session");
    if (Date.now() > payload.expires_at) {
      localStorage.removeItem("cm_auth");
      throw new Error("session expired");
    }
    // ok — 可在 window 上暴露供 admin.js 读用户名
    window.__cmAuth = payload;
  } catch (e) {
    // 跳登录页，避免在未授权状态下先渲染出 admin 骨架
    const back = encodeURIComponent(location.pathname + location.search);
    location.replace("login.html?back=" + back);
  }
})();

function cmLogout() {
  try {
    localStorage.removeItem("cm_auth");
  } catch (e) {
    // ignore
  }
  location.replace("login.html");
}
