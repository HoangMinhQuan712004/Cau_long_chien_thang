// T-076 / ADR-015: service worker CHỈ để nhận thông báo đẩy (Web Push).
// - Không có `fetch` handler, không cache trang hay API (AC24): trang public giữ nguyên SEO, đăng xuất rồi Back không hiện dữ liệu cũ.
// - Payload từ server: { title, body, url, tag? }. Bấm thông báo chỉ mở đường dẫn cùng domain bắt đầu bằng "/" (AC21).

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

/** Chỉ nhận "/đường-dẫn" cùng domain; "//host", "/\host" hay URL đầy đủ ⇒ trang chủ. */
function safePath(value) {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\") ? value : "/";
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  const title = typeof data.title === "string" && data.title ? data.title : "Chiến Thắng";
  const options = {
    body: typeof data.body === "string" ? data.body : "",
    icon: "/pwa-icon/192",
    badge: "/pwa-icon/192",
    data: { url: safePath(data.url) },
  };
  // Cùng tag ⇒ thông báo mới thay thông báo cũ (vd. đổi giờ hai lần cho một buổi vẫn là hai lần báo, server tự chọn tag)
  if (typeof data.tag === "string" && data.tag) options.tag = data.tag;
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(safePath(event.notification.data && event.notification.data.url), self.location.origin).href;
  event.waitUntil(
    (async () => {
      // App / tab đang mở ⇒ chuyển tới trang đó; chưa mở ⇒ mở mới
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        await client.focus();
        try {
          await client.navigate(target);
        } catch {
          // tab chưa do SW này điều khiển ⇒ mở cửa sổ mới
          await self.clients.openWindow(target);
        }
        return;
      }
      await self.clients.openWindow(target);
    })(),
  );
});
