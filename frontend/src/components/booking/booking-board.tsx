"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { formatTime, formatVnd, todayVn, vnIso } from "@/lib/format";

type Availability = components["schemas"]["AvailabilityOut"];
type SlotIn = components["schemas"]["SlotIn"];
type Message = { type: "error" | "ok"; text: string };

const NETWORK_ERROR: Message = { type: "error", text: "Không kết nối được máy chủ, vui lòng thử lại" };

const toMinutes = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
};
const toHHmm = (min: number) =>
  `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
const addDays = (date: string, days: number) => {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

/** Gộp các ô liền nhau trên cùng một sân thành 1 slot. */
function groupSelection(date: string, selected: Set<string>, step: number): SlotIn[] {
  const byCourt = new Map<number, number[]>();
  for (const key of selected) {
    const [court, start] = key.split("|").map(Number);
    byCourt.set(court, [...(byCourt.get(court) ?? []), start]);
  }
  const slots: SlotIn[] = [];
  for (const [court_id, starts] of byCourt) {
    starts.sort((a, b) => a - b);
    let from = starts[0];
    let prev = starts[0];
    for (const s of [...starts.slice(1), Infinity]) {
      if (s !== prev + step) {
        slots.push({
          court_id,
          start: vnIso(date, toHHmm(from)),
          end: vnIso(date, toHHmm(prev + step)),
        });
        from = s;
      }
      prev = s;
    }
  }
  return slots;
}

/** Tải lịch trống; loadedAt dùng để khóa các ô đã qua giờ. */
async function fetchAvailability(
  day: string,
): Promise<{ data: Availability; loadedAt: number } | { error: Message }> {
  try {
    const { data, error } = await api.GET("/api/v1/bookings/availability", {
      params: { query: { date: day } },
    });
    if (error || !data) return { error: { type: "error", text: errorMessage(error) } };
    return { data, loadedAt: Date.now() };
  } catch {
    return { error: NETWORK_ERROR };
  }
}

export function BookingBoard({ maxAdvanceDays }: { maxAdvanceDays: number }) {
  const router = useRouter();
  const today = todayVn();
  const [date, setDate] = useState(today);
  const [reloadKey, setReloadKey] = useState(0);
  const [board, setBoard] = useState<{ data: Availability; loadedAt: number } | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [quote, setQuote] = useState<{ key: string; total: number } | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const data = board?.data ?? null;

  useEffect(() => {
    let cancelled = false; // bỏ qua response cũ khi người dùng đổi ngày liên tục
    fetchAvailability(date).then((r) => {
      if (cancelled) return;
      if ("error" in r) setMessage(r.error);
      else setBoard(r);
    });
    return () => {
      cancelled = true;
    };
  }, [date, reloadKey]);

  const changeDate = (day: string) => {
    if (!day) return;
    setDate(day);
    setBoard(null);
    setSelected(new Set());
    setMessage(null);
  };

  const step = data?.slot_minutes ?? 30;
  const rows = useMemo(() => {
    if (!data) return [];
    const out: number[] = [];
    const close = toMinutes(data.close_time) || 24 * 60;
    for (let m = toMinutes(data.open_time); m < close; m += step) out.push(m);
    return out;
  }, [data, step]);

  const slots = useMemo(() => groupSelection(date, selected, step), [date, selected, step]);
  const slotsKey = JSON.stringify(slots);
  const total = quote?.key === slotsKey ? quote.total : null;

  useEffect(() => {
    if (!slots.length) return;
    let cancelled = false;
    api
      .POST("/api/v1/bookings/quote", { body: slots })
      .then(({ data, error }) => {
        if (cancelled) return;
        if (data) setQuote({ key: slotsKey, total: data.total_amount });
        setMessage(error ? { type: "error", text: errorMessage(error) } : null);
      })
      .catch(() => !cancelled && setMessage(NETWORK_ERROR));
    return () => {
      cancelled = true;
    };
  }, [slots, slotsKey]);

  const isBusy = (courtId: number, minute: number) => {
    const start = Date.parse(vnIso(date, toHHmm(minute)));
    const end = start + step * 60_000;
    if (!board || start <= board.loadedAt) return true;
    const court = data?.courts.find((c) => c.court_id === courtId);
    return !!court?.busy.some((b) => Date.parse(b.start) < end && Date.parse(b.end) > start);
  };

  const toggle = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const submit = async () => {
    setSubmitting(true);
    try {
      const { data: booking, error, response } = await api.POST("/api/v1/bookings", {
        body: { slots },
      });
      if (response.status === 401) {
        router.push(`/dang-nhap?next=${encodeURIComponent("/dat-san")}`);
        return;
      }
      if (error || !booking) {
        setMessage({ type: "error", text: errorMessage(error) });
      } else {
        setSelected(new Set());
        setMessage({
          type: "ok",
          text: `Đã giữ chỗ, mã đơn ${booking.code}. Vui lòng thanh toán trước ${
            booking.expires_at ? formatTime(booking.expires_at) : "giờ chơi"
          }.`,
        });
      }
      setReloadKey((k) => k + 1);
    } catch {
      setMessage(NETWORK_ERROR);
    } finally {
      setSubmitting(false);
    }
  };

  const courtName = (id: number) => data?.courts.find((c) => c.court_id === id)?.name;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="booking-date" className="font-medium">
          Chọn ngày
        </label>
        <input
          id="booking-date"
          type="date"
          value={date}
          min={today}
          max={addDays(today, maxAdvanceDays)}
          onChange={(e) => changeDate(e.target.value)}
          className="rounded-md border border-border bg-surface px-3 py-2"
        />
        <span className="text-sm text-muted">Bấm vào các ô trống để chọn giờ, tối thiểu 1 tiếng.</span>
      </div>

      {!data ? (
        message?.type === "error" ? (
          <button
            type="button"
            onClick={() => {
              setMessage(null);
              setReloadKey((k) => k + 1);
            }}
            className="rounded-md border border-border px-4 py-2"
          >
            Tải lại lịch sân
          </button>
        ) : (
          <p className="text-muted">Đang tải lịch sân…</p>
        )
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr>
                <th className="w-20 border-b border-border p-2 text-left">Giờ</th>
                {data.courts.map((c) => (
                  <th key={c.court_id} className="border-b border-border p-2">
                    {c.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m}>
                  <td className="border-b border-border px-2 py-1 tabular-nums text-muted">
                    {toHHmm(m)}
                  </td>
                  {data.courts.map((c) => {
                    const key = `${c.court_id}|${m}`;
                    const busy = isBusy(c.court_id, m);
                    const active = selected.has(key);
                    return (
                      <td key={key} className="border-b border-l border-border p-0.5">
                        <button
                          type="button"
                          disabled={busy}
                          aria-pressed={active}
                          aria-label={`${c.name} ${toHHmm(m)}${busy ? " (đã kín)" : ""}`}
                          onClick={() => toggle(key)}
                          className={`h-8 w-full rounded transition-colors ${
                            busy
                              ? "cursor-not-allowed bg-busy"
                              : active
                                ? "bg-primary"
                                : "bg-free hover:bg-primary/25"
                          }`}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {message && (
        <p role="status" className={message.type === "error" ? "text-danger" : "text-success"}>
          {message.text}
        </p>
      )}

      <div className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm">
        <div>
          <p className="text-sm text-muted">
            {slots.length
              ? slots
                  .map(
                    (s) =>
                      `${courtName(s.court_id)}: ${formatTime(s.start)}–${formatTime(s.end)}`,
                  )
                  .join(" · ")
              : "Chưa chọn khung giờ"}
          </p>
          <p className="text-lg font-semibold">{total !== null ? formatVnd(total) : "—"}</p>
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={!slots.length || total === null || submitting}
          className="rounded-md bg-primary px-5 py-2.5 font-medium text-primary-fg disabled:opacity-50"
        >
          {submitting ? "Đang đặt…" : "Đặt sân"}
        </button>
      </div>
    </div>
  );
}
