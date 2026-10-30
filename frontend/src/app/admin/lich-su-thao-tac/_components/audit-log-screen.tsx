"use client";

import { useTransition } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ResetIcon, SearchXIcon } from "@/components/ui/icons";
import { ListFooter } from "@/components/ui/list-footer";
import { PageHeader } from "@/components/ui/page-header";
import { useUrlFilters } from "@/hooks/use-url-filters";
import type { Dictionary } from "@/i18n/dictionaries";
import type { AuditCatalog, AuditLogPage } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import { AuditFilters } from "./audit-filters";
import { type AuditFilter, type AuditParams, type AuditPatch, CLEAR_FILTERS, DEFAULT_SIZE, NEXT_SORT, PAGE_SIZES, PARAM } from "./audit-params";
import { AuditTable } from "./audit-table";

type Props = {
  catalog: AuditCatalog;
  /** null = tải danh sách lỗi (E-003): giữ bộ lọc, không có bảng / phân trang. */
  data: AuditLogPage | null;
  /** Bộ lọc, sắp xếp, trang đang áp (đọc từ URL). */
  applied: AuditParams;
  t: Dictionary["auditLog"];
};

/** Màn Lịch sử thao tác (SRS FR-001, FR-002): lọc như màn Hội viên (đổi là áp, về trang 1), 20 / 50 / 100 dòng (mặc định 50), chỉ xem. */
export function AuditLogScreen({ catalog, data, applied, t }: Props) {
  const url = useUrlFilters(PARAM, "page");
  const [isPending, startTransition] = useTransition();
  // Đổi lọc trong transition ⇒ mờ danh sách cũ trong lúc tải
  const set = (patch: AuditPatch) => startTransition(() => url.set(patch));
  // URL chưa có ngày ⇒ hiện khoảng API đã dùng (7 ngày gần nhất)
  const filter: AuditFilter = {
    actor: applied.actor,
    action: applied.action,
    from: applied.from || data?.date_from || catalog.max_date,
    to: applied.to || data?.date_to || catalog.max_date,
  };
  const hasDateRange = applied.from !== "" || applied.to !== "";
  const isFiltered = hasDateRange || applied.actor !== "all" || applied.action !== "all";

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title={t.title} description={t.description} descriptionBelow />

      <Card bareOnMobile className="flex flex-col gap-3 sm:gap-4 sm:p-5">
        <AuditFilters
          catalog={catalog}
          filter={filter}
          hasDateRange={hasDateRange}
          onChange={set}
          t={t}
        />

        {/* Đang tải lại: mờ danh sách cũ, không nhảy bố cục */}
        <div aria-busy={isPending} className={cn("flex flex-col gap-3 transition-opacity sm:gap-4", isPending && `
          opacity-60
        `)}>
          {data ? (
            <>
              <AuditTable
                rows={data.items}
                sort={applied.sort}
                // Đổi chiều ⇒ về trang 1 (patch không có trang)
                onSort={() => set({ sort: NEXT_SORT[applied.sort] })}
                empty={
                  <EmptyState
                    icon={<SearchXIcon size={24} />}
                    title={t.noMatch.title}
                    description={t.noMatch.text}
                    action={isFiltered ? (
                      <Button variant="secondary" onClick={() => set(CLEAR_FILTERS)}>
                        <ResetIcon />
                        {t.filters.filterBar.clear}
                      </Button>
                    ) : null}
                  />
                }
                t={t}
              />
              <ListFooter
                page={data.page}
                pageSize={data.page_size}
                pageSizes={PAGE_SIZES}
                // Đổi số dòng ⇒ về trang 1; mặc định 50 không ghi lên URL
                onPageSize={(n) => set({ size: n === DEFAULT_SIZE ? null : String(n) })}
                total={data.total}
                shown={data.items.length}
                // Chuyển trang giữ bộ lọc đang áp (BR-015)
                hrefFor={(n) => url.hrefWith({ page: n === 1 ? null : String(n) })}
                t={t}
              />
            </>
          ) : (
            <Alert variant="error">{t.loadError}</Alert>
          )}
        </div>
      </Card>
    </div>
  );
}
