"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { UnsavedGuard } from "@/components/admin/unsaved-guard";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";
import { Button } from "@/components/ui/button";
import { PencilIcon, TrashIcon } from "@/components/ui/icons";
import { SidePanel } from "@/components/ui/side-panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { toast } from "@/lib/feedback";
import { CourtForm } from "./court-form";
import { formOf, type Resource, type ResourceType } from "./court-form-logic";
import { CourtOverview } from "./court-overview";
import { CourtStats } from "./court-stats";
import { useCourtForm } from "./use-court-form";

// Ngăn chi tiết sân: mở ⇒ gọi /detail một lần (thông tin, giá chỉ xem, lịch sắp tới); thống kê + giao dịch tự tải riêng.
// "Sửa" ⇒ thân ngăn thành form (PATCH theo version của /detail); đang sửa mà có thay đổi ⇒ hỏi khi rời trang.

/** Chi tiết sân; `resource` theo kiểu Resource (khung cao điểm là mảng [từ, đến], lỏng hơn tuple của OpenAPI). */
export type CourtDetail = Omit<components["schemas"]["ResourceDetailOut"], "resource"> & { resource: Resource };
type State = { status: "loading" } | { status: "error" } | { status: "gone" } | { status: "ok"; detail: CourtDetail };
type Props = {
  code: string;
  /** Mở thẳng chế độ sửa (mục "Sửa sân" của menu ⋯ trên bảng). */
  startEditing?: boolean;
  /** Có quyền xóa ⇒ hiện nút "Xóa sân" ở chân ngăn. */
  onDelete?: () => void;
  t: Dictionary["courts"];
  resources: Resource[];
  types: ResourceType[];
  onClose: () => void;
  onSaved: (code: string) => void;
};

export function CourtDrawer({ code, startEditing = false, onDelete, t, resources, types, onClose, onSaved }: Props) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [isEditing, setIsEditing] = useState(startEditing);

  const load = useCallback(async () => {
    const res = await api.GET("/api/v1/booking/resources/{code}/detail", { params: { path: { code } } }).catch(() => null);
    if (res?.data) setState({ status: "ok", detail: res.data });
    else setState({ status: res?.response.status === 404 ? "gone" : "error" });
  }, [code]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi mở ngăn
    void load();
  }, [load]);

  // ?san= trỏ tới sân đã xóa / mã lạ: báo một lần rồi đóng ngăn, về danh sách
  const isGone = state.status === "gone";
  const goneNotified = useRef(false);
  useEffect(() => {
    if (!isGone || goneNotified.current) return;
    goneNotified.current = true;
    toast(t.gone, undefined, "info");
    onClose();
  }, [isGone, onClose, t.gone]);

  const detail = state.status === "ok" ? state.detail : null;
  const title = detail ? `${detail.resource.code} · ${detail.resource.name}` : code;

  if (detail && isEditing) {
    return (
      <EditPanel
        title={title}
        resource={detail.resource}
        resources={resources}
        types={types}
        t={t}
        onCancel={() => setIsEditing(false)}
        onReload={() => {
          // Dữ liệu đã đổi ở máy khác (E-CFG-7): về chế độ xem với bản mới nhất
          setIsEditing(false);
          setState({ status: "loading" });
          void load();
        }}
        onSaved={(c) => {
          setIsEditing(false);
          onSaved(c);
          void load();
        }}
        onClose={onClose}
      />
    );
  }

  return (
    <SidePanel
      title={title}
      closeLabel={t.drawer.close}
      onClose={onClose}
      resizeLabel={t.drawer.resize}
      storageKey="san.chi-tiet.rong"
      status={isGone ? "loading" : state.status}
      loadingLabel={t.drawer.loading}
      errorText={t.drawer.error}
      skeleton={<DrawerSkeleton />}
      footer={
        <div className="flex w-full justify-end gap-2">
          {onDelete ? (
            <Button variant="secondary" className="border-danger text-danger" onClick={onDelete}>
              <TrashIcon />
              {t.delete}
            </Button>
          ) : null}
          <Button onClick={() => setIsEditing(true)}>
            <PencilIcon />
            {t.edit}
          </Button>
        </div>
      }
    >
      {detail ? (
        <div className="flex flex-col divide-y">
          <CourtOverview detail={detail} typeName={types.find((t) => t.code === detail.resource.resource_type_code)?.name} />
          <CourtStats code={code} />
        </div>
      ) : null}
    </SidePanel>
  );
}

/** Ngăn ở chế độ sửa: form dùng chung với "Thêm sân", Lưu / Hủy ở chân ngăn. */
function EditPanel({ title, resource, resources, types, t, onCancel, onReload, onSaved, onClose }: {
  title: string;
  resource: Resource;
  resources: Resource[];
  types: ResourceType[];
  t: Dictionary["courts"];
  onCancel: () => void;
  onReload: () => void;
  onSaved: (code: string) => void;
  onClose: () => void;
}) {
  const state = useCourtForm(formOf(resource), resources, onSaved);
  // Đang sửa có thay đổi: ✕ / Esc / bấm nền đều hỏi "Bỏ thay đổi?" trước khi đóng ngăn
  const [askClose, setAskClose] = useState(false);
  const confirmClose = () => {
    if (!state.dirty) return true;
    setAskClose(true);
    return false;
  };
  return (
    <SidePanel
      title={t.drawer.editTitle.replace("{title}", title)}
      closeLabel={t.drawer.close}
      onClose={onClose}
      confirmClose={confirmClose}
      resizeLabel={t.drawer.resize}
      storageKey="san.chi-tiet.rong"
      footer={
        <div className="grid w-full grid-cols-2 gap-2">
          <Button variant="secondary" block onClick={onCancel} disabled={state.busy}>{t.cancel}</Button>
          <Button block onClick={() => void state.submit()} loading={state.busy}>{state.busy ? t.saving : t.drawer.save}</Button>
        </div>
      }
    >
      <CourtForm state={state} types={types} onReload={onReload} t={t} />
      <UnsavedGuard dirty={state.dirty} />
      {askClose ? (
        <ConfirmDialog
          danger
          title={t.drawer.discardTitle}
          body={t.drawer.discardBody}
          cancelLabel={t.drawer.keepEditing}
          confirmLabel={t.drawer.discard}
          onClose={() => setAskClose(false)}
          onConfirm={async () => {
            setAskClose(false);
            onClose();
            return null;
          }}
        />
      ) : null}
    </SidePanel>
  );
}

function DrawerSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}
