"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { InboxIcon, PlusIcon, RacketIcon, ResetIcon, SearchXIcon, UserIcon } from "@/components/ui/icons";
import { PageActions, PageHeader } from "@/components/ui/page-header";
import { ListFooter } from "@/components/ui/list-footer";
import { NavTabs } from "@/components/ui/nav-tabs";
import { useUrlFilters } from "@/hooks/use-url-filters";
import type { Dictionary } from "@/i18n/dictionaries";
import type { MemberList as MemberListData } from "@/lib/api/server";
import { MemberDrawer } from "./member-drawer";
import { RacketCatalog } from "./racket-catalog";
import { MemberFilters } from "./member-filters";
import { type FormMode, MemberForm } from "./member-form";
import { CLEAR_FILTERS, isFiltered, MEMBER_KINDS, NEXT_SORT, PAGE_SIZES, PARAM, readMemberParams } from "./member-params";
import { MemberTable } from "./member-table";

type Props = { data: MemberListData; t: Dictionary["members"] };

/** Màn Hội viên (Figma P5): danh sách lọc/phân trang theo URL, mở popup thêm/sửa/chuyển và drawer chi tiết. */
export function MemberList({ data, t }: Props) {
  const router = useRouter();
  const url = useUrlFilters(PARAM, "page");
  const { filter, bookingsSort } = readMemberParams(url.searchParams);
  const [form, setForm] = useState<FormMode | null>(null);
  const [drawerRef, setDrawerRef] = useState<string | null>(null);
  const [isCatalogOpen, setIsCatalogOpen] = useState(false);
  const { counts, total, page, items, can } = data;

  const actionProps = {
    primaryAction: { label: t.addMember, shortLabel: t.addShort, icon: <PlusIcon />, onClick: () => setForm({ kind: "add" }) },
    actions: [
      ...(can.manage_rackets ? [{ label: t.rackets.open, icon: <RacketIcon />, plain: true, onClick: () => setIsCatalogOpen(true) }] : []),
      { label: t.addTemp, icon: <UserIcon />, onClick: () => setForm({ kind: "temp" }) },
    ],
    moreLabel: t.moreActions,
  };

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title={t.title}
        description={t.summary
          .replace("{total}", String(counts.all))
          .replace("{members}", String(counts.member))
          .replace("{temps}", String(counts.temp))}
        // Từ sm: nút nằm cùng hàng tab, canh phải; điện thoại giữ ở đầu trang
        {...actionProps}
        actionsOnMobileOnly
      />

      {/* Loại hồ sơ là tab (giống màn Sân); đổi tab tự về trang 1, giữ các lọc khác */}
      <NavTabs
        label={t.kindLabel}
        items={MEMBER_KINDS.map((k) => ({ id: k, href: url.hrefWith({ kind: k }), label: t.kinds[k], count: counts[k] }))}
        active={filter.kind}
        scroll={false}
        end={
          // Bọc div để ẩn trên điện thoại (PageActions vốn có class flex)
          <div className="hidden sm:block">
            <PageActions {...actionProps} />
          </div>
        }
      />

      {/* Điện thoại: không khung ngoài (thẻ hội viên dùng hết bề ngang) */}
      <Card bareOnMobile className="flex flex-col gap-3 sm:gap-4 sm:p-5">
      <MemberFilters filter={filter} onChange={url.set} canSeeHiddenRackets={can.manage_rackets} t={t} />

      <MemberTable
        rows={items}
        sortDir={bookingsSort}
        // Đổi chiều ⇒ về trang 1
        onSort={() => url.set({ sort: NEXT_SORT[bookingsSort ?? "none"] })}
        onAction={(action, row) =>
          action === "detail" ? setDrawerRef(row.ref) : setForm({ kind: "edit", ref: row.ref })
        }
        empty={
          <MemberEmpty
            total={total}
            isFiltered={isFiltered(filter)}
            firstPageHref={url.hrefWith({ page: null })}
            onClearFilters={() => url.set(CLEAR_FILTERS)}
            onAdd={() => setForm({ kind: "add" })}
            t={t}
          />
        }
        t={t}
      />

      <ListFooter
        page={page}
        // Theo `size` API trả về (đúng với số dòng thật của trang này)
        pageSize={data.size}
        pageSizes={PAGE_SIZES}
        total={total}
        shown={items.length}
        hrefFor={(n) => url.hrefWith({ page: n === 1 ? null : String(n) })}
        // Số dòng mặc định không ghi lên URL; đổi ⇒ về trang 1, giữ bộ lọc
        onPageSize={(n) => url.set({ size: n === PAGE_SIZES[0] ? null : String(n) })}
        t={t}
      />
      </Card>

      {drawerRef ? (
        <MemberDrawer
          memberRef={drawerRef}
          onClose={() => setDrawerRef(null)}
          onEdit={(detail) => {
            setDrawerRef(null);
            setForm({ kind: "edit", ref: detail.ref, detail });
          }}
          t={t}
        />
      ) : null}
      {isCatalogOpen ? <RacketCatalog onClose={() => setIsCatalogOpen(false)} t={t} /> : null}
      {form ? (
        <MemberForm
          key={form.kind === "edit" ? `edit-${form.ref}` : form.kind}
          mode={form}
          canEditStatus={can.edit_status}
          onClose={() => setForm(null)}
          onSaved={() => router.refresh()}
          t={t}
        />
      ) : null}
    </div>
  );
}

type EmptyProps = {
  /** Tổng hồ sơ khớp bộ lọc (khác 0 mà trang rỗng ⇒ URL trỏ quá trang cuối). */
  total: number;
  isFiltered: boolean;
  firstPageHref: string;
  onClearFilters: () => void;
  onAdd: () => void;
  t: Dictionary["members"];
};

/** Câu rỗng của bảng hội viên: quá trang cuối / lọc không ra / chưa có hồ sơ nào. */
function MemberEmpty({ total, isFiltered, firstPageHref, onClearFilters, onAdd, t }: EmptyProps) {
  if (total > 0) {
    // Link cũ hoặc vừa bớt hồ sơ ⇒ trang hiện tại không còn dòng
    return (
      <EmptyState
        title={t.pageEmpty}
        action={
          <Link href={firstPageHref} className="font-semibold text-primary underline focus-ring">
            {t.firstPage}
          </Link>
        }
      />
    );
  }
  if (isFiltered) {
    return (
      <EmptyState
        icon={<SearchXIcon size={24} />}
        title={t.empty.title}
        description={t.empty.text}
        action={
          <Button variant="secondary" onClick={onClearFilters}>
            <ResetIcon />
            {t.empty.clear}
          </Button>
        }
      />
    );
  }
  return (
    <EmptyState
      icon={<InboxIcon size={24} />}
      title={t.emptyAll.title}
      description={t.emptyAll.text}
      action={
        <Button className="min-w-40" onClick={onAdd}>
          <PlusIcon />
          {t.addMember}
        </Button>
      }
    />
  );
}
