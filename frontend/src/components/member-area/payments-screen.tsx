"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PageBanner } from "@/components/member-area/page-banner";
import { hourRange } from "@/components/play-rooms/utils";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatDayMonthYear, formatDateTime, formatNumber, formatTime, formatVnd, vnDate } from "@/lib/format";

// /hoi-vien/lich-su-thanh-toan (T-018 AC7–AC10): chỉ khoản đã thanh toán; chọn tháng; 3 thẻ; lọc; nhóm theo ngày; bấm dòng xem chi tiết.

type List = components["schemas"]["PaymentList"];
type Item = components["schemas"]["PaymentItem"];
type Kind = "all" | "booking" | "ticket";

const monthLabel = (m: string) => `Tháng ${m.slice(5, 7)}/${m.slice(0, 4)}`;
const weekday = (isoDate: string) => new Intl.DateTimeFormat("vi-VN", { weekday: "long", timeZone: "UTC" }).format(new Date(`${isoDate}T00:00:00Z`));

export function PaymentsScreen() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [kind, setKind] = useState<Kind>("all");
  const [data, setData] = useState<List | null>(null);
  const [failed, setFailed] = useState(false);
  const [detail, setDetail] = useState<Item | null>(null);
  const [nowMs, setNowMs] = useState(0);
  // Chỉ nhận kết quả của lần gọi mới nhất (đổi tháng / lọc liên tiếp)
  const seq = useRef(0);

  const load = useCallback(async (m: string | undefined, k: Kind) => {
    const mine = ++seq.current;
    setFailed(false);
    try {
      const { data: d, response } = await api.GET("/api/v1/member-area/payments", { params: { query: { ...(m ? { month: m } : {}), kind: k } } });
      if (mine !== seq.current) return;
      if (response.status === 401) {
        window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien/lich-su-thanh-toan")}&ly-do=het-han`);
        return;
      }
      if (d) {
        setData(d);
        setNowMs(Date.now());
      } else setFailed(true);
    } catch {
      if (mine === seq.current) setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi tháng / bộ lọc
    void load(month, kind);
  }, [load, month, kind]);

  const today = nowMs ? vnDate(new Date(nowMs).toISOString()) : "";
  // Nhóm theo ngày thanh toán (giờ VN); dữ liệu đã mới nhất trước
  const groups = useMemo(() => {
    const out: { day: string; items: Item[] }[] = [];
    for (const it of data?.items ?? []) {
      const day = vnDate(it.paid_at);
      const g = out.find((x) => x.day === day);
      if (g) g.items.push(it);
      else out.push({ day, items: [it] });
    }
    return out;
  }, [data]);

  const s = data?.summary;
  const m = data?.month ?? month ?? "";
  const monthNo = m ? Number(m.slice(5, 7)) : "";

  return (
    <>
      <PageBanner
        title="Lịch sử thanh toán"
        subtitle="Các khoản bạn đã thanh toán"
        aside={
          data ? (
            <div className="flex items-center gap-2">
              <label htmlFor="pay-month" className="text-sm text-surface/80">
                Tháng
              </label>
              <select
                id="pay-month"
                value={data.month}
                onChange={(e) => setMonth(e.target.value)}
                className="h-10 rounded-lg border border-border-strong bg-surface px-3 text-sm font-medium text-foreground focus-ring"
              >
                {data.months.map((x) => (
                  <option key={x} value={x}>
                    {monthLabel(x)}
                  </option>
                ))}
              </select>
            </div>
          ) : null
        }
      />
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        {failed && !data ? (
          <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card">
            <p className="font-semibold">Không tải được lịch sử thanh toán. Vui lòng thử lại.</p>
            <Button className="mt-4" onClick={() => void load(month, kind)}>
              Thử lại
            </Button>
          </div>
        ) : !data || !s ? (
          <p className="py-10 text-center text-muted" aria-busy>
            Đang tải…
          </p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label={`Đã thanh toán tháng ${monthNo}`} value={formatVnd(s.total)} sub={`${formatNumber(s.count)} giao dịch`} />
              <Stat label="Lượt đặt sân" value={`${formatNumber(s.bookings.count)} lượt`} sub={`${formatNumber(s.bookings.hours)} giờ chơi`} />
              <Stat label="Vé sự kiện" value={`${formatNumber(s.tickets.count)} vé`} sub={formatVnd(s.tickets.total)} />
            </div>

            <div className="mt-5 flex flex-wrap gap-2" role="group" aria-label="Lọc khoản thanh toán">
              {(
                [
                  ["all", `Tất cả (${s.count})`],
                  ["booking", `Đặt sân (${s.bookings.count})`],
                  ["ticket", `Vé sự kiện (${s.tickets.count})`],
                ] as const
              ).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  aria-pressed={kind === k}
                  onClick={() => setKind(k)}
                  className={cn("h-9 rounded-full border px-4 text-sm font-medium focus-ring", kind === k ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer")}
                >
                  {label}
                </button>
              ))}
            </div>

            {groups.length === 0 ? (
              <p className="mt-6 rounded-card bg-surface p-8 text-center text-muted shadow-card">Chưa có khoản thanh toán nào trong tháng này.</p>
            ) : (
              groups.map((g) => (
                <section key={g.day} className="mt-6" aria-label={formatDayMonthYear(g.day)}>
                  <h2 className="flex items-center gap-2 text-xs font-semibold tracking-wide text-muted uppercase">
                    {g.day === today ? "Hôm nay" : weekday(g.day)} · {formatDayMonth(g.day)}
                    <span aria-hidden className="h-px flex-1 bg-border" />
                  </h2>
                  <ul className="mt-2 divide-y divide-border overflow-hidden rounded-card bg-surface shadow-card">
                    {g.items.map((it) => (
                      <li key={`${it.kind}-${it.code}`}>
                        <button type="button" onClick={() => setDetail(it)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-primary-softer focus-ring">
                          <span aria-hidden className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-softer text-primary">
                            {it.kind === "ticket" ? "🎫" : "🏸"}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold">{it.title}</span>
                            <span className="block truncate text-xs text-muted">
                              Mã {it.display_code} · {formatTime(it.paid_at)}
                            </span>
                          </span>
                          <span className="rounded-full bg-background px-2.5 py-0.5 text-xs font-semibold ring-1 ring-border">{it.method}</span>
                          <span className="text-sm font-bold whitespace-nowrap tabular-nums">{formatVnd(it.amount)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              ))
            )}
          </>
        )}
      </div>

      <Modal
        open={detail !== null}
        onClose={() => setDetail(null)}
        title="Chi tiết thanh toán"
        footer={
          <Button variant="secondary" onClick={() => setDetail(null)}>
            Đóng
          </Button>
        }
      >
        {detail ? (
          <dl className="space-y-2.5 text-sm">
            <Line label="Mã" value={detail.display_code} />
            <Line label="Nội dung" value={detail.title} />
            <Line label="Ngày chơi" value={formatDayMonthYear(detail.play_date)} />
            {detail.resource_names.length > 0 ? <Line label="Sân" value={detail.resource_names.join(", ")} /> : null}
            <Line label="Giờ" value={hourRange(detail.start_at, detail.end_at)} />
            <Line label="Số tiền" value={formatVnd(detail.amount)} />
            <Line label="Thanh toán lúc" value={formatDateTime(detail.paid_at)} />
            <Line label="Hình thức" value={`${detail.method} · ${detail.channel === "counter" ? "tại quầy" : "online"}`} />
          </dl>
        ) : null}
      </Modal>
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-card bg-surface p-4 shadow-card">
      <p className="text-xs text-muted sm:text-sm">{label}</p>
      <p className="mt-1 text-xl font-bold tabular-nums sm:text-2xl">{value}</p>
      <p className="text-xs text-muted sm:text-sm">{sub}</p>
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{value}</dd>
    </div>
  );
}
