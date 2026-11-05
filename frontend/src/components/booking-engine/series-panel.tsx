"use client";

import { useEffect, useState } from "react";
import { SidePanel } from "@/components/ui/side-panel";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { fill, formatVnd } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import { hourText } from "./block";
import { getSeries } from "./requests";
import { monthLabel } from "./series-fields";
import { dayLabel } from "./series-preview";
import type { PaymentStatus, SeriesDetail } from "./types";
import { StatusBadge } from "./ui";

// Ngăn chi tiết gói đặt theo tháng (GET /front-desk/series/{code}): thông tin chung, các ngày + thanh toán, Tổng / Đã thu.

type T = Dictionary["series"];
type Props = { code: string; t: T; onClose: () => void; onOpenItem?: (bookingCode: string) => void };

export function SeriesPanel({ code, t, onClose, onOpenItem }: Props) {
  const [data, setData] = useState<SeriesDetail | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    getSeries(code).then((res) => {
      if (!live) return;
      if (res.ok) setData(res.data);
      else setFailed(true);
    });
    return () => {
      live = false;
    };
  }, [code]);

  const rows: [string, React.ReactNode][] = data
    ? [
        [t.court, `${data.resource.code} · ${data.resource.name}`],
        [t.time, `${hourText(data.start_hour)}–${hourText(data.end_hour)}`],
        [t.weekdays, data.weekdays.map((d) => t.weekdayShort[d - 1]).join(", ")],
        [t.month, monthLabel(data.month, t.monthOption)],
        [t.customer, (
          <>
            {data.customer.name}
            {data.customer.phone ? <span className="block text-ui text-muted tabular-nums">{formatPhone(data.customer.phone)}</span> : null}
          </>
        )],
      ]
    : [];

  return (
    <SidePanel
      title={fill(t.panelTitle, { code })}
      closeLabel={t.close}
      onClose={onClose}
      resizeLabel={t.resize}
      storageKey="dat-san.goi.rong"
      status={failed ? "error" : data ? "ok" : "loading"}
      loadingLabel={t.loading}
      errorText={t.loadError}
    >
      {data ? (
        <div className="flex flex-col gap-5">
          <p className="text-ui font-semibold text-primary">{t.status[data.status]}</p>
          <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-2 text-sm">
            {rows.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted">{k}</dt>
                <dd className="min-w-0 wrap-break-word">{v}</dd>
              </div>
            ))}
          </dl>
          <section className="flex flex-col gap-1" aria-label={fill(t.itemsTitle, { n: data.items.length })}>
            <h3 className="text-sm font-semibold">{fill(t.itemsTitle, { n: data.items.length })}</h3>
            <ul className="divide-y">
              {data.items.map((it) => {
                const off = it.status === "cancelled";
                return (
                  <li key={it.booking_code} className={cn("flex min-h-11 items-center gap-3 py-2", off && `
                    text-muted
                  `)}>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className={cn("text-sm font-medium tabular-nums", off && "line-through")}>{dayLabel(it.date, t.weekdayShort)}</span>
                      {onOpenItem && !off ? (
                        <button
                          type="button"
                          onClick={() => onOpenItem(it.booking_code)}
                          className={cn(`
                            -my-1 self-start py-1 font-mono text-xs text-primary focus-ring
                            hover:underline
                          `)}
                        >
                          {it.booking_code}
                        </button>
                      ) : (
                        <span className="font-mono text-xs">{it.booking_code}</span>
                      )}
                    </span>
                    <span className={cn("text-sm tabular-nums", off && "line-through")}>{formatVnd(it.price)}</span>
                    {off ? <span className="text-xs">{t.cancelled}</span> : <StatusBadge status={it.payment_status as PaymentStatus} />}
                  </li>
                );
              })}
            </ul>
          </section>
          <dl className="flex flex-col gap-1 border-t pt-3 text-sm">
            <div className="flex justify-between font-semibold">
              <dt>{t.total}</dt>
              <dd className="tabular-nums">{formatVnd(data.total)}</dd>
            </div>
            <div className="flex justify-between text-muted">
              <dt>{t.paid}</dt>
              <dd className="tabular-nums">{formatVnd(data.paid_total)}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </SidePanel>
  );
}
