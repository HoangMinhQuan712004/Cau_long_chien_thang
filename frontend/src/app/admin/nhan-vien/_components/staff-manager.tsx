"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dropdown } from "@/components/ui/dropdown";
import { EmptyState } from "@/components/ui/empty-state";
import { InboxIcon, PlusIcon, SearchIcon, SearchXIcon } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import { ListFooter } from "@/components/ui/list-footer";
import { useSearchDraft } from "@/hooks/use-search-draft";
import { useUrlFilters } from "@/hooks/use-url-filters";
import type { Staff } from "@/lib/api/server";
import { hrefOf, patchParams } from "@/lib/url-params";
import { type StaffDialog, StaffDialogs, useUnlock } from "./staff-dialogs";
import { StaffDrawer } from "./staff-drawer";
import { fold, type StaffTexts } from "./staff-form-kit";
import { type StaffAction, StaffTable } from "./staff-table";

export type StatusFilter = "all" | "active" | "locked";

type Props = {
  staff: Staff[];
  /** Mã NV trên URL (`?ma=`): cuộn tới, tô nổi và focus dòng đó. */
  focusCode: string | null;
  /** Từ khóa / trạng thái trên URL (`?q=`, `?trang-thai=`): Back / F5 không mất. */
  initialQuery: string;
  initialStatus: StatusFilter;
  t: StaffTexts;
};

// Phân trang như màn Hội viên: 20 / 50 / 100 dòng, trang + số dòng trên URL (?trang=, ?so-dong=)
const PAGE_SIZES = [20, 50, 100] as const;

// Tham số URL (như Hội viên: ?q=&trang-thai=&trang=&so-dong=)
const PARAM = { q: "q", status: "trang-thai", page: "trang", size: "so-dong" } as const;

// Ghi tìm / lọc lên URL tại chỗ (không gọi lại server, không chất lịch sử); đổi tìm / lọc ⇒ về trang 1
function syncUrl(q: string, status: StatusFilter) {
  const params = patchParams<keyof typeof PARAM>(new URLSearchParams(window.location.search), PARAM, "page", { q, status });
  window.history.replaceState(null, "", hrefOf(window.location.pathname, params));
}

/** Màn Nhân viên: đầu trang + ô tìm / lọc trạng thái, bảng (thẻ trên điện thoại), ngăn chi tiết, các hộp thoại. */
export function StaffManager({ staff, focusCode, initialQuery, initialStatus, t }: Props) {
  const router = useRouter();
  const { searchParams, hrefWith, set } = useUrlFilters(PARAM, "page");
  const refresh = () => router.refresh();
  const [query, setQuery] = useState(initialQuery);
  const [status, setStatus] = useState<StatusFilter>(initialStatus);
  const [draft, setDraft] = useSearchDraft(query, (q) => {
    setQuery(q);
    syncUrl(q, status);
  }, 250);
  const [dialog, setDialog] = useState<StaffDialog | null>(null);
  const [detail, setDetail] = useState<{ id: number; sessions: boolean } | null>(null);
  // Mốc "bây giờ" cho "x phút trước" (không gọi Date.now khi render)
  const [now] = useState(() => Date.now());
  const unlock = useUnlock(t, refresh);

  // Mở từ link `?ma=` ⇒ đưa dòng ra giữa màn và focus tên (bàn phím / trình đọc màn hình bắt đầu từ đó)
  useEffect(() => {
    const el = focusCode ? document.querySelector<HTMLElement>(`[data-staff="${focusCode}"]`) : null;
    el?.scrollIntoView({ block: "center" });
    el?.focus({ preventScroll: true });
  }, [focusCode]);

  const changeStatus = (next: StatusFilter) => {
    setStatus(next);
    syncUrl(query, next);
  };
  // Xóa ô tìm (giữ lọc trạng thái); "Xóa bộ lọc" ở màn không kết quả ⇒ xóa cả trạng thái
  const clearSearch = (nextStatus = status) => {
    setDraft("");
    setQuery("");
    setStatus(nextStatus);
    syncUrl("", nextStatus);
  };

  const q = fold(query);
  const rows = staff.filter(
    (s) =>
      (status === "all" || s.is_active === (status === "active")) &&
      (!q || [s.full_name, s.staff_code, s.username].some((v) => fold(v).includes(q))),
  );
  // Phân trang phía client (API trả cả danh sách): STT đánh tiếp theo trang
  const pageSize = PAGE_SIZES.find((n) => String(n) === searchParams.get(PARAM.size)) ?? PAGE_SIZES[0];
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const page = Math.min(pageCount, Math.max(1, Math.trunc(Number(searchParams.get(PARAM.page))) || 1));
  const pageRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const activeCount = staff.filter((s) => s.is_active).length;
  const detailStaff = detail ? staff.find((s) => s.id === detail.id) : undefined;

  const onAction = (action: StaffAction, s: Staff) => {
    if (action === "detail" || action === "sessions") setDetail({ id: s.id, sessions: action === "sessions" });
    else if (action === "unlock") void unlock(s);
    else setDialog({ kind: action, staff: s });
  };
  const add = () => setDialog({ kind: "create" });

  const statusLabels: Record<StatusFilter, string> = { all: t.filterAll, active: t.active, locked: t.disabled };

  return (
    <div className="flex flex-col gap-4">
      {/* Đầu trang: tiêu đề + chữ phụ ngắn bên trái, "Thêm nhân viên" bên phải (điện thoại: chữ ngắn) */}
      <header className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <h1 className="text-xl font-bold sm:text-2xl">{t.title}</h1>
          <p className="text-xs text-muted tabular-nums sm:text-ui">
            {t.summary.replace("{total}", String(staff.length)).replace("{active}", String(activeCount))}
          </p>
        </div>
        <Button type="button" onClick={add} className="shrink-0">
          <PlusIcon />
          <span className="sm:hidden">{t.addShort}</span>
          <span className="hidden sm:inline">{t.add}</span>
        </Button>
      </header>

      {staff.length === 0 ? (
        <EmptyState icon={<InboxIcon />} title={t.empty} action={<Button type="button" onClick={add}><PlusIcon />{t.add}</Button>} />
      ) : (
        // Như Hội viên: khung chứa thanh lọc + bảng + chân phân trang; điện thoại không khung ngoài
        <Card bareOnMobile className="flex flex-col gap-3 sm:gap-4 sm:p-5">
          {/* Hàng công cụ: ô tìm + lọc trạng thái (Dropdown như Hội viên), cùng cao 36 / 38 */}
          <div className="flex items-center gap-2 sm:gap-3">
            <label htmlFor="staff-search" className="sr-only">
              {t.searchLabel}
            </label>
            <Input
              id="staff-search"
              compact
              value={draft}
              maxLength={100}
              placeholder={t.searchPlaceholder}
              startSlot={<SearchIcon />}
              onChange={(e) => setDraft(e.target.value)}
              onClear={() => clearSearch()}
              clearLabel={t.clearSearch}
              className="min-w-0 flex-1 sm:w-80 sm:flex-none [&_input]:h-9! [&_input]:text-sm sm:[&_input]:h-9.5!"
            />
            <Dropdown
              aria-label={t.statusFilter}
              value={status}
              onChange={(v) => changeStatus(v as StatusFilter)}
              options={(Object.keys(statusLabels) as StatusFilter[]).map((key) => ({ value: key, label: statusLabels[key] }))}
              // Điện thoại gọn ("Tất cả ▾", ~7rem); từ sm đủ "Trạng thái: Tất cả"
              renderValue={(o) => (
                <>
                  <span className="sm:hidden">{o?.label ?? t.filterAll}</span>
                  <span className="hidden sm:inline">{`${t.colStatus}: ${o?.label ?? t.filterAll}`}</span>
                </>
              )}
              active={status !== "all"}
              onClear={() => changeStatus("all")}
              clearLabel={t.clearStatus}
              className="w-28 shrink-0 [&>button]:h-9 sm:w-52 sm:[&>button]:h-9.5"
            />
          </div>
          <StaffTable
            rows={pageRows}
            indexOffset={(page - 1) * pageSize}
            now={now}
            focusCode={focusCode}
            onAction={onAction}
            t={t}
            empty={
              <EmptyState
                icon={<SearchXIcon />}
                title={t.noResults}
                action={
                  <Button type="button" variant="secondary" onClick={() => clearSearch("all")}>
                    {t.clearFilters}
                  </Button>
                }
              />
            }
          />
          <ListFooter
            page={page}
            pageSize={pageSize}
            pageSizes={PAGE_SIZES}
            total={rows.length}
            shown={pageRows.length}
            hrefFor={(n) => hrefWith({ page: n === 1 ? null : String(n) })}
            // Số dòng mặc định không ghi lên URL; đổi ⇒ về trang 1, giữ bộ lọc
            onPageSize={(n) => set({ size: n === PAGE_SIZES[0] ? null : String(n) })}
            t={t}
          />
        </Card>
      )}

      {detailStaff ? (
        <StaffDrawer
          staff={detailStaff}
          now={now}
          focusSessions={detail?.sessions ?? false}
          onClose={() => setDetail(null)}
          onAction={onAction}
          onChanged={refresh}
          t={t}
        />
      ) : null}
      {dialog ? (
        <StaffDialogs
          dialog={dialog}
          onClose={() => setDialog(null)}
          onChanged={refresh}
          // Đóng màn kết quả ⇒ tải lại bảng (server) và tô nổi dòng mới qua ?ma=
          onCreated={(s) => {
            setDialog(null);
            router.replace(`?ma=${encodeURIComponent(s.staff_code)}`, { scroll: false });
          }}
          t={t}
        />
      ) : null}
    </div>
  );
}
