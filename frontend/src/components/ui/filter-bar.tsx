"use client";

import { useSearchDraft } from "@/hooks/use-search-draft";
import { cn } from "@/lib/cn";
import { Button } from "./button";
import { Dropdown, type SelectOption } from "./dropdown";
import { ResetIcon, SearchIcon } from "./icons";
import { Input } from "./input";

export type FilterDef = {
  key: string;
  /** Tên bộ lọc ("Hạng"), luôn hiện làm tiền tố trên ô: "Hạng: Khá". */
  label: string;
  /** Các lựa chọn, không gồm "Tất cả" (thanh lọc tự thêm). */
  options: readonly SelectOption[];
  value: string;
  onChange: (value: string) => void;
  /** Giá trị "Tất cả" (không lọc); mặc định "all". */
  allValue?: string;
  /** "tree": nhóm thu gọn / mở như cây thư mục (xem Dropdown). */
  variant?: "default" | "tree";
  /** Bề rộng ô (vd `lg:w-52`): từ lg nên cố định để đổi lọc không làm hàng nhảy. */
  className?: string;
};

type FilterBarTexts = {
  all: string;
  clear: string;
  /** "{n} bộ lọc đang bật" (đọc cho trình đọc màn hình cạnh số đếm). */
  activeCount: string;
  /** "Bỏ lọc {label}" */
  remove: string;
};

type SearchDef = { value: string; onChange: (value: string) => void; label: string; placeholder: string; maxLength?: number };

// Có ô tìm ⇒ bắt buộc có tên nút ✕ của ô (`t.clearSearch`); không có ô tìm thì không cần
type SearchProps =
  | {
      /** `value` là giá trị đang áp (trên URL); ô tự giữ chữ đang gõ và gọi `onChange` sau khi ngừng gõ. */
      search: SearchDef;
      t: FilterBarTexts & { clearSearch: string };
    }
  | { search?: undefined; t: FilterBarTexts };

type FilterBarProps = SearchProps & {
  filters: readonly FilterDef[];
  /** Bỏ mọi bộ lọc trong `filters` (nút "Xóa lọc"); ô tìm thanh lọc tự xóa. */
  onClear: () => void;
  /** Số bộ lọc nằm ngoài thanh (vd khoảng ngày) đang khác mặc định, cộng vào số trên nút Xóa lọc. */
  extraCount?: number;
};

/** Thanh lọc: ô tìm, rồi các ô chọn "Hạng: Khá" (đang lọc tô màu + ✕) và nút Xóa lọc có số; từ xl tất cả một hàng. */
export function FilterBar({ search, filters, onClear, extraCount = 0, t }: FilterBarProps) {
  const [draft, setDraft] = useSearchDraft(search?.value ?? "", (q) => search?.onChange(q));
  const allOf = (f: FilterDef) => f.allValue ?? "all";
  const isOn = (f: FilterDef) => f.value !== allOf(f);
  const optionsOf = (f: FilterDef) => [{ value: allOf(f), label: t.all }, ...f.options];
  const labelOf = (f: FilterDef) => optionsOf(f).find((o) => o.value === f.value)?.label ?? f.value;
  // Ô tìm có chữ tính là 1 lọc
  const count = filters.filter(isOn).length + (search && (search.value !== "" || draft !== "") ? 1 : 0) + extraCount;
  const clearAll = () => {
    setDraft("");
    onClear();
  };

  return (
    <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
      {search && "clearSearch" in t ? <Input
        compact
        type="search"
        aria-label={search.label}
        placeholder={search.placeholder}
        value={draft}
        maxLength={search.maxLength}
        onChange={(e) => setDraft(e.target.value)}
        startSlot={<SearchIcon size={18} />}
        // ✕ xóa chữ ngay, không chờ debounce
        onClear={() => {
          setDraft("");
          search.onChange("");
        }}
        clearLabel={t.clearSearch}
        className="xl:min-w-40 xl:flex-1"
      /> : null}
      {/*
        Điện thoại: một hàng vuốt ngang (pan-x lẫn pan-y để vẫn cuộn trang dọc được), mép phải mờ dần báo còn nội dung,
        -my-1 py-1 chừa chỗ cho vòng focus trên/dưới (không lùi trái ⇒ mép ô thẳng với ô tìm). Từ sm: xếp hàng tự xuống dòng, bề rộng cố định.
      */}
      <div className={cn(`
        -my-1 flex touch-pan-x touch-pan-y snap-x snap-proximity scrollbar-none items-center gap-2
        overflow-x-auto mask-r-from-85% py-1
        sm:my-0 sm:snap-none sm:flex-wrap sm:overflow-visible sm:mask-none sm:py-0
      `)}>
        {filters.map((f) => (
          <Dropdown
            key={f.key}
            aria-label={f.label}
            value={f.value}
            onChange={f.onChange}
            options={optionsOf(f)}
            variant={f.variant}
            renderValue={() => (
              <span className="flex min-w-0 gap-1">
                <span className={cn("shrink-0 font-normal", isOn(f) ? "text-primary/70" : `
                  text-muted
                `)}>{f.label}:</span>
                <span className="min-w-0 truncate font-semibold">{labelOf(f)}</span>
              </span>
            )}
            title={`${f.label}: ${labelOf(f)}`}
            active={isOn(f)}
            onClear={() => f.onChange(allOf(f))}
            clearLabel={t.remove.replace("{label}", f.label)}
            className={cn("max-w-64 shrink-0 snap-start sm:max-w-none", f.className ?? "sm:w-52")}
          />
        ))}
        {/* Chỉ hiện khi có lọc (nằm cuối nên không đẩy các ô); từ xl chung hàng với ô tìm ⇒ giữ chỗ bằng invisible */}
        <div className={cn(count > 0 ? "shrink-0 animate-fade-in" : `hidden xl:invisible xl:block`)}>
        <Button
          variant="ghost"
          onClick={clearAll}
          title={t.clear}
        >
          <ResetIcon />
          {/* Điện thoại có chỗ ⇒ hiện chữ; sm–2xl chỉ icon cho hàng gọn */}
          <span className="sm:sr-only 2xl:not-sr-only">{t.clear}</span>
          <span aria-hidden className={cn(`
            grid h-5 min-w-5 place-items-center rounded-full bg-primary-soft px-1 text-label
            font-bold text-primary tabular-nums
          `)}>
            {Math.max(count, 1)}
          </span>
          <span className="sr-only">{t.activeCount.replace("{n}", String(count))}</span>
        </Button>
        </div>
      </div>
    </div>
  );
}
