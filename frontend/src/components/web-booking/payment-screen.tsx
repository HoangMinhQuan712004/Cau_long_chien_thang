"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { formatLongDate, formatVnd } from "@/lib/format";
import { BankBox, CopyButton, mmss, useCountdown } from "./pay-parts";
import { getCheckout } from "./requests";
import { RoomLinks } from "./room-links";
import { RESTORE_KEY, type Checkout, type TicketInfo } from "./types";

// /thanh-toan/{token}: QR + đếm ngược theo giờ server, hỏi trạng thái mỗi 3 giây (10 giây khi tab ẩn) → Thành công | Hết thời gian giữ chỗ (T-008 AC15–AC18).

type View = "pending" | "paid" | "expired";

// T-023: checkout vé sự kiện (`kind='ticket'`) – không có danh sách sân/giờ đặt sân, thay bằng khối `event`.
// TODO(T-023): BE chưa handoff ⇒ kiểu viết tay; sau khi merge `be/T-023-ve-online` lấy từ schema.d.ts.
const ticketOf = (c: Checkout): TicketInfo | null => {
  const x = c as Checkout & { kind?: string; event?: TicketInfo | null };
  return x.kind === "ticket" && x.event ? x.event : null;
};

const hhmm = (t: string) => t.slice(0, 5);

export function PaymentScreen({ token, hotline, member = false }: { token: string; hotline: string; member?: boolean }) {
  const router = useRouter();
  // Trong khu hội viên (T-018): đặt lại / đặt thêm quay về /hoi-vien/dat-san, đặt xong có nút Vào phòng
  const bookPath = member ? "/hoi-vien/dat-san" : "/dat-san";
  const [checkout, setCheckout] = useState<Checkout | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const next = () => {
      timer = setTimeout(run, document.visibilityState === "visible" ? 3000 : 10_000);
    };
    const run = async () => {
      const res = await getCheckout(token);
      if (stop) return;
      if (res.ok) {
        setOffline(false);
        setCheckout(res.data);
        if (res.data.status === "pending") next(); // còn chờ tiền → hỏi tiếp; paid/expired là kết quả cuối → dừng
        return;
      }
      if (res.error.status === 404 || res.error.code === "E-WEB-6") {
        setNotFound(true);
        return;
      }
      // Chỉ lỗi thật (mạng / 5xx) mới báo mất kết nối, rồi thử lại.
      setOffline(true);
      next();
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
        <Link href={bookPath} className="mt-4 inline-block rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-white">
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

  if (view === "paid") return <PaidView checkout={checkout} member={member} bookPath={bookPath} />;

  const ticket = ticketOf(checkout);
  const date = ticket?.play_date ?? checkout.items[0]?.play_date;
  function rebook() {
    if (!date) return router.push(bookPath);
    if (ticket) return router.push(`${bookPath}?ngay=${date}`); // vé: về lịch ngày đó, bấm lại ô sự kiện
    try {
      const items = checkout!.items.flatMap((it) => {
        return Array.from({ length: it.hours }, (_, i) => ({ code: it.resource_code, hour: it.start_hour + i }));
      });
      sessionStorage.setItem(RESTORE_KEY, JSON.stringify({ date, items }));
    } catch {
      /* không lưu được thì chỉ chuyển trang */
    }
    router.push(`${bookPath}?ngay=${date}`);
  }

  return (
    <Card wide>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted">Bước 3/3</p>
          <h1 className="text-2xl font-bold">{ticket ? "Thanh toán vé sự kiện" : "Thanh toán chuyển khoản"}</h1>
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
        <p role="status" className="mt-5 flex items-center gap-2 rounded-lg border border-border bg-primary-softer px-4 py-3 text-sm">
          <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-border border-t-primary" />
          Đang chờ xác nhận thanh toán… Trang sẽ tự chuyển khi nhận được tiền.
        </p>
      ) : (
        <div className="mt-5 space-y-3">
          <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            Đã hết thời gian giữ chỗ nhưng chưa nhận được tiền. {ticket ? "Chỗ đã được nhả lại cho người khác." : "Khung giờ đã được mở lại cho người khác đặt."}
          </p>
          <p className="text-sm text-muted">Nếu bạn đã chuyển khoản, vui lòng gọi hotline {hotline} kèm mã booking để được hỗ trợ.</p>
          <button type="button" onClick={rebook} className="rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-white">
            {ticket ? "Về lịch đặt sân" : "Đặt lại"}
          </button>
        </div>
      )}

      {offline ? (
        <p role="status" className="mt-3 text-xs text-muted">
          Chưa kết nối được máy chủ, đang thử lại… (nếu bạn đã chuyển khoản, trang sẽ tự cập nhật khi có mạng.)
        </p>
      ) : null}

      <div className="mt-5 space-y-1.5 border-t border-border pt-4 text-sm">
        {/* Khách chỉ thấy MÃ ĐƠN (trùng nội dung chuyển khoản); mã khối không hiện (T-019 AC2) */}
        <p className="font-semibold">Mã booking {checkout.order_code}</p>
        {ticket ? (
          <p className="font-medium">
            Vé sự kiện {ticket.name} × {ticket.seats} · {formatLongDate(ticket.play_date)} · {hhmm(ticket.start_time)} – {hhmm(ticket.end_time)}
          </p>
        ) : (
          checkout.items.map((it) => (
            <p key={it.code} className="font-medium">
              {it.resource_name} · {formatLongDate(it.play_date)} · {hhmm(it.start_time)} – {hhmm(it.end_time)}
            </p>
          ))
        )}
        {view === "pending" ? (
          <p className="text-muted">
            Chuyển đúng số tiền và nội dung để hệ thống tự xác nhận. Hết thời gian giữ chỗ mà chưa nhận được tiền, {ticket ? "chỗ" : "khung giờ"} sẽ được mở lại.
          </p>
        ) : null}
      </div>
    </Card>
  );
}

function PaidView({ checkout, member, bookPath }: { checkout: Checkout; member: boolean; bookPath: string }) {
  const ticket = ticketOf(checkout);
  if (ticket) return <PaidTicketView checkout={checkout} ticket={ticket} member={member} bookPath={bookPath} />;
  const names = [...new Set(checkout.items.map((i) => i.resource_name))].join(", ");
  const date = checkout.items[0]?.play_date;
  return (
    <Card>
      <div className="flex flex-col items-center text-center">
        <span aria-hidden className="grid size-16 place-items-center rounded-full bg-primary-softer text-3xl text-primary">
          ✓
        </span>
        <h1 className="mt-4 text-2xl font-bold">Đặt sân thành công</h1>
        <p className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <span className="text-sm text-muted">Mã booking</span>
          <b className="text-lg text-primary">{checkout.order_code}</b>
          <CopyButton text={checkout.order_code} label={`mã booking ${checkout.order_code}`} />
        </p>
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
      {member ? <RoomLinks items={checkout.items} /> : null}
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Link href={member ? "/hoi-vien/lich-su-thanh-toan" : "/tra-cuu"} className="rounded-lg border border-border px-4 py-3 text-center text-sm font-semibold hover:bg-primary-softer">
          {member ? "Lịch sử thanh toán" : "Tra cứu booking"}
        </Link>
        <Link href={bookPath} className="rounded-lg bg-primary px-4 py-3 text-center text-sm font-semibold text-white">
          Đặt thêm sân
        </Link>
      </div>
    </Card>
  );
}

function PaidTicketView({ checkout, ticket, member, bookPath }: { checkout: Checkout; ticket: TicketInfo; member: boolean; bookPath: string }) {
  const codes = ticket.ticket_codes ?? [];
  return (
    <Card>
      <div className="flex flex-col items-center text-center">
        <span aria-hidden className="grid size-16 place-items-center rounded-full bg-primary-softer text-3xl text-primary">
          ✓
        </span>
        <h1 className="mt-4 text-2xl font-bold">Mua vé thành công</h1>
        <p className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <span className="text-sm text-muted">Mã đơn</span>
          <b className="text-lg text-primary">{checkout.order_code}</b>
          <CopyButton text={checkout.order_code} label={`mã đơn ${checkout.order_code}`} />
        </p>
      </div>

      <dl className="mt-5 space-y-2.5 rounded-xl bg-background p-4 text-sm">
        <Row label="Sự kiện" value={ticket.name} />
        <Row label="Ngày" value={formatLongDate(ticket.play_date)} />
        <Row label="Giờ" value={`${hhmm(ticket.start_time)} – ${hhmm(ticket.end_time)}`} />
        <Row label="Số vé" value={String(ticket.seats)} />
        {codes.length > 0 ? <Row label="Mã vé" value={codes.join(", ")} /> : null}
        <Row label="Người mua" value={`${checkout.customer.full_name} · ${checkout.customer.phone_masked ?? "—"}`} />
        <Row label="Đã thanh toán" value={`${formatVnd(checkout.amount)} · Chuyển khoản`} />
      </dl>

      <p className="mt-4 text-sm text-muted">Lưu mã đơn hoặc mã vé để tra cứu. Vui lòng đến trước giờ bắt đầu và báo mã vé tại quầy.</p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Link href={member ? "/hoi-vien/lich-su-thanh-toan" : "/tra-cuu"} className="rounded-lg border border-border px-4 py-3 text-center text-sm font-semibold hover:bg-primary-softer">
          {member ? "Lịch sử thanh toán" : "Tra cứu vé"}
        </Link>
        <Link href={`${bookPath}?ngay=${ticket.play_date}`} className="rounded-lg bg-primary px-4 py-3 text-center text-sm font-semibold text-white">
          Về lịch đặt sân
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
