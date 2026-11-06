"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { ActionMenu, type MenuAction } from "@/components/ui/action-menu";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EyeIcon, PencilIcon, TrashIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { api } from "@/lib/api/client";
import { errorText, write } from "@/lib/api/write";
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

/** Sân ngừng hoạt động: mờ từng ô nội dung; trạng thái và ⋯ giữ rõ (như dòng khóa ở Nhân viên). */
const dim = (r: Resource) => (r.is_active ? "" : "opacity-60");

const noop = () => () => {};
/** true chỉ ở trình duyệt (server và lúc hydrate là false). */
const useIsClient = () => useSyncExternalStore(noop, () => true, () => false);

/** Xác nhận xóa sân: Hủy | Xóa (đỏ), rộng bằng nhau; 409 (còn lịch sắp tới) hiện câu của backend trong hộp. */
function DeleteCourtDialog({ court, onClose, onDeleted, t }: { court: Resource; onClose: () => void; onDeleted: () => void; t: Dictionary["courts"] }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    if (busy) return;
    setBusy(true);
    setError("");
    const res = await write((key) =>
      api.DELETE("/api/v1/booking/resources/{code}", { params: { path: { code: court.code } }, headers: { "Idempotency-Key": key } }),
    );
    setBusy(false);
    // 404: đã bị xóa ở nơi khác ⇒ coi như xong
    if (res.ok || res.error.status === 404) onDeleted();
    else setError(errorText(res.error));
  }

  return (
    <Modal
      open
      sheet
      onClose={onClose}
      title={t.deleteTitle.replace("{name}", court.name)}
      footer={
        <div className="grid w-full grid-cols-2 gap-2">
          <Button type="button" variant="secondary" block onClick={onClose} disabled={busy}>
            {t.cancel}
          </Button>
          <Button type="button" variant="danger" block loading={busy} onClick={() => void confirm()}>
            {busy ? t.deleting : t.delete}
          </Button>
        </div>
      }
    >
      {error ? <Alert variant="error">{error}</Alert> : null}
      <p className="text-sm text-muted">{t.deleteBody}</p>
    </Modal>
  );
}

export function CourtsTable({ resources, types, weekdayPrice, canDelete, t }: {
  resources: Resource[];
  types: ResourceType[];
  /** Giá ngày thường, thấp điểm, theo mã loại sân (VND/giờ). */
  weekdayPrice: Record<string, number>;
  /** Có quyền booking.resources.delete ⇒ hiện "Xóa sân". */
  canDelete: boolean;
  t: Dictionary["courts"];
}) {
  const router = useRouter();
  const openCode = useSearchParams().get("san");
  // Ngăn đọc bề rộng đã lưu (localStorage) khi render ⇒ chỉ dựng ở trình duyệt, tránh lệch HTML khi mở thẳng link ?san=
  const isClient = useIsClient();
  const [form, setForm] = useState<Form | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  // ⋯ "Sửa sân" ⇒ ngăn mở thẳng chế độ sửa
  const [editCode, setEditCode] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Resource | null>(null);
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

  const open = (code: string, edit = false) => {
    setEditCode(edit ? code : null);
    setCourtParam(code);
  };
  const onDeleted = (court: Resource) => {
    setDeleting(null);
    setEditCode(null);
    setCourtParam(null);
    toast(t.deleted.replace("{name}", court.name));
    router.refresh();
  };
  const menu = (r: Resource): MenuAction[] => [
    { label: t.detail, icon: <EyeIcon />, onClick: () => open(r.code) },
    { label: t.edit, icon: <PencilIcon />, onClick: () => open(r.code, true) },
    ...(canDelete ? [{ label: t.delete, icon: <TrashIcon />, danger: true, onClick: () => setDeleting(r) }] : []),
  ];
  const openCourt = resources.find((r) => r.code === openCode);

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
                {/* Cột ⋯ dính phải: khung hẹp bảng cuộn ngang vẫn thấy và bấm được */}
                <th className="sticky right-0 w-14 bg-surface px-2 py-2 text-right font-medium">
                  <span className="sr-only">Thao tác</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {resources.map((r) => (
                // Cả dòng bấm được (chuột); menu ⋯ cho bàn phím / trình đọc màn hình
                <tr
                  key={r.code}
                  onClick={() => open(r.code)}
                  className={`group/row cursor-pointer border-b border-border last:border-0 hover:bg-primary-softer ${fresh === r.code || openCode === r.code ? "bg-primary-softer" : ""}`}
                >
                  <td className={`px-4 py-3 font-mono text-xs ${dim(r)}`}>{r.code}</td>
                  <td className={`px-4 py-3 font-medium ${dim(r)}`}>{r.name}</td>
                  <td className={`px-4 py-3 ${dim(r)}`}>{typeName.get(r.resource_type_code) ?? r.resource_type_name}</td>
                  <td className={`px-4 py-3 ${dim(r)}`}>
                    {r.schedule ? `${t5(r.schedule.open_time)} – ${t5(r.schedule.close_time)}` : "—"}
                    {r.pending_schedule ? (
                      <span className="mt-0.5 block text-xs text-muted">
                        → {t5(r.pending_schedule.open_time)} – {t5(r.pending_schedule.close_time)} từ {formatDayMonth(r.pending_schedule.effective_from)}
                      </span>
                    ) : null}
                  </td>
                  <td className={`px-4 py-3 text-right tabular-nums ${dim(r)}`}>
                    {weekdayPrice[r.resource_type_code] != null ? formatNumber(weekdayPrice[r.resource_type_code]) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${r.is_active ? "bg-primary-softer text-primary" : "bg-border text-muted"}`}>
                      {r.is_active ? "Hoạt động" : "Ngừng hoạt động"}
                    </span>
                  </td>
                  {/* Bấm ⋯ / mục menu không mở ngăn; nền theo dòng để cột dính không lộ chữ cuộn phía dưới */}
                  <td
                    onClick={(e) => e.stopPropagation()}
                    className={`sticky right-0 bg-surface px-2 py-1.5 text-right group-hover/row:bg-primary-softer ${fresh === r.code || openCode === r.code ? "bg-primary-softer" : ""}`}
                  >
                    <ActionMenu label={t.actions.replace("{name}", r.name)} items={menu(r)} />
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
          startEditing={editCode === openCode}
          // Sân không còn trên danh sách (vừa xóa ở nơi khác) ⇒ không hiện nút xóa
          onDelete={canDelete && openCourt ? () => setDeleting(openCourt) : undefined}
          t={t}
          onClose={() => (setEditCode(null), setCourtParam(null))}
          onSaved={(code) => (setFresh(code), router.refresh())}
        />
      ) : null}
      {deleting ? <DeleteCourtDialog court={deleting} onClose={() => setDeleting(null)} onDeleted={() => onDeleted(deleting)} t={t} /> : null}
    </div>
  );
}
