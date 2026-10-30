"use client";

import { Alert } from "./alert";
import { Drawer } from "./drawer";
import { Skeleton } from "./skeleton";

type SidePanelStatus = "loading" | "error" | "ok";

type SidePanelProps = {
  title: string;
  closeLabel: string;
  onClose: () => void;
  /** Thanh kéo dãn (từ lg) cho trình đọc màn hình. */
  resizeLabel: string;
  /** Khóa localStorage nhớ bề rộng, riêng mỗi ngăn (vd "hoi-vien.chi-tiet.rong"). */
  storageKey: string;
  status?: SidePanelStatus;
  /** Câu "Đang tải…" cho trình đọc màn hình. */
  loadingLabel?: string;
  /** Câu lỗi tải, nói cách xử lý. */
  errorText?: string;
  /** Khung tải đúng hình nội dung; không có ⇒ vài thanh chung. */
  skeleton?: React.ReactNode;
  /** Chỉ hiện khi status "ok". */
  footer?: React.ReactNode;
  children?: React.ReactNode;
};

/** Ngăn chi tiết bên phải dùng chung: kéo dãn + nhớ bề rộng, đang tải ⇒ Skeleton, lỗi ⇒ Alert, xong ⇒ nội dung. */
export function SidePanel({
  title,
  closeLabel,
  onClose,
  resizeLabel,
  storageKey,
  status = "ok",
  loadingLabel,
  errorText,
  skeleton,
  footer,
  children,
}: SidePanelProps) {
  return (
    <Drawer
      open
      onClose={onClose}
      title={title}
      closeLabel={closeLabel}
      side="right"
      resizable
      resizeLabel={resizeLabel}
      storageKey={storageKey}
      footer={status === "ok" ? footer : undefined}
    >
      {status === "loading" ? (
        <>
          {loadingLabel ? (
            <p role="status" className="sr-only">
              {loadingLabel}
            </p>
          ) : null}
          {skeleton ?? <DefaultSkeleton />}
        </>
      ) : null}
      {status === "error" ? <Alert variant="error">{errorText}</Alert> : null}
      {status === "ok" ? children : null}
    </Drawer>
  );
}

// Khung tải chung: một dòng tiêu đề và vài dòng nội dung
function DefaultSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <Skeleton className="h-6 w-1/2" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-3/4" />
    </div>
  );
}
