import { cn } from "@/lib/cn";
import { staggerStyle } from "@/lib/motion";
import type { CardSlot, Column, DataTableProps } from "./data-table";
import { LAYOUT, rowClickHandler } from "./data-table-desktop";

type Cell = { key: string; header: string; node: React.ReactNode };

// Ô của dòng theo vị trí trong thẻ; ô rỗng (cardCell trả null) bị bỏ
function cellsOf<Row>(columns: readonly Column<Row>[], row: Row, slot: CardSlot): Cell[] {
  return columns
    .filter((c) => (c.card ?? "meta") === slot)
    .map((c) => ({ key: c.key, header: c.header, node: (c.cardCell ?? c.cell)(row) }))
    .filter((x) => x.node !== null && x.node !== undefined && x.node !== false && x.node !== "");
}

/** Phần thẻ xếp dọc của DataTable (khung hẹp). */
export function DataCards<Row>({ caption, columns, rows, rowKey, rowClassName, onRowClick, layout = "viewport" }: DataTableProps<Row>) {
  const isSlotted = columns.some((c) => c.card);
  return (
    // Dạng bảng gọn: một khung, các dòng ngăn bằng vạch (không tách từng thẻ rời)
    <ul aria-label={caption} className={cn("divide-y overflow-hidden rounded-xl border bg-surface", LAYOUT[layout].cards)}>
      {rows.map((row, i) => (
        <li
          key={rowKey(row)}
          style={staggerStyle(i)}
          onClick={rowClickHandler(row, onRowClick)}
          className={cn(`
            animate-slide-up px-3 py-2.5 transition-colors stagger
            hover:bg-primary-softer
            sm:p-4
          `, onRowClick && "cursor-pointer", rowClassName?.(row))}
        >
          {isSlotted ? <SlottedCard columns={columns} row={row} /> : <PlainCard columns={columns} row={row} />}
        </li>
      ))}
    </ul>
  );
}

// Nối các ô bằng " · " trên một dòng
function joined(cells: Cell[]) {
  return cells.map((x, i) => (
    <span key={x.key}>
      {i > 0 ? " · " : null}
      {x.node}
    </span>
  ));
}

// Thẻ gọn: dòng 1 tên + nhãn (nút ở góc phải), dòng 2 phụ, dòng 3 các mục "Nhãn: giá trị", rồi khối nội dung dài
function SlottedCard<Row>({ columns, row }: { columns: readonly Column<Row>[]; row: Row }) {
  const [titles, subtitles, badges, metas, bodies, actions] = (["title", "subtitle", "badge", "meta", "body", "actions"] as const).map((slot) =>
    cellsOf(columns, row, slot),
  );
  return (
    <div className="flex items-start justify-between gap-3">
      {/* flex-1: cột nội dung rộng hết phần còn lại (ô "body" tự chia cột canh phải được) */}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {titles.map((x) => (
            <div key={x.key} className="text-sm font-semibold wrap-break-word sm:text-base">
              {x.node}
            </div>
          ))}
          {badges.map((x) => (
            <span key={x.key} className="contents">
              {x.node}
            </span>
          ))}
        </div>
        {subtitles.length > 0 ? <p className="text-xs text-muted tabular-nums sm:text-ui">{joined(subtitles)}</p> : null}
        {/* Mỗi mục "Nhãn: giá trị" là một khối không ngắt; hết chỗ thì cả mục xuống dòng */}
        {metas.length > 0 ? (
          <dl className={cn(`
            flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums
            sm:gap-y-1 sm:text-ui
          `)}>
            {metas.map((x) => (
              <div key={x.key} className="flex gap-1 whitespace-nowrap">
                <dt className="text-muted">{x.header}:</dt>
                <dd className="font-medium">{x.node}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {/* Nội dung dài (vd danh sách thay đổi): khối riêng, không nhãn, xuống dòng bình thường */}
        {bodies.map((x) => (
          <div key={x.key} className="text-xs sm:text-ui">
            {x.node}
          </div>
        ))}
      </div>
      {actions.length > 0 ? (
        <div className="-mt-1 -mr-1 flex shrink-0 items-center gap-1">
          {actions.map((x) => (
            <span key={x.key} className="contents">
              {x.node}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// Thẻ kiểu cũ: mỗi cột một dòng "nhãn – giá trị" (bảng chưa khai báo `card`)
function PlainCard<Row>({ columns, row }: { columns: readonly Column<Row>[]; row: Row }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
      {columns.map((c) => (
        <div key={c.key} className="contents">
          <dt className="text-muted">{c.header}</dt>
          <dd className="min-w-0 text-right">{c.cell(row)}</dd>
        </div>
      ))}
    </dl>
  );
}
