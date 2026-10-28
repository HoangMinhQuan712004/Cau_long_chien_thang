"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { formatLongDate, formatVnd } from "@/lib/format";
import { BankBox, CopyButton, mmss, useCountdown } from "./pay-parts";
import { getCheckout } from "./requests";
import { RESTORE_KEY, type Checkout } from "./types";

// /thanh-toan/{token}: QR + đếm ngược theo giờ server, hỏi trạng thái mỗi 3 giây (10 giây khi tab ẩn) → Thành công | Hết thời gian giữ chỗ (T-008 AC15–AC18).

type View = "pending" | "paid" | "expired";

const hhmm = (t: string) => t.slice(0, 5);

export function PaymentScreen({ token, hotline }: { token: string; hotline: string }) {
  const router = useRouter();
  const [checkout, setCheckout] = useState<Checkout | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      const res = await getCheckout(token);
      if (stop) return;
      if (res.ok) {
        setOffline(false);
        setCheckout(res.data);
        if (res.data.status !== "pending") return; // kết quả cuối từ server: dừng hỏi
      } else if (res.error.status === 404 || res.error.code === "E-WEB-6") {
        setNotFound(true);
        return;
      }
      // lỗi mạng tạm thời → báo nhẹ và thử lại
      setOffline(true);
      timer = setTimeout(run, document.visibilityState === "visible" ? 3000 : 10_000);
    };
    void run();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  const left = useCountdown(checkout?.expires_at ?? null, checkout?.server_now ?? null);

  if (notFound) {
    return (
      <Card>
        <h1 className="text-xl font-bold">Không tìm thấy lượt thanh toán.</h1>
        <p className="mt-2 text-sm text-muted">Liên kết không đúng hoặc đã cũ. Nếu bạn đã chuyển khoản, vui lòng gọi hotline {hotline} kèm mã booking.</p>
        <Link href="/dat-san" className="mt-4 inline-block rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-fg">
          Đặt sân
        </Link>
      </Card>
    );
  }
  if (!checkout) {
    return (
      <Card>
        <p className="text-sm text-muted" role="status">
          Đang tải thông tin thanh toán…
        </p>
      </Card>
    );
  }

  // Đếm ngược về 0 nhưng server chưa báo expired (ân hạn nhận tiền báo trễ) → hiện màn hết hạn, vẫn hỏi tiếp tới khi server trả kết quả cuối.
  const view: View = checkout.status === "paid" ? "paid" : checkout.status === "expired" || left === 0 ? "expired" : "pending";

  if (view === "paid") return <PaidView checkout={checkout} />;

  const date = checkout.items[0]?.play_date;
  function rebook() {
    if (!date) return router.push("/dat-san");
    try {
      const items = checkout!.items.flatMap((it) => {
        return Array.from({ length: it.hours }, (_, i) => ({ code: it.resource_code, hour: it.start_hour + i }));
      });
      sessionStorage.setItem(RESTORE_KEY, JSON.stringify({ date, items }));
    } catch {
      /* không lưu được thì chỉ chuyển trang */
    }
    router.push(`/dat-san?ngay=${date}`);
  }

  return (
    <Card wide>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted">Bước 3/3</p>
          <h1 className="text-2xl font-bold">Thanh toán chuyển khoản</h1>
        </div>
        {view === "expired" ? (
          <span className="rounded-full border border-danger/40 bg-danger/10 px-3 py-1.5 text-sm font-semibold text-danger">Hết thời gian giữ chỗ</span>
        ) : (
          <span className="rounded-full border border-blk-unpaid-fg/30 bg-blk-unpaid px-3 py-1.5 text-sm text-blk-unpaid-fg" role="timer" aria-live="off">
            Giữ chỗ còn <b className="tabular-nums">{left == null ? "--:--" : mmss(left)}</b>
          </span>
        )}
      </div>

      {checkout.bank ? (
        <div className="mt-5">
          <BankBox bank={checkout.bank} amount={checkout.amount} payRef={checkout.pay_ref} dim={view === "expired"} />
        </div>
      ) : null}

      {view === "pending" ? (
        <p role="status" className="mt-5 flex items-center gap-2 rounded-lg border border-border bg-free px-4 py-3 text-sm">
          <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-border border-t-primary" />
          Đang chờ xác nhận thanh toán… Trang sẽ tự chuyển khi nhận được tiền.
        </p>
      ) : (
        <div className="mt-5 space-y-3">
          <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            Đã hết thời gian giữ chỗ nhưng chưa nhận được tiền. Khung giờ đã được mở lại cho người khác đặt.
          </p>
          <p className="text-sm text-muted">Nếu bạn đã chuyển khoản, vui lòng gọi hotline {hotline} kèm mã booking để được hỗ trợ.</p>
          <button type="button" onClick={rebook} className="rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-primary-fg">
            Đặt lại
          </button>
        </div>
      )}

      {offline ? (
        <p role="status" className="mt-3 text-xs text-muted">
          Chưa kết nối được máy chủ, đang thử lại… (nếu bạn đã chuyển khoản, trang sẽ tự cập nhật khi có mạng.)
        </p>
      ) : null}

      <div className="mt-5 space-y-1.5 border-t border-border pt-4 text-sm">
        {checkout.items.map((it) => (
          <p key={it.code} className="font-medium">
            Mã booking {it.code} · {it.resource_name} · {formatLongDate(it.play_date)} · {hhmm(it.start_time)} – {hhmm(it.end_time)}
          </p>
        ))}
        {view === "pending" ? (
          <p className="text-muted">Chuyển đúng số tiền và nội dung để hệ thống tự xác nhận. Hết thời gian giữ chỗ mà chưa nhận được tiền, khung giờ sẽ được mở lại.</p>
        ) : null}
      </div>
    </Card>
  );
}

function PaidView({ checkout }: { checkout: Checkout }) {
  const names = [...new Set(checkout.items.map((i) => i.resource_name))].join(", ");
  const date = checkout.items[0]?.play_date;
  return (
    <Card>
      <div className="flex flex-col items-center text-center">
        <span aria-hidden className="grid size-16 place-items-center rounded-full bg-free text-3xl text-success">
          ✓
        </span>
        <h1 className="mt-4 text-2xl font-bold">Đặt sân thành công</h1>
        <ul className="mt-4 space-y-2">
          {checkout.items.map((it) => (
            <li key={it.code} className="flex flex-wrap items-center justify-center gap-2">
              <span className="text-sm text-muted">Mã booking</span>
              <b className="text-lg text-primary">{it.code}</b>
              <CopyButton text={it.code} label={`mã booking ${it.code}`} />
            </li>
          ))}
        </ul>
      </div>

      <dl className="mt-5 space-y-2.5 rounded-xl bg-background p-4 text-sm">
        <Row label="Sân" value={names} />
        {date ? <Row label="Ngày" value={formatLongDate(date)} /> : null}
        <Row
          label="Khung giờ"
          value={checkout.items.map((i) => `${checkout.items.length > 1 ? `${i.resource_name}: ` : ""}${hhmm(i.start_time)} – ${hhmm(i.end_time)} (${i.hours} giờ)`).join("; ")}
        />
        <Row label="Người đặt" value={`${checkout.customer.full_name} · ${checkout.customer.phone_masked ?? "—"}`} />
        <Row label="Đã thanh toán" value={`${formatVnd(checkout.amount)} · Chuyển khoản`} />
      </dl>

      <p className="mt-4 text-sm text-muted">Lưu mã booking để tra cứu. Vui lòng đến trước giờ chơi và báo mã tại quầy.</p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Link href="/tra-cuu" className="rounded-lg border border-border px-4 py-3 text-center text-sm font-semibold hover:bg-free">
          Tra cứu booking
        </Link>
        <Link href="/dat-san" className="rounded-lg bg-primary px-4 py-3 text-center text-sm font-semibold text-primary-fg">
          Đặt thêm sân
        </Link>
      </div>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words font-medium">{value}</dd>
    </div>
  );
}

function Card({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return <div className={`mx-auto w-full rounded-2xl border border-border bg-surface p-5 sm:p-6 ${wide ? "max-w-3xl" : "max-w-xl"}`}>{children}</div>;
}
