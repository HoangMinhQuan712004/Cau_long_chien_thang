"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { ActionMenu, type MenuAction } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { type Column, DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { EyeIcon, InboxIcon, PencilIcon, PlusIcon, TrashIcon } from "@/components/ui/icons";
import { ListFooter } from "@/components/ui/list-footer";
import { PageActions, PageHeader } from "@/components/ui/page-header";
import { useUrlFilters } from "@/hooks/use-url-filters";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatDayMonth, formatVnd } from "@/lib/format";
import { CourtDrawer } from "./court-drawer";
import { CourtFormDialog, DeleteCourtDialog } from "./court-form-dialog";
import { emptyForm, t5, type Form, type Resource, type ResourceType } from "./court-form-logic";
import { SanTabs } from "./san-tabs";

// Màn Danh mục sân (như Nhân viên / Hội viên): đầu trang + tab, bảng sân (thẻ trên điện thoại).
// Bấm dòng / tên ⇒ ngăn chi tiết (?san=MÃ trên URL, Back đóng được); ⋯ có Chi tiết / Sửa / Xóa; "Thêm sân" ⇒ popup.

/** Đổi ?san= trên URL không tải lại trang server (Next đồng bộ useSearchParams với history). */
function setCourtParam(code: string | null) {
  const url = new URL(window.location.href);
  if (code) url.searchParams.set("san", code);
  else url.searchParams.delete("san");
  if (code) window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
}

// Phân trang như Hội viên / Nhân viên, phía client vì API trả đủ danh sách: ?trang=, ?so-dong= trên URL (giữ ?san= khi đổi trang)
const PARAM = { page: "trang", size: "so-dong" } as const;
const PAGE_SIZES = [20, 50, 100] as const;

const noop = () => () => {};
/** true chỉ ở trình duyệt (server và lúc hydrate là false). */
const useIsClient = () => useSyncExternalStore(noop, () => true, () => false);

/** Sân ngừng hoạt động: nội dung mờ (trạng thái và ⋯ giữ rõ), rê chuột thì rõ lại để đọc. */
const dim = (r: Resource) => (r.is_active ? undefined : "opacity-50 transition-opacity group-hover/row:opacity-90 motion-reduce:transition-none");
const NAME = "rounded-sm text-left font-semibold focus-ring hover:text-primary hover:underline";

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
  const { searchParams, hrefWith, set } = useUrlFilters(PARAM, "page");
  const openCode = searchParams.get("san");
  const pageSize = PAGE_SIZES.find((n) => String(n) === searchParams.get(PARAM.size)) ?? PAGE_SIZES[0];
  // Kẹp trang: đổi số dòng hoặc xóa sân xong trang vẫn hợp lệ
  const pageCount = Math.max(1, Math.ceil(resources.length / pageSize));
  const page = Math.min(pageCount, Math.max(1, Math.trunc(Number(searchParams.get(PARAM.page))) || 1));
  const pageRows = resources.slice((page - 1) * pageSize, page * pageSize);
  // Ngăn đọc bề rộng đã lưu (localStorage) khi render ⇒ chỉ dựng ở trình duyệt, tránh lệch HTML khi mở thẳng link ?san=
  const isClient = useIsClient();
  const [form, setForm] = useState<Form | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  // ⋯ "Sửa sân" ⇒ ngăn mở thẳng chế độ sửa
  const [editCode, setEditCode] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Resource | null>(null);
  const typeName = (r: Resource) => types.find((x) => x.code === r.resource_type_code)?.name ?? r.resource_type_name;
  const active = resources.filter((r) => r.is_active).length;
  const openCourt = resources.find((r) => r.code === openCode);

  useEffect(() => {
    if (!fresh) return;
    const timer = setTimeout(() => setFresh(null), 3000);
    return () => clearTimeout(timer);
  }, [fresh]);

  const reload = () => {
    setForm(null);
    router.refresh();
    toast(t.reloaded, undefined, "info");
  };
  const add = () => setForm(emptyForm(types));
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
  const actionProps = { primaryAction: { label: t.add, shortLabel: t.addShort, icon: <PlusIcon />, onClick: add } };
  const menu = (r: Resource) => {
    const items: MenuAction[] = [
      { label: t.detail, icon: <EyeIcon />, onClick: () => open(r.code) },
      { label: t.edit, icon: <PencilIcon />, onClick: () => open(r.code, true) },
    ];
    if (canDelete) items.push({ label: t.delete, icon: <TrashIcon />, danger: true, onClick: () => setDeleting(r) });
    return <ActionMenu label={t.actions.replace("{name}", r.name)} items={items} />;
  };
  const hours = (r: Resource) => (r.schedule ? `${t5(r.schedule.open_time)} – ${t5(r.schedule.close_time)}` : "—");
  const price = (r: Resource) => (weekdayPrice[r.resource_type_code] != null ? formatVnd(weekdayPrice[r.resource_type_code]) : "—");
  const nameButton = (r: Resource) => (
    <button type="button" className={NAME} onClick={() => open(r.code)}>
      {r.name}
    </button>
  );

  const columns: Column<Resource>[] = [
    { key: "code", header: t.colCode, className: "w-20 font-mono text-xs", cell: (r) => <span className={dim(r)}>{r.code}</span>, cardCell: () => null },
    {
      key: "name",
      header: t.colName,
      card: "body",
      // Khung < xl: loại sân thành dòng phụ dưới tên (cột Loại sân ẩn)
      cell: (r) => (
        <span className={cn("flex flex-col items-start", dim(r))}>
          {nameButton(r)}
          <span className="text-xs text-muted xl:hidden">{typeName(r)}</span>
        </span>
      ),
      // Thẻ điện thoại 3 dòng, lưới 2 cột cố định (trạng thái và ⋯ thẳng hàng mọi thẻ):
      //   Tên sân                       ● Hoạt động
      //   S01 · Sân thường                        ⋯
      //   05:00 – 22:00 · 150.000 ₫/giờ
      cardCell: (r) => (
        <span className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3">
          <span className={cn("min-w-0 text-sm [&>button]:block [&>button]:max-w-full [&>button]:truncate", dim(r))}>{nameButton(r)}</span>
          <span className={cn("inline-flex items-center justify-end gap-1 text-xs font-medium whitespace-nowrap", r.is_active ? "text-primary" : "text-muted")}>
            <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-current" />
            {r.is_active ? t.active : t.inactiveShort}
          </span>
          <span className={cn("col-start-1 text-xs text-muted", dim(r))}>{`${r.code} · ${typeName(r)}`}</span>
          <span className="col-start-2 row-span-2 row-start-2 flex items-center justify-end">{menu(r)}</span>
          <span className={cn("col-start-1 text-xs tabular-nums", dim(r))}>{`${hours(r)} · ${t.perHour.replace("{price}", price(r))}`}</span>
        </span>
      ),
    },
    { key: "type", header: t.colType, hideBelow: "xl", cell: (r) => <span className={dim(r)}>{typeName(r)}</span>, cardCell: () => null },
    {
      key: "hours",
      header: t.colHours,
      className: "whitespace-nowrap tabular-nums",
      cell: (r) => (
        <span className={cn("flex flex-col", dim(r))}>
          {hours(r)}
          {/* Giờ mở cửa đã hẹn đổi: dòng phụ */}
          {r.pending_schedule ? (
            <span className="text-xs text-muted">
              {t.pendingSchedule
                .replace("{date}", formatDayMonth(r.pending_schedule.effective_from))
                .replace("{open}", t5(r.pending_schedule.open_time))
                .replace("{close}", t5(r.pending_schedule.close_time))}
            </span>
          ) : null}
        </span>
      ),
      cardCell: () => null,
    },
    { key: "price", header: t.colPrice, align: "right", className: "whitespace-nowrap tabular-nums", cell: (r) => <span className={dim(r)}>{price(r)}</span>, cardCell: () => null },
    {
      key: "status",
      header: t.colStatus,
      className: "w-40",
      cell: (r) => <Badge variant={r.is_active ? "success" : "neutral"}>{r.is_active ? t.active : t.inactive}</Badge>,
      cardCell: () => null,
    },
    { key: "actions", header: "", align: "right", className: "w-14", cell: menu, cardCell: () => null },
  ];

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title={t.title} description={t.summary.replace("{total}", String(resources.length)).replace("{active}", String(active))} {...actionProps} actionsOnMobileOnly />
      {/* Từ sm: "Thêm sân" nằm cuối hàng tab (như Hội viên); điện thoại ở đầu trang */}
      <SanTabs
        active="list"
        t={t}
        end={
          <div className="hidden sm:block">
            <PageActions {...actionProps} />
          </div>
        }
      />

      <Card bareOnMobile className="flex flex-col gap-3 sm:gap-4 sm:p-5">
        <DataTable
          caption={t.caption}
          columns={columns}
          rows={pageRows}
          rowKey={(r) => r.code}
          rowClassName={(r) => cn("group/row", !r.is_active && "bg-background", (fresh === r.code || openCode === r.code) && "bg-primary-softer") || undefined}
          onRowClick={(r) => open(r.code)}
          stickyHeader
          empty={
            <EmptyState
              icon={<InboxIcon />}
              title={t.empty}
              description={t.emptyHint}
              action={
                <Button type="button" onClick={add}>
                  <PlusIcon />
                  {t.add}
                </Button>
              }
            />
          }
        />
        <ListFooter
          page={page}
          pageSize={pageSize}
          pageSizes={PAGE_SIZES}
          total={resources.length}
          shown={pageRows.length}
          hrefFor={(n) => hrefWith({ page: n === 1 ? null : String(n) })}
          // Số dòng mặc định không ghi lên URL; đổi ⇒ về trang 1, giữ ?san=
          onPageSize={(n) => set({ size: n === PAGE_SIZES[0] ? null : String(n) })}
          t={t}
        />
      </Card>

      {form ? (
        <CourtFormDialog
          initial={form}
          resources={resources}
          types={types}
          t={t}
          onClose={() => setForm(null)}
          onSaved={(code) => (setFresh(code), setForm(null), router.refresh())}
          onReload={reload}
        />
      ) : null}
      {isClient && openCode ? (
        <CourtDrawer
          key={openCode}
          code={openCode}
          startEditing={editCode === openCode}
          // Sân không còn trên danh sách (vừa xóa ở nơi khác) ⇒ không hiện nút xóa
          onDelete={canDelete && openCourt ? () => setDeleting(openCourt) : undefined}
          t={t}
          resources={resources}
          types={types}
          onClose={() => (setEditCode(null), setCourtParam(null))}
          onSaved={(code) => (setFresh(code), router.refresh())}
        />
      ) : null}
      {deleting ? <DeleteCourtDialog court={deleting} onClose={() => setDeleting(null)} onDeleted={() => onDeleted(deleting)} t={t} /> : null}
    </div>
  );
}
