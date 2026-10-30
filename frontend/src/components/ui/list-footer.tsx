import { Pagination } from "./pagination";
import { Dropdown } from "./dropdown";

type ListFooterTexts = {
  /** "Hiển thị {from}–{to} / {total} …" */
  showing: string;
  pageSizeLabel: string;
  /** "Hiển thị {n} dòng" */
  pageSizeOption: string;
  pagination: React.ComponentProps<typeof Pagination>["t"];
};

type ListFooterProps = {
  page: number;
  pageSize: number;
  pageSizes: readonly number[];
  total: number;
  /** Số dòng đang hiện ở trang này. */
  shown: number;
  hrefFor: (page: number) => string;
  onPageSize: (size: number) => void;
  t: ListFooterTexts;
};

/** Chân danh sách: "Hiển thị a–b / n", chọn số dòng, phân trang. Máy tính một hàng; điện thoại phân trang lên trên, căn giữa. */
export function ListFooter({ page, pageSize, pageSizes, total, shown, hrefFor, onPageSize, t }: ListFooterProps) {
  if (shown === 0) return null;
  const from = (page - 1) * pageSize;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex flex-col-reverse gap-3 md:flex-row md:items-center md:justify-between">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 md:justify-start">
        <p className="text-xs text-muted tabular-nums sm:text-ui">
          {t.showing
            .replace("{from}", String(from + 1))
            .replace("{to}", String(from + shown))
            .replace("{total}", String(total))}
        </p>
        <Dropdown
          aria-label={t.pageSizeLabel}
          value={String(pageSize)}
          onChange={(v) => onPageSize(Number(v))}
          options={pageSizes.map((n) => ({ value: String(n), label: t.pageSizeOption.replace("{n}", String(n)) }))}
          className="w-36 sm:w-44"
        />
      </div>
      <div className="flex justify-center">
        <Pagination page={page} pageCount={pageCount} hrefFor={hrefFor} t={t.pagination} />
      </div>
    </div>
  );
}
