"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { Dropdown } from "@/components/ui/dropdown";
import { AlertCircleIcon, InfoIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { cn } from "@/lib/cn";
import { authFailure } from "./booking-dialogs";
import { getMoveTargets, sendMove } from "./requests";
import type { components as Api } from "@/lib/api/schema";
import type { Item, MoveTarget } from "./types";
import { btnCls, btnPrimaryCls, btnRowCls, ErrorBanner, raisedFooterCls } from "./ui";

// Đổi sân cho một booking: cùng ngày giờ, giữ mã, giá đã chốt và tiền đã thu. Danh sách sân trống do BE lọc (move-targets).

type Props = {
  item: Item;
  /** "S01 · Sân 1" của sân hiện tại; "16/11 · 18:00–20:00" */
  court: string;
  when: string;
  onBack: () => void;
  onClose: () => void;
  /** Đổi xong: item mới từ response (đã có lịch sử đổi sân) ⇒ cha quay về popup Thông tin. */
  onMoved: (next: Item) => void;
  onStale: (message: string) => Promise<void>;
};

// Lý do bắt buộc: gửi đúng chuỗi nhãn BE nhận (MoveIn.reason)
type Reason = NonNullable<Api["schemas"]["MoveIn"]["reason"]>;
const REASONS: Reason[] = ["Sân hỏng / bảo trì", "Ngừng sân"];
// Chip chọn nhanh như bộ lọc màn Đơn đặt sân; vùng chạm 44 trên điện thoại (nhìn 32)
const chipCls = (on: boolean) =>
  cn(
    "relative rounded-full border px-3 py-1.5 text-sm transition-colors focus-ring before:absolute before:-inset-y-1.5 before:inset-x-0 sm:before:hidden",
    on ? "border-primary bg-primary text-white" : "border-border bg-surface enabled:hover:bg-primary-softer",
  );

const label = (t: MoveTarget) => `${t.code} · ${t.name} · ${t.type_name}`;

export function MoveDialog({ item, court, when, onBack, onClose, onMoved, onStale }: Props) {
  const fieldId = useId();
  // undefined = đang tải
  const [targets, setTargets] = useState<MoveTarget[] | undefined>(undefined);
  const [target, setTarget] = useState("");
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState<Reason | null>(null);
  const [reasonError, setReasonError] = useState("");
  const reasonId = useId();

  const load = useCallback(async () => {
    const res = await getMoveTargets(item.code);
    if (res.ok) {
      setTargets(res.data);
      setTarget((cur) => (res.data.some((t) => t.code === cur) ? cur : (res.data[0]?.code ?? "")));
    } else {
      setTargets([]);
      setBanner(errorText(res.error));
    }
  }, [item.code]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải danh sách sân khi mở hộp thoại
    void load();
  }, [load]);

  async function confirm() {
    if (!target || !reason) return;
    setBanner("");
    setReasonError("");
    setBusy(true);
    try {
      const res = await write((key) => sendMove(key, item.code, { resource_code: target, version: item.version, reason }));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        // Thiếu / sai lý do (E-001): báo dưới nhóm lý do
        if (e.code === "E-001") return void setReasonError(errorText(e));
        // Dữ liệu đổi ở nơi khác (E-012) hoặc booking không còn đổi được (E-BOOK-6): tải lại bản mới
        if (e.code === "E-012" || e.code === "E-BOOK-6" || e.status === 404) return void (await onStale(errorText(e)));
        setBanner(errorText(e));
        // Sân vừa có lịch / không nhận khung này: tải lại danh sách sân trống
        if (e.code === "E-BOOK-8" || e.code === "E-BOOK-7") await load();
        return;
      }
      const picked = targets?.find((t) => t.code === target);
      toast(`Đã đổi ${item.code} sang ${picked ? `${picked.code} · ${picked.name}` : target}`, "Giá và tiền đã thu giữ nguyên");
      onMoved(res.data as Item);
    } finally {
      setBusy(false);
    }
  }

  const empty = targets !== undefined && targets.length === 0;
  return (
    <Modal
      open
      onClose={onClose}
      sheet
      size="medium"
      title="Đổi sân"
      // Header: dòng sân · giờ rồi câu giữ giá (span vì Modal bọc subtitle trong <p>)
      subtitle={
        <>
          {`${court} · ${when}`}
          <span className="mt-1 flex items-center gap-1.5 text-sm font-medium text-primary">
            <InfoIcon size={16} className="shrink-0" />
            Giá và tiền đã thu giữ nguyên, chỉ đổi sân.
          </span>
        </>
      }
      footerClassName={raisedFooterCls}
      footer={
        <div className={cn(btnRowCls, "grid-cols-2")}>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Quay lại
          </button>
          <button type="button" onClick={confirm} disabled={busy || !target || !reason} className={cn(btnPrimaryCls, "whitespace-nowrap")}>
            {busy ? "Đang đổi…" : "Đổi sân"}
          </button>
        </div>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <p className="text-sm text-muted">
        Mã booking: <span className="font-mono text-ui text-foreground">{item.code}</span>
      </p>
      <div>
        <label htmlFor={fieldId} className="mb-1.5 block text-label font-semibold text-muted">
          Sân mới
        </label>
        {targets === undefined ? (
          <p role="status" className="text-sm text-muted">Đang tải sân trống…</p>
        ) : empty ? (
          <p className="flex items-center gap-1.5 text-sm text-danger">
            <AlertCircleIcon size={16} className="shrink-0" />
            Không còn sân trống cùng khung giờ này.
          </p>
        ) : (
          <Dropdown
            id={fieldId}
            aria-label="Sân mới"
            value={target}
            onChange={setTarget}
            options={targets.map((t) => ({ value: t.code, label: label(t) }))}
            className="[&>button]:h-11 [&>button]:text-sm sm:[&>button]:h-9.5"
          />
        )}
      </div>
      <div>
        <p id={reasonId} className="mb-1.5 text-label font-semibold text-muted">
          Lý do <span className="text-danger">*</span>
        </p>
        {/* Chọn một (không bỏ chọn về rỗng): radiogroup dạng chip */}
        <div role="radiogroup" aria-labelledby={reasonId} aria-required className="flex flex-wrap gap-2">
          {REASONS.map((x) => (
            <button
              key={x}
              type="button"
              role="radio"
              aria-checked={reason === x}
              onClick={() => (setReason(x), setReasonError(""))}
              className={chipCls(reason === x)}
            >
              {x}
            </button>
          ))}
        </div>
        {reasonError ? (
          <p role="alert" className="mt-1.5 text-xs text-danger">{reasonError}</p>
        ) : target && !reason ? (
          <p className="mt-1.5 text-xs text-muted">Chọn lý do để đổi sân.</p>
        ) : null}
      </div>
    </Modal>
  );
}
