import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage } from "@/lib/api/client";
import type { StaffSession, StaffSessionHistory } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatDateTime, formatDayMonth, formatTime, vnDate } from "@/lib/format";
import { DeviceIcon, deviceName } from "../../ho-so/_components/sessions-panel";
import type { StaffTexts } from "./staff-form-kit";

// Ngăn chi tiết nhân viên: "Thiết bị đang đăng nhập" (như "Nơi bạn đăng nhập" ở Hồ sơ của tôi; không IP, không user-agent)
// + "Lịch sử đăng nhập" (20 lần gần nhất). Đăng xuất một thiết bị có hộp xác nhận nhẹ.

type Device = StaffSession;
type EndReason = StaffSessionHistory["end_reason"];

const HISTORY_LIMIT = 20;
const short = (iso: string) => `${formatDayMonth(vnDate(iso))} ${formatTime(iso)}`;

/** Thiết bị đang đăng nhập của một nhân viên + đăng xuất từ xa từng thiết bị. */
export function StaffDevices({ t, staffId, onChanged }: { t: StaffTexts; staffId: number; onChanged: () => void }) {
  // undefined = đang tải, null = lỗi
  const [devices, setDevices] = useState<Device[] | null | undefined>(undefined);
  const [confirm, setConfirm] = useState<Device | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.GET("/api/v1/admin/staff/{staff_id}/sessions", { params: { path: { staff_id: staffId } } });
      setDevices(data ?? null);
    } catch {
      setDevices(null);
    }
  }, [staffId]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi mở ngăn
    void load();
  }, [load]);

  async function revoke(d: Device): Promise<string | null> {
    try {
      const res = await api.DELETE("/api/v1/admin/staff/{staff_id}/sessions/{session_id}", {
        params: { path: { staff_id: staffId, session_id: d.id } },
      });
      // 404: thiết bị đã tự đăng xuất ⇒ coi như xong, tải lại
      if (!res.response.ok && res.response.status !== 404) return errorMessage(res.error, t.errors.generic);
      toast(t.revoked);
      setConfirm(null);
      await load();
      onChanged();
      return null;
    } catch {
      return t.errors.network;
    }
  }

  if (devices === undefined) return <Skeleton className="h-16 w-full rounded-xl" />;
  if (devices === null) return <Alert variant="error">{t.sessionsError}</Alert>;
  if (devices.length === 0) return <p className="text-ui text-muted">{t.sessionsEmpty}</p>;

  return (
    <>
      <ul className="flex flex-col gap-2">
        {devices.map((d) => (
          <li key={d.id} className="flex items-center gap-3 rounded-xl border p-3">
            <span aria-hidden className="shrink-0 text-primary">
              <DeviceIcon type={d.device_type} />
            </span>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="text-sm font-semibold wrap-anywhere">{deviceName(d, t.device)}</span>
              <span className="text-ui text-muted tabular-nums">{t.device.signedInAt.replace("{time}", formatDateTime(d.created_at))}</span>
            </span>
            <Button variant="secondary" onClick={() => setConfirm(d)} aria-label={`${t.revoke}: ${deviceName(d, t.device)}`}>
              {t.revoke}
            </Button>
          </li>
        ))}
      </ul>
      {confirm ? (
        <ConfirmDialog
          danger
          title={t.revokeTitle.replace("{device}", deviceName(confirm, t.device))}
          body={<p className="text-ui text-muted">{t.revokeBody}</p>}
          cancelLabel={t.cancel}
          confirmLabel={t.revoke}
          onClose={() => setConfirm(null)}
          onConfirm={() => revoke(confirm)}
        />
      ) : null}
    </>
  );
}

/** 20 lần đăng nhập gần nhất: thiết bị · "05/11 15:33 → 05/11 18:02" · nhãn kết thúc. Danh sách kẻ dòng, không khung. */
export function StaffLoginHistory({ t, staffId }: { t: StaffTexts; staffId: number }) {
  const [items, setItems] = useState<StaffSessionHistory[] | null | undefined>(undefined);

  useEffect(() => {
    let isCurrent = true;
    api
      .GET("/api/v1/admin/staff/{staff_id}/sessions/history", { params: { path: { staff_id: staffId }, query: { limit: HISTORY_LIMIT } } })
      .then(({ data }) => isCurrent && setItems(data ?? null))
      .catch(() => isCurrent && setItems(null));
    return () => {
      isCurrent = false;
    };
  }, [staffId]);

  if (items === undefined) return <Skeleton className="h-24 w-full rounded-xl" />;
  if (items === null) return <p className="text-ui text-muted">{t.historyError}</p>;
  if (items.length === 0) return <p className="text-ui text-muted">{t.historyEmpty}</p>;

  return (
    <ul className="divide-y text-ui">
      {items.map((h) => {
        const reason: EndReason = h.is_active ? "active" : h.end_reason;
        return (
          <li key={h.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-2">
            <span aria-hidden className="shrink-0 text-muted [&>svg]:size-4">
              <DeviceIcon type={h.device_type} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-medium wrap-anywhere">{deviceName(h, t.device)}</span>
              <span className="block text-muted tabular-nums">
                {short(h.created_at)}
                {h.ended_at ? ` → ${short(h.ended_at)}` : ""}
              </span>
            </span>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold",
                reason === "active" ? "bg-primary-softer text-primary" : "bg-background text-muted",
              )}
            >
              {t.endReasons[reason]}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
