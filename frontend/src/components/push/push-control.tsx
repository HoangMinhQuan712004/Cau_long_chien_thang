"use client";

import { useEffect, useState } from "react";
import { Svg } from "@/components/ui/icons/svg";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { currentSubscription, disablePush, enablePush, getPushConfig, pushSupport, resyncPush, sendTestPush } from "@/lib/push";

// T-076 AC1–AC6: "Bật thông báo trên máy này" ⇒ "Đã bật · Gửi thử · Tắt".
// - `card`: thẻ ở Tổng quan hội viên · `menu`: dòng gọn trong menu / sheet tài khoản (hội viên, quản trị).
// - Cấu hình tắt (`enabled = false`) hoặc lỗi mạng ⇒ không hiện gì (AC6).
// - iPhone mở bằng Safari chưa thêm vào MH chính / iOS < 16.4 ⇒ hướng dẫn thay cho nút (AC2). Đã chặn quyền ⇒ hướng dẫn mở lại (AC3).

type State =
  | { kind: "hidden" }
  | { kind: "ios-install" }
  | { kind: "unsupported" }
  | { kind: "denied" }
  | { kind: "off"; publicKey: string }
  | { kind: "on" };

const TEXT = {
  member: "Nhắc giờ chơi, đổi lịch, thanh toán và phòng chơi hiện ngay trên màn hình khóa.",
  staff: "Báo đặt online mới, tiền QR đã nhận và tiền về cần xử lý ngay trên máy này.",
} as const;
const IOS_HINT = "Để nhận thông báo trên iPhone: bấm Chia sẻ → Thêm vào MH chính, rồi mở app Chiến Thắng.";
const DENIED_HINT = "Bạn đã chặn thông báo cho trang này, hãy bật lại trong Cài đặt của máy.";
const UNSUPPORTED_HINT = "Trình duyệt này không hỗ trợ thông báo.";

function BellIcon({ size = 18 }: { size?: number }) {
  return (
    <Svg size={size}>
      <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </Svg>
  );
}

/** Trạng thái thật của máy này: hỗ trợ? cấu hình? quyền? đã có đăng ký? */
async function detect(): Promise<State> {
  const config = await getPushConfig();
  if (!config?.enabled || !config.public_key) return { kind: "hidden" };
  const support = pushSupport();
  if (support !== "ok") return { kind: support };
  if (Notification.permission === "denied") return { kind: "denied" };
  const sub = Notification.permission === "granted" ? await currentSubscription() : null;
  if (sub) {
    void resyncPush(sub); // đổi tài khoản trên cùng máy ⇒ chuyển đăng ký sang tài khoản đang đăng nhập (AC5)
    return { kind: "on" };
  }
  return { kind: "off", publicKey: config.public_key };
}

export function PushControl({ variant, audience, className = "" }: { variant: "card" | "menu"; audience: "member" | "staff"; className?: string }) {
  const [state, setState] = useState<State>({ kind: "hidden" });
  const [busy, setBusy] = useState<null | "enable" | "test" | "disable">(null);

  useEffect(() => {
    let live = true;
    void detect()
      .catch((): State => ({ kind: "hidden" }))
      .then((s) => {
        if (live) setState(s);
      });
    return () => {
      live = false;
    };
  }, []);

  if (state.kind === "hidden") return null;

  async function enable(publicKey: string) {
    if (busy) return;
    setBusy("enable");
    let res: Awaited<ReturnType<typeof enablePush>>;
    try {
      res = await enablePush(publicKey); // hỏi quyền ngay trong lần bấm (iOS)
    } catch {
      res = { ok: false, reason: "error" };
    } finally {
      setBusy(null);
    }
    if (res.ok) {
      setState({ kind: "on" });
      toast("Đã bật thông báo trên máy này", "Bấm “Gửi thử” để kiểm tra");
    } else if (res.reason === "denied") setState({ kind: "denied" });
    else if (res.reason === "error") toast(res.message ?? "Không bật được thông báo", undefined, "error");
    // dismissed: người dùng đóng hộp hỏi quyền ⇒ giữ nút để bấm lại
  }

  async function test() {
    if (busy) return;
    setBusy("test");
    let res: Awaited<ReturnType<typeof sendTestPush>>;
    try {
      res = await sendTestPush();
    } catch {
      res = { ok: false, message: "Không gửi thử được, vui lòng thử lại." };
    } finally {
      setBusy(null);
    }
    if (res.ok) toast("Đã gửi thử", res.devices > 1 ? `Tới ${res.devices} thiết bị của bạn` : "Thông báo sẽ hiện trong giây lát");
    else toast(res.message, undefined, "error");
  }

  async function disable() {
    if (busy) return;
    setBusy("disable");
    try {
      await disablePush();
      const config = await getPushConfig();
      setState(config?.public_key ? { kind: "off", publicKey: config.public_key } : { kind: "hidden" });
      toast("Đã tắt thông báo trên máy này");
    } catch {
      toast("Không tắt được thông báo, vui lòng thử lại", undefined, "error");
    } finally {
      setBusy(null);
    }
  }

  const hint = state.kind === "ios-install" ? IOS_HINT : state.kind === "denied" ? DENIED_HINT : state.kind === "unsupported" ? UNSUPPORTED_HINT : null;
  const linkBtn = "rounded-md px-2 py-1 text-sm font-semibold focus-ring disabled:opacity-50";

  const actions =
    state.kind === "off" ? (
      <button
        type="button"
        disabled={busy !== null}
        aria-busy={busy === "enable" || undefined}
        onClick={() => void enable(state.publicKey)}
        className={cn(
          "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-surface focus-ring hover:bg-primary-hover disabled:opacity-60",
          variant === "menu" ? "w-full" : "whitespace-nowrap",
        )}
      >
        <BellIcon size={16} />
        {busy === "enable" ? "Đang bật…" : "Bật thông báo trên máy này"}
      </button>
    ) : state.kind === "on" ? (
      <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-softer px-2.5 py-1 text-sm font-semibold text-primary">
          <BellIcon size={14} />
          Đã bật
        </span>
        <button type="button" disabled={busy !== null} onClick={() => void test()} className={cn(linkBtn, "text-primary hover:bg-primary-soft/60")}>
          {busy === "test" ? "Đang gửi…" : "Gửi thử"}
        </button>
        <button type="button" disabled={busy !== null} onClick={() => void disable()} className={cn(linkBtn, "text-muted hover:bg-danger-soft hover:text-danger")}>
          {busy === "disable" ? "Đang tắt…" : "Tắt"}
        </button>
      </div>
    ) : null;

  if (variant === "menu") {
    return (
      <div className={cn("px-3 py-2", className)}>
        <p className="mb-1.5 text-xs font-semibold tracking-wide text-muted uppercase">Thông báo trên máy này</p>
        {hint ? <p className="text-sm text-muted">{hint}</p> : actions}
      </div>
    );
  }

  return (
    <section aria-label="Thông báo trên điện thoại" className={cn("rounded-2xl bg-surface p-4 shadow-card sm:px-6", className)}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
        <span aria-hidden className="hidden size-10 shrink-0 place-items-center rounded-full bg-primary-softer text-primary sm:grid">
          <BellIcon size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-bold">Thông báo trên điện thoại</p>
          <p className="mt-0.5 text-sm text-muted">{hint ?? TEXT[audience]}</p>
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
    </section>
  );
}
