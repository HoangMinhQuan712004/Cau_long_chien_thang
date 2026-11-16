// T-076 / ADR-015: thông báo đẩy (Web Push) trên thiết bị này – phát hiện hỗ trợ, bật, tắt, gửi thử, gỡ khi đăng xuất.
// API: GET /push/config, POST + DELETE /push/subscriptions, POST /push/test (kiểu sinh từ schema.d.ts).

import { api, errorMessage } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type PushConfig = components["schemas"]["PushConfig"];

/**
 * `ok`: bật được ngay · `ios-install`: iPhone/iPad mở bằng Safari chưa thêm vào màn hình chính, hoặc iOS < 16.4 (AC2)
 * · `unsupported`: trình duyệt không có Push API.
 */
export type PushSupport = "ok" | "ios-install" | "unsupported";

export function pushSupport(): PushSupport {
  if (typeof window === "undefined") return "unsupported";
  const ua = navigator.userAgent;
  // iPadOS 13+ báo là "Macintosh" nhưng có cảm ứng
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const hasApi = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (isIOS) {
    const standalone = window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
    const m = ua.match(/OS (\d+)_(\d+)/);
    const tooOld = m ? Number(m[1]) * 100 + Number(m[2]) < 1604 : false;
    return standalone && !tooOld && hasApi ? "ok" : "ios-install";
  }
  return hasApi ? "ok" : "unsupported";
}

let configPromise: Promise<PushConfig | null> | null = null;

/** Cấu hình push (một lần mỗi lượt tải trang). Lỗi mạng ⇒ null (coi như tắt, không hiện nút). */
export function getPushConfig(): Promise<PushConfig | null> {
  configPromise ??= api
    .GET("/api/v1/push/config")
    .then(({ data }) => (data && typeof data.enabled === "boolean" ? data : null))
    .catch(() => null);
  return configPromise;
}

async function existingRegistration(): Promise<ServiceWorkerRegistration | undefined> {
  if (!("serviceWorker" in navigator)) return undefined;
  return navigator.serviceWorker.getRegistration("/");
}

/** Đăng ký đẩy hiện có của trình duyệt này (không đăng ký SW mới). */
export async function currentSubscription(): Promise<PushSubscription | null> {
  try {
    const reg = await existingRegistration();
    return (await reg?.pushManager.getSubscription()) ?? null;
  } catch {
    return null;
  }
}

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob((value + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/** Tên máy ngắn cho danh sách thiết bị (không chứa thông tin cá nhân). */
function deviceLabel(): string {
  const ua = navigator.userAgent;
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad|Macintosh/.test(ua) && navigator.maxTouchPoints > 1 ? "iPad" : /Android/.test(ua) ? "Android" : /Windows/.test(ua) ? "Windows" : /Mac/.test(ua) ? "Mac" : "Máy khác";
  const browser = /Edg\//.test(ua) ? "Edge" : /CriOS|Chrome\//.test(ua) ? "Chrome" : /Firefox|FxiOS/.test(ua) ? "Firefox" : /Safari/.test(ua) ? "Safari" : "";
  return browser ? `${os} · ${browser}` : os;
}

/** Gửi đăng ký lên server (201 mới / 200 đã có ⇒ chuyển sang tài khoản đang đăng nhập). */
async function saveSubscription(sub: PushSubscription): Promise<{ ok: true } | { ok: false; message: string }> {
  const json = sub.toJSON();
  const p256dh = json.keys?.p256dh;
  const auth = json.keys?.auth;
  if (!json.endpoint || !p256dh || !auth) return { ok: false, message: "Thiết bị này không hỗ trợ nhận thông báo." };
  try {
    const { error, response } = await api.POST("/api/v1/push/subscriptions", {
      body: { endpoint: json.endpoint, keys: { p256dh, auth }, device_label: deviceLabel() },
    });
    if (response.ok) return { ok: true };
    return { ok: false, message: errorMessage(error, "Không bật được thông báo, vui lòng thử lại.") };
  } catch {
    return { ok: false, message: "Không kết nối được máy chủ, vui lòng thử lại." };
  }
}

export type EnableResult = { ok: true } | { ok: false; reason: "denied" | "dismissed" | "error"; message?: string };

/**
 * Bật trên máy này. PHẢI gọi trực tiếp trong sự kiện bấm (iOS chỉ hỏi quyền khi người dùng bấm, AC1):
 * hỏi quyền là việc đầu tiên, trước mọi await khác.
 */
export async function enablePush(publicKey: string): Promise<EnableResult> {
  let permission: NotificationPermission;
  try {
    permission = await Notification.requestPermission();
  } catch {
    return { ok: false, reason: "error", message: "Trình duyệt này không hỗ trợ thông báo." };
  }
  if (permission === "denied") return { ok: false, reason: "denied" };
  if (permission !== "granted") return { ok: false, reason: "dismissed" };
  let sub: PushSubscription;
  try {
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    await navigator.serviceWorker.ready;
    sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlToBytes(publicKey) }));
  } catch {
    return { ok: false, reason: "error", message: "Thiết bị này không hỗ trợ nhận thông báo." };
  }
  const saved = await saveSubscription(sub);
  if (!saved.ok) {
    // Server từ chối (E-PUSH-1 / E-PUSH-2) ⇒ không giữ đăng ký dở ở trình duyệt
    await sub.unsubscribe().catch(() => false);
    return { ok: false, reason: "error", message: saved.message };
  }
  return { ok: true };
}

/** Đồng bộ lại đăng ký đang có với tài khoản đang đăng nhập (đổi tài khoản trên cùng máy, AC5). Lỗi thì bỏ qua. */
let synced = false;
export async function resyncPush(sub: PushSubscription): Promise<void> {
  if (synced) return; // một lần mỗi lượt tải trang (nhiều nút thông báo cùng trang)
  synced = true;
  await saveSubscription(sub);
}

/** Tắt trên máy này: xóa ở server (khi còn phiên) rồi hủy đăng ký ở trình duyệt. */
export async function disablePush(): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  await api.DELETE("/api/v1/push/subscriptions", { body: { endpoint: sub.endpoint } }).catch(() => {});
  await sub.unsubscribe().catch(() => false);
}

/** Gọi TRƯỚC API đăng xuất (còn cookie phiên để DELETE). Tối đa ~3 giây để không làm chậm đăng xuất (AC5). */
export async function forgetPushDevice(): Promise<void> {
  if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
  await Promise.race([disablePush().catch(() => {}), new Promise((resolve) => setTimeout(resolve, 3000))]);
}

/** Gửi thử tới các thiết bị của chính tài khoản (AC4). */
export async function sendTestPush(): Promise<{ ok: true; devices: number } | { ok: false; message: string }> {
  try {
    const { data, error, response } = await api.POST("/api/v1/push/test");
    if (response.ok) return { ok: true, devices: data?.devices ?? 0 };
    if (response.status === 429) return { ok: false, message: "Bạn đã gửi thử nhiều lần, vui lòng chờ vài phút." };
    return { ok: false, message: errorMessage(error, "Không gửi thử được, vui lòng thử lại.") };
  } catch {
    return { ok: false, message: "Không kết nối được máy chủ, vui lòng thử lại." };
  }
}
