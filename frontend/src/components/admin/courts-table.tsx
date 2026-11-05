"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { toast } from "@/lib/feedback";
import { formatDayMonth, formatNumber } from "@/lib/format";
import { CourtDrawer } from "./court-drawer";
import { CourtFormDialog } from "./court-form-dialog";
import { emptyForm, t5, type Form, type Resource, type ResourceType } from "./court-form-logic";

// Danh sách sân (tab Sân & bảng giá): bấm một dòng ⇒ ngăn chi tiết (?san=MÃ trên URL, Back đóng được); "+ Thêm sân" ⇒ popup.

/** Đổi ?san= trên URL không tải lại trang server (Next đồng bộ useSearchParams với history). */
function setCourtParam(code: string | null) {
  const url = new URL(window.location.href);
  if (code) url.searchParams.set("san", code);
  else url.searchParams.delete("san");
  if (code) window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
}

const noop = () => () => {};
/** true chỉ ở trình duyệt (server và lúc hydrate là false). */
const useIsClient = () => useSyncExternalStore(noop, () => true, () => false);

export function CourtsTable({ resources, types, weekdayPrice }: {
  resources: Resource[];
  types: ResourceType[];
  /** Giá ngày thường, thấp điểm, theo mã loại sân (VND/giờ). */
  weekdayPrice: Record<string, number>;
}) {
  const router = useRouter();
  const openCode = useSearchParams().get("san");
  // Ngăn đọc bề rộng đã lưu (localStorage) khi render ⇒ chỉ dựng ở trình duyệt, tránh lệch HTML khi mở thẳng link ?san=
  const isClient = useIsClient();
  const [form, setForm] = useState<Form | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const typeName = new Map(types.map((t) => [t.code, t.name]));
  const active = resources.filter((r) => r.is_active).length;

  useEffect(() => {
    if (!fresh) return;
    const t = setTimeout(() => setFresh(null), 3000);
    return () => clearTimeout(t);
  }, [fresh]);

  const reload = () => {
    setForm(null);
    router.refresh();
    toast("Đã tải lại dữ liệu mới nhất.", undefined, "info");
  };

  return (
    <div className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
        <h2 className="text-base font-semibold">
          Danh sách sân ({resources.length}) · {active} hoạt động, {resources.length - active} ngừng
        </h2>
        <button type="button" onClick={() => setForm(emptyForm(types))} className="ml-auto min-h-11 rounded-md bg-primary px-4 py-2 text-sm font-medium text-white sm:min-h-0">
          + Thêm sân
        </button>
      </div>

      {resources.length === 0 ? (
        <p className="p-6 text-center text-sm text-muted">Chưa có sân nào. Bấm “Thêm sân” để bắt đầu.</p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-176 text-left text-sm">
            <thead className="text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 font-medium">Mã</th>
                <th className="px-4 py-2 font-medium">Sân</th>
                <th className="px-4 py-2 font-medium">Loại sân</th>
                <th className="px-4 py-2 font-medium">Giờ mở cửa</th>
                <th className="px-4 py-2 text-right font-medium">Giá ngày thường (₫)</th>
                <th className="px-4 py-2 font-medium">Trạng thái</th>
                <th className="px-4 py-2 text-right font-medium">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {resources.map((r) => (
                // Cả dòng bấm được (chuột); nút "Chi tiết" cho bàn phím / trình đọc màn hình
                <tr
                  key={r.code}
                  onClick={() => setCourtParam(r.code)}
                  className={`cursor-pointer border-b border-border last:border-0 hover:bg-primary-softer ${r.is_active ? "" : "opacity-60"} ${fresh === r.code || openCode === r.code ? "bg-primary-softer" : ""}`}
                >
                  <td className="px-4 py-3 font-mono text-xs">{r.code}</td>
                  <td className="px-4 py-3 font-medium">{r.name}</td>
                  <td className="px-4 py-3">{typeName.get(r.resource_type_code) ?? r.resource_type_name}</td>
                  <td className="px-4 py-3">
                    {r.schedule ? `${t5(r.schedule.open_time)} – ${t5(r.schedule.close_time)}` : "—"}
                    {r.pending_schedule ? (
                      <span className="mt-0.5 block text-xs text-muted">
                        → {t5(r.pending_schedule.open_time)} – {t5(r.pending_schedule.close_time)} từ {formatDayMonth(r.pending_schedule.effective_from)}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {weekdayPrice[r.resource_type_code] != null ? formatNumber(weekdayPrice[r.resource_type_code]) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${r.is_active ? "bg-primary-softer text-primary" : "bg-border text-muted"}`}>
                      {r.is_active ? "Hoạt động" : "Ngừng hoạt động"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button type="button" onClick={(e) => (e.stopPropagation(), setCourtParam(r.code))} className="min-h-11 text-primary hover:underline sm:min-h-0">
                      Chi tiết<span className="sr-only"> {r.name}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {form ? (
        <CourtFormDialog
          initial={form}
          resources={resources}
          types={types}
          onClose={() => setForm(null)}
          onSaved={(code) => (setFresh(code), setForm(null), router.refresh())}
          onReload={reload}
        />
      ) : null}
      {isClient && openCode ? (
        <CourtDrawer
          key={openCode}
          code={openCode}
          resources={resources}
          types={types}
          onClose={() => setCourtParam(null)}
          onSaved={(code) => (setFresh(code), router.refresh())}
        />
      ) : null}
    </div>
  );
}
