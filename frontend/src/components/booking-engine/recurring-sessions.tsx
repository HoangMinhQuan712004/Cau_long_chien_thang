"use client";

import { Dropdown } from "@/components/ui/dropdown";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatDayMonthYear, formatVnd, hhmm } from "@/lib/format";
import { dowName, hourOptions, isoDow, KIND_LABEL, pad, reasonText, type Tweak } from "./recurring-utils";
import type { Calendar, RecurringPreview, RecurringSessionIn, RecurringSuggestion } from "./types";
import { dropdownCls } from "./ui";

// Bước 3 của hộp Đặt sân định kỳ – cấu trúc gốc của dev (T-043 AC4): buổi LỖI bung riêng từng khối (Sửa giờ / sân, Bỏ buổi),
// buổi hợp lệ gom MỘT dòng "✓ n buổi hợp lệ · Xem ▾" (bấm mới bung). Tóm tắt dính đầu nhóm + "Bỏ hết buổi lỗi".
// Gợi ý: mỗi buổi lỗi có các thẻ "Đổi giờ / Đổi sân" ghi rõ giờ + sân + giá sau khi đổi; thêm nút đổi cả loạt buổi cùng thứ.

type Props = {
  preview: RecurringPreview | null;
  calculating: boolean;
  resources: Calendar["resources"];
  columns: number[];
  tweaks: Record<string, Tweak>;
  removedDays: RecurringSessionIn[];
  editingDay: string | null;
  setEditingDay: (d: string | null) => void;
  setTweak: (day: string, t: Tweak | null) => void;
  applySuggestion: (day: string, sg: RecurringSuggestion) => void;
  showOk: boolean;
  setShowOk: (v: boolean) => void;
};

type Session = RecurringPreview["sessions"][number];

const linkBtn = "relative rounded-md px-2 py-1 text-sm font-semibold focus-ring before:absolute before:inset-x-0 before:-inset-y-2";
// Nút trên khối buổi: 32px nhìn, vùng chạm ẩn 44px
const btn = "relative inline-flex min-h-8 items-center rounded-lg px-2.5 py-1 text-left text-sm focus-ring before:absolute before:inset-x-0 before:-inset-y-1.5";
const hintBtn = cn(btn, "border border-primary bg-surface font-medium text-primary hover:bg-primary-softer");
const outlineBtn = cn(btn, "border border-border bg-surface hover:bg-primary-softer");
const ghostBtn = cn(btn, "text-muted hover:bg-primary-softer hover:text-primary");
/** "T5 05/11" (điện thoại, bỏ năm). */
const dayShort = (d: string) => `${dowName(d)} ${formatDayMonth(d)}`;
const day = (d: string) => `${dowName(d)} ${formatDayMonthYear(d)}`;

export function SessionsPanel(props: Props) {
  const { preview, calculating, removedDays, setTweak, applySuggestion, showOk, setShowOk } = props;
  if (!preview && removedDays.length === 0) return null;
  const sessions = preview?.sessions ?? [];
  const bad = sessions.filter((s) => !s.ok);
  const good = sessions.filter((s) => s.ok);

  // "Áp cho mọi buổi {thứ} lỗi" (như dev): nhóm các buổi lỗi cùng thứ có cùng kiểu gợi ý (≥ 2 buổi)
  const bulk = new Map<string, { dow: string; kind: RecurringSuggestion["kind"]; days: { date: string; sg: RecurringSuggestion }[] }>();
  for (const s of bad) {
    for (const sg of s.suggestions ?? []) {
      const k = `${isoDow(s.date)}|${sg.kind}`;
      const g = bulk.get(k) ?? { dow: dowName(s.date), kind: sg.kind, days: [] };
      g.days.push({ date: s.date, sg });
      bulk.set(k, g);
    }
  }
  const bulkList = [...bulk.values()].filter((g) => g.days.length >= 2);

  return (
    <section aria-label="Các buổi sẽ đặt" aria-busy={calculating} className={cn("space-y-2 transition-opacity motion-reduce:transition-none", calculating && "opacity-60")}>
      {preview ? (
        // Tóm tắt dính trên khi cuộn (nền trắng che phần bên dưới)
        <div className="sticky -top-5 z-10 -mx-5 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface px-5 py-2">
          <p className="text-sm tabular-nums" aria-live="polite">
            <b>{preview.count}</b> buổi
            {bad.length > 0 ? <b className="text-danger"> · {bad.length} lỗi</b> : <span className="text-primary"> · đều hợp lệ</span>}
          </p>
          {bad.length > 0 ? (
            <span className="ml-auto flex gap-1">
              {bad.length >= 2 ? (
                <button type="button" onClick={() => bad.forEach((s) => setTweak(s.date, { removed: true }))} className={cn(linkBtn, "text-danger hover:bg-danger-soft")}>
                  Bỏ hết buổi lỗi
                </button>
              ) : null}
            </span>
          ) : null}
        </div>
      ) : null}

      {/* Buổi lỗi: mỗi buổi một khối nền đỏ nhạt + vạch trái, xếp liền nhau cách 8px */}
      {bulkList.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {bulkList.map((g) => (
            <button key={`${g.dow}-${g.kind}`} type="button" onClick={() => g.days.forEach((d) => applySuggestion(d.date, d.sg))} className={hintBtn}>
              {KIND_LABEL[g.kind]} cho cả {g.days.length} buổi {g.dow} lỗi
            </button>
          ))}
        </div>
      ) : null}

      {bad.length > 0 ? (
        <ul className="space-y-2" aria-label="Buổi lỗi">
          {bad.map((s) => (
            <SessionItem key={s.date} s={s} bad {...props} />
          ))}
        </ul>
      ) : null}

      {removedDays.length > 0 ? (
        <ul className="divide-y divide-border" aria-label="Buổi đã bỏ">
          {removedDays.map((r) => (
            <li key={r.date} className="flex min-h-10 items-center justify-between gap-3 text-ui text-muted tabular-nums">
              <span>
                <span className="line-through">{day(r.date)}</span>
              </span>
              <button type="button" onClick={() => setTweak(r.date, null)} className={cn(linkBtn, "text-primary hover:bg-primary-softer")}>
                Hoàn tác
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {/* Buổi hợp lệ: một dòng thu gọn, bấm mới bung danh sách kẻ dòng */}
      {good.length > 0 ? (
        <div>
          <button
            type="button"
            onClick={() => setShowOk(!showOk)}
            aria-expanded={showOk}
            className="flex min-h-10 w-full items-center justify-between gap-2 rounded-lg bg-background px-3 text-left text-sm focus-ring hover:bg-primary-softer/60"
          >
            <span>
              <b className="text-primary">✓</b> <b>{good.length}</b> buổi hợp lệ
            </span>
            <span className="text-muted">{showOk ? "Thu gọn ▴" : "Xem ▾"}</span>
          </button>
          {showOk ? (
            <ul className="mt-1 divide-y divide-border">
              {good.map((s) => (
                <SessionItem key={s.date} s={s} bad={false} {...props} />
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function SessionItem({ s, bad, resources, columns, tweaks, editingDay, setEditingDay, setTweak, applySuggestion }: Props & { s: Session; bad: boolean }) {
  const tw = tweaks[s.date];
  const editing = editingDay === s.date;
  const startH = Number(s.start_time.slice(0, 2));
  const endH = Number(s.end_time.slice(0, 2));
  const label = day(s.date);
  const court = resources.find((r) => r.code === s.resource_code)?.name ?? s.resource_code;
  // Buổi lỗi: thẻ gợi ý ghi rõ buổi sẽ thành giờ + sân + giá nào; không có gợi ý thì nói cách xử lý tiếp theo
  const options = s.suggestions ?? [];
  const hints = !bad ? null : options.length > 0 ? (
    <div role="group" aria-label={`Lựa chọn còn trống cho ${label}`}>
      <p className="mb-1.5 text-xs font-medium">Còn trống, bấm để đổi sang:</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((sg) => {
          const time = `${pad(sg.start_hour)}:00–${pad(sg.end_hour)}:00`;
          return (
            <button
              key={`${sg.kind}-${sg.resource_code}-${sg.start_hour}`}
              type="button"
              onClick={() => applySuggestion(s.date, sg)}
              aria-label={`Đổi buổi ${label} sang ${time}, ${sg.resource_name}, ${formatVnd(sg.price)}`}
              className="flex min-h-11 w-full items-center justify-between gap-3 rounded-lg border border-primary bg-surface px-3 py-1.5 text-left focus-ring hover:bg-primary-softer"
            >
              <span className="min-w-0">
                <span className="block text-xs font-medium text-primary">{KIND_LABEL[sg.kind]}</span>
                <span className="block truncate text-sm font-semibold tabular-nums">
                  {time} · {sg.resource_name}
                </span>
              </span>
              <span className="shrink-0 text-sm tabular-nums">{formatVnd(sg.price)}</span>
            </button>
          );
        })}
      </div>
    </div>
  ) : (
    <p className="text-xs text-muted">Không có giờ trống gần đó. Hãy tự chọn giờ khác hoặc bỏ buổi này.</p>
  );
  const actions = (
    <>
      <button type="button" onClick={() => setEditingDay(editing ? null : s.date)} aria-expanded={editing} aria-label={`${editing ? "Xong sửa" : bad ? "Tự chọn giờ / sân" : "Sửa giờ / sân"} buổi ${label}`} className={bad ? outlineBtn : ghostBtn}>
        {editing ? "Xong" : bad ? "Tự chọn giờ / sân" : "Sửa giờ / sân"}
      </button>
      <button type="button" onClick={() => setTweak(s.date, { removed: true })} aria-label={`Bỏ buổi ${label}`} className={ghostBtn}>
        Bỏ buổi
      </button>
      {tw ? (
        <button type="button" onClick={() => setTweak(s.date, null)} aria-label={`Hoàn tác buổi ${label}`} className={ghostBtn}>
          Hoàn tác
        </button>
      ) : null}
    </>
  );

  return (
    <li className={cn(bad ? "rounded-r-lg border-l-3 border-danger bg-danger-soft px-3 py-2" : "py-1.5", "text-ui")}>
      {bad ? (
        // Điện thoại: đầu khối 2 dòng – "T5 05/11" + badge lý do bên phải (cách ≥ 8px), dòng 2 "17:00–19:00 · Sân 1"
        <div className="flex items-start justify-between gap-2 sm:hidden">
          <span className="min-w-0 tabular-nums">
            <span className="block font-semibold">
              {dayShort(s.date)}
              {tw ? <span className="ml-1.5 rounded-full bg-primary-softer px-1.5 py-0.5 text-2xs font-medium text-primary">Đã chỉnh</span> : null}
            </span>
            <span className="block whitespace-nowrap text-muted">
              {hhmm(s.start_time)}–{hhmm(s.end_time)} · {court}
            </span>
          </span>
          <span className="shrink-0 rounded-full bg-danger/10 px-2 py-0.5 text-xs font-semibold text-danger">{s.reason_text ?? reasonText(s.reason)}</span>
        </div>
      ) : null}
      <div className={cn("flex-wrap items-center gap-x-3 gap-y-1", bad ? "hidden sm:flex" : "flex")}>
        <span className="min-w-0 flex-1 tabular-nums">
          <span className={cn("whitespace-nowrap", bad ? "font-semibold" : "font-medium")}>
            {label} · {hhmm(s.start_time)}–{hhmm(s.end_time)}
          </span>
          <span className="text-muted"> · {court}</span>
          {tw ? <span className="ml-1.5 rounded-full bg-primary-softer px-1.5 py-0.5 text-2xs font-medium text-primary">Đã chỉnh</span> : null}
        </span>
        {bad ? (
          <span className="rounded-full bg-danger/10 px-2 py-0.5 text-xs font-semibold text-danger">{s.reason_text ?? reasonText(s.reason)}</span>
        ) : (
          <span className="text-muted tabular-nums">{s.price_after_discount !== null ? formatVnd(s.price_after_discount) : "—"}</span>
        )}
        {bad ? null : <span className="ml-auto flex flex-wrap justify-end gap-0.5">{actions}</span>}
      </div>

      {bad ? (
        // Gợi ý ở trên, cụm Tự chọn / Bỏ căn phải ở hàng dưới (mọi cỡ màn hình)
        <div className="mt-2 space-y-2">
          {hints}
          <span className="flex justify-end gap-2">{actions}</span>
        </div>
      ) : null}

      {editing ? (
        // Điện thoại: Sân một hàng, Từ / Đến chung hàng dưới; từ sm: 3 cột
        <div className="mt-2 grid grid-cols-2 gap-2 pb-1 sm:grid-cols-3">
          <div className="col-span-2 flex flex-col gap-1 sm:col-span-1">
            <span aria-hidden className="text-xs text-muted">Sân</span>
            <Dropdown aria-label={`Sân buổi ${label}`} value={s.resource_code ?? ""} onChange={(v) => setTweak(s.date, { resource_code: v })} options={resources.map((r) => ({ value: r.code, label: r.name }))} className={dropdownCls} />
          </div>
          <div className="flex flex-col gap-1">
            <span aria-hidden className="text-xs text-muted">Từ</span>
            <Dropdown
              aria-label={`Giờ bắt đầu buổi ${label}`}
              value={String(startH)}
              // Đổi giờ bắt đầu ⇒ giữ độ dài buổi, kẹp về giờ cuối của lịch (tối thiểu 1 tiếng)
              onChange={(v) => setTweak(s.date, { start_hour: Number(v), end_hour: Math.max(Number(v) + 1, Math.min(Number(v) + endH - startH, (columns[columns.length - 1] ?? 22) + 1)) })}
              options={hourOptions(columns)}
              className={dropdownCls}
            />
          </div>
          <div className="flex flex-col gap-1">
            <span aria-hidden className="text-xs text-muted">Đến</span>
            <Dropdown aria-label={`Giờ kết thúc buổi ${label}`} value={String(endH)} onChange={(v) => setTweak(s.date, { end_hour: Number(v) })} options={hourOptions(columns.filter((h) => h + 1 > startH), true)} className={dropdownCls} />
          </div>
        </div>
      ) : null}
    </li>
  );
}
