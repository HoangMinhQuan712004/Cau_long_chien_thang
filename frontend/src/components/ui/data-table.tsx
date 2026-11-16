import { cn } from "@/lib/cn";
import { DataCards } from "./data-table-cards";
import { DataTableDesktop, LAYOUT } from "./data-table-desktop";

export type SortDir = "asc" | "desc";

/** Vị trí của cột trong thẻ điện thoại; không cột nào khai báo ⇒ thẻ kiểu cũ "nhãn – giá trị" từng dòng. */
export type CardSlot = "title" | "subtitle" | "badge" | "meta" | "body" | "actions";

export type Column<Row> = {
  key: string;
  header: string;
  cell: (row: Row) => React.ReactNode;
  align?: "left" | "center" | "right";
  /** Độ rộng/kiểu riêng của cột trên bảng máy tính (vd `w-20`). */
  className?: string;
  sortable?: boolean;
  /** Ẩn cột trên bảng khi khung hẹp hơn mức này (cột ít quan trọng); thẻ điện thoại vẫn hiện theo `card`. */
  hideBelow?: "lg" | "xl";
  card?: CardSlot;
  /** Nội dung riêng trong thẻ (vd nhãn gọn hơn); trả null ⇒ bỏ qua ô đó trong thẻ. */
  cardCell?: (row: Row) => React.ReactNode;
};

export type DataTableProps<Row> = {
  /** Tên bảng cho trình đọc màn hình. */
  caption: string;
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  /** Lớp thêm cho dòng (vd mờ dòng Ngừng). */
  rowClassName?: (row: Row) => string | undefined;
  /**
   * Bấm vào dòng (chuột / chạm) ⇒ vd mở chi tiết. Bấm trúng nút / link trong dòng thì bỏ qua.
   * Bàn phím vẫn cần một nút trong dòng làm việc này (vd tên là button), vì dòng không nhận focus.
   */
  onRowClick?: (row: Row) => void;
  sort?: { key: string; dir: SortDir };
  onSort?: (key: string) => void;
  /** Hiện khi không có dòng nào (gợi ý + hành động). */
  empty?: React.ReactNode;
  /** `viewport`: bảng/thẻ theo khổ màn hình; `container`: theo bề rộng khung chứa (vd trong ngăn chi tiết). */
  layout?: "viewport" | "container";
  /** Dòng tiêu đề dính khi cuộn trang (bảng không cuộn ngang: cột phụ phải ẩn bớt bằng `hideBelow`). */
  stickyHeader?: boolean;
};

/** Bảng dữ liệu quản trị (Figma "Bảng hội viên"): khung rộng là bảng có cột, khung hẹp là thẻ xếp dọc. */
export function DataTable<Row>(props: DataTableProps<Row>) {
  const { rows, empty, layout = "viewport" } = props;
  if (rows.length === 0 && empty) {
    return <div className="rounded-xl border bg-surface px-4 py-10 text-center text-sm text-muted">{empty}</div>;
  }

  return (
    <div className={cn(LAYOUT[layout].root)}>
      <DataTableDesktop {...props} layout={layout} />
      <DataCards {...props} layout={layout} />
    </div>
  );
}
