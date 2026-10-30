import { cn } from "@/lib/cn";
import { staggerStyle } from "@/lib/motion";
import type { Column, DataTableProps, SortDir } from "./data-table";
import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon } from "./icons";

// Class viết đầy đủ để Tailwind quét được: chọn bảng hay thẻ theo màn hình hoặc theo khung `@container/data-table`
export const LAYOUT = {
  viewport: { root: "", table: "hidden md:block", cards: "md:hidden" },
  container: { root: "@container/data-table", table: "hidden @xl/data-table:block", cards: "@xl/data-table:hidden" },
} as const;

/** Gắn vào onClick của dòng: bỏ qua khi bấm trúng phần tử tương tác bên trong. */
export function rowClickHandler<Row>(row: Row, onRowClick?: (row: Row) => void) {
  if (!onRowClick) return undefined;
  return (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button, a, input, select, textarea, [role=combobox]")) return;
    onRowClick(row);
  };
}

const ALIGN = { left: "text-left", center: "text-center", right: "text-right" } as const;
// Ẩn cột theo khổ; trong khung container dùng mốc tương ứng của khung (56rem ≈ lg trừ sidebar, 64rem ≈ xl)
const HIDE = {
  viewport: { lg: "hidden lg:table-cell", xl: "hidden xl:table-cell" },
  container: { lg: "hidden @4xl/data-table:table-cell", xl: "hidden @5xl/data-table:table-cell" },
} as const;
const ARIA_SORT = { asc: "ascending", desc: "descending" } as const;
// Dính dưới header điện thoại của khu quản trị (biến đặt ở AdminShell); trong ngăn chi tiết dính sát mép trên
const STICKY = {
  viewport: "sticky top-(--sticky-top,0px) z-1",
  container: "sticky top-0 z-1",
} as const;

// Tách riêng (không đặt trong cn): lint Tailwind không đọc nhầm "left" là class
function alignOf<Row>(c: Column<Row>): string {
  return ALIGN[c.align ?? "left"];
}

function cellClass<Row>(c: Column<Row>, layout: "viewport" | "container"): string {
  return cn(alignOf(c), c.hideBelow && HIDE[layout][c.hideBelow], c.className);
}

// Mũi tên cột sắp xếp: đang sắp thì đậm màu chữ, chưa sắp thì mờ
function SortIcon({ dir }: { dir?: SortDir }) {
  const Icon = dir === "asc" ? ArrowUpIcon : dir === "desc" ? ArrowDownIcon : ArrowUpDownIcon;
  return <Icon size={14} className={dir ? "text-foreground" : "opacity-60"} />;
}

/** Phần bảng có cột của DataTable (khung rộng). */
export function DataTableDesktop<Row>({
  caption,
  columns,
  rows,
  rowKey,
  rowClassName,
  onRowClick,
  sort,
  onSort,
  layout = "viewport",
  stickyHeader = false,
}: DataTableProps<Row>) {
  return (
    // Dính tiêu đề cần khung không cuộn ngang (overflow-x-auto tạo khung cuộn riêng làm sticky mất tác dụng)
    <div className={cn("rounded-xl border", LAYOUT[layout].table, stickyHeader ? "overflow-x-clip" : `
      overflow-x-auto
    `)}>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-ui text-muted">
          <tr>
            {columns.map((c) => {
              const dir = sort?.key === c.key ? sort.dir : undefined;
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={c.sortable ? (dir ? ARIA_SORT[dir] : "none") : undefined}
                  className={cn(
                    "bg-background p-3 font-medium whitespace-nowrap 2xl:px-4",
                    stickyHeader && STICKY[layout],
                    cellClass(c, layout),
                  )}
                >
                  {c.sortable && onSort ? (
                    <button
                      type="button"
                      onClick={() => onSort(c.key)}
                      className={cn(`
                        -mx-1 inline-flex items-center gap-1 rounded-sm px-1 font-medium focus-ring
                        hover:text-foreground
                      `)}
                    >
                      {c.header}
                      <SortIcon dir={dir} />
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey(row)}
              style={staggerStyle(i)}
              onClick={rowClickHandler(row, onRowClick)}
              className={cn(`
                animate-fade-in border-t transition-colors stagger
                hover:bg-primary-softer
              `, onRowClick && "cursor-pointer", rowClassName?.(row))}
            >
              {columns.map((c) => (
                <td key={c.key} className={cn("px-3 py-3.5 2xl:px-4", cellClass(c, layout))}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
