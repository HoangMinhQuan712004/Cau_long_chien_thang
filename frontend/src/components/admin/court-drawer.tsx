"use client";

import { useCallback, useEffect, useState } from "react";
import { UnsavedGuard } from "@/components/admin/unsaved-guard";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";
import { Button } from "@/components/ui/button";
import { PencilIcon } from "@/components/ui/icons";
import { SidePanel } from "@/components/ui/side-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { CourtForm } from "./court-form";
import { formOf, type Resource, type ResourceType } from "./court-form-logic";
import { CourtOverview } from "./court-overview";
import { CourtRecent } from "./court-recent";
import { CourtStats } from "./court-stats";
import { useCourtForm } from "./use-court-form";

// Ngăn chi tiết sân: mở ⇒ gọi /detail một lần (thông tin, giá chỉ xem, lịch sắp tới); thống kê + giao dịch tự tải riêng.
// "Sửa" ⇒ thân ngăn thành form (PATCH theo version của /detail); đang sửa mà có thay đổi ⇒ hỏi khi rời trang.

/** Chi tiết sân; `resource` theo kiểu Resource (khung cao điểm là mảng [từ, đến], lỏng hơn tuple của OpenAPI). */
export type CourtDetail = Omit<components["schemas"]["ResourceDetailOut"], "resource"> & { resource: Resource };
type State = { status: "loading" } | { status: "error" } | { status: "ok"; detail: CourtDetail };
type Props = {
  code: string;
  resources: Resource[];
  types: ResourceType[];
  onClose: () => void;
  onSaved: (code: string) => void;
};

export function CourtDrawer({ code, resources, types, onClose, onSaved }: Props) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [isEditing, setIsEditing] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.GET("/api/v1/booking/resources/{code}/detail", { params: { path: { code } } }).catch(() => ({ data: undefined }));
    setState(data ? { status: "ok", detail: data } : { status: "error" });
  }, [code]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi mở ngăn
    void load();
  }, [load]);

  const detail = state.status === "ok" ? state.detail : null;
  const title = detail ? `${detail.resource.code} · ${detail.resource.name}` : code;

  if (detail && isEditing) {
    return (
      <EditPanel
        title={title}
        resource={detail.resource}
        resources={resources}
        types={types}
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
      closeLabel="Đóng"
      onClose={onClose}
      resizeLabel="Kéo để đổi bề rộng ngăn"
      storageKey="san.chi-tiet.rong"
      status={state.status}
      loadingLabel="Đang tải chi tiết sân…"
      errorText="Không tải được chi tiết sân. Đóng ngăn rồi mở lại để thử lại."
      skeleton={<DrawerSkeleton />}
      footer={
        <Button onClick={() => setIsEditing(true)}>
          <PencilIcon />
          Sửa sân
        </Button>
      }
    >
      {detail ? (
        <div className="flex flex-col divide-y">
          <CourtOverview detail={detail} typeName={types.find((t) => t.code === detail.resource.resource_type_code)?.name} />
          <CourtStats code={code} />
          <CourtRecent code={code} />
        </div>
      ) : null}
    </SidePanel>
  );
}

/** Ngăn ở chế độ sửa: form dùng chung với "Thêm sân", Lưu / Hủy ở chân ngăn. */
function EditPanel({ title, resource, resources, types, onCancel, onReload, onSaved, onClose }: {
  title: string;
  resource: Resource;
  resources: Resource[];
  types: ResourceType[];
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
      title={`Sửa ${title}`}
      closeLabel="Đóng"
      onClose={onClose}
      confirmClose={confirmClose}
      resizeLabel="Kéo để đổi bề rộng ngăn"
      storageKey="san.chi-tiet.rong"
      footer={
        <div className="flex w-full justify-end gap-2 [&>button]:h-11 [&>button]:flex-1 sm:[&>button]:h-9.5 sm:[&>button]:flex-none">
          <Button variant="secondary" onClick={onCancel} disabled={state.busy}>Hủy</Button>
          <Button onClick={() => void state.submit()} loading={state.busy}>{state.busy ? "Đang lưu…" : "Lưu"}</Button>
        </div>
      }
    >
      <CourtForm state={state} types={types} onReload={onReload} />
      <UnsavedGuard dirty={state.dirty} />
      {askClose ? (
        <ConfirmDialog
          danger
          title="Bỏ thay đổi?"
          body="Các thay đổi của sân chưa được lưu sẽ mất."
          cancelLabel="Tiếp tục sửa"
          confirmLabel="Bỏ thay đổi"
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
