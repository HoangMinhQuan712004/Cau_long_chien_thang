"use client";

import { ChevronDownIcon } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { fill } from "@/lib/format";

// Quyền của Nhân viên dạng CÂY: dòng cha (nhóm) = nút thu gọn + checkbox cha (có trạng thái một phần) + tên + "x/y quyền";
// dòng con thụt vào, nối với cha bằng đường cây vẽ bằng pseudo-element (dọc 1px dưới checkbox cha, nhánh ngang 12px, con cuối └).
// Cả dòng con là <label> (bấm nhãn cũng tích), cao ≥ 44px; một nền trắng chung, các nhóm ngăn bằng đường kẻ mảnh.

type Group = components["schemas"]["PermGroupOut"];
type T = Dictionary["roles"];
type Props = {
  groups: Group[];
  draft: ReadonlySet<string>;
  collapsed: ReadonlySet<string>;
  onToggle: (perm: string) => void;
  onGroup: (perms: string[], on: boolean) => void;
  onCollapse: (group: string) => void;
  t: T;
};

const BOX = "size-5 shrink-0 cursor-pointer accent-primary";
// Tâm checkbox cha cách mép nội dung 3.625rem (nút 2.75rem + khe 0.25rem + nửa checkbox 0.625rem) ⇒ đường dọc đặt ở đó;
// tâm checkbox con cách đỉnh dòng 1.375rem (đệm 0.625rem + lệch 0.125rem + nửa checkbox) ⇒ nhánh ngang + điểm dừng của con cuối.
const TREE_LINE = cn(
  `
    before:absolute before:top-0 before:left-14.5 before:h-full before:w-px before:bg-border-strong
    last:before:h-5.5
  `,
  `after:absolute after:top-5.5 after:left-14.5 after:h-px after:w-3 after:bg-border-strong`,
);

export function RolesMatrix({ groups, draft, collapsed, onToggle, onGroup, onCollapse, t }: Props) {
  return (
    <div className="flex flex-col divide-y overflow-hidden rounded-card bg-surface shadow-card">
      {groups.map((g) => {
        const keys = g.perms.map((p) => p.key);
        const n = keys.filter((k) => draft.has(k)).length;
        const all = n === keys.length;
        const open = !collapsed.has(g.key);
        const listId = `perm-group-${g.key}`;
        return (
          <section key={g.key} aria-label={g.label}>
            {/* Dòng cha: nền nhạt để tách bậc */}
            <div className="flex min-h-13 items-center gap-1 bg-primary-softer/60 px-2 sm:px-4">
              <button
                type="button"
                aria-expanded={open}
                aria-controls={listId}
                aria-label={fill(open ? t.collapseGroup : t.expandGroup, { group: g.label })}
                onClick={() => onCollapse(g.key)}
                className={cn(`
                  grid size-11 shrink-0 place-items-center rounded-lg text-muted focus-ring
                  transition-colors
                  hover:bg-primary-soft hover:text-foreground
                `)}
              >
                <ChevronDownIcon size={18} className={cn(`
                  transition-transform
                  motion-reduce:transition-none
                `, !open && `-rotate-90`)} />
              </button>
              <label className="flex min-h-11 min-w-0 flex-1 cursor-pointer items-center gap-3">
                <input
                  type="checkbox"
                  className={BOX}
                  checked={all}
                  ref={(el) => {
                    if (el) el.indeterminate = n > 0 && !all;
                  }}
                  onChange={() => onGroup(keys, !all)}
                />
                <span className="truncate text-sm font-semibold">{g.label}</span>
              </label>
              <span className={cn("shrink-0 text-ui tabular-nums", all ? `
                font-semibold text-primary
              ` : `text-muted`)}>
                {fill(t.countOf, { n, total: keys.length })}
              </span>
            </div>
            {open ? (
              <ul id={listId} className="px-2 pb-2 sm:px-4">
                {g.perms.map((p) => (
                  <li key={p.key} className={cn("relative pl-16.5", TREE_LINE)}>
                    <label className={cn(`
                      flex min-h-11 cursor-pointer items-start gap-3 rounded-lg py-2.5 pr-2 pl-1
                      transition-colors
                      focus-within:bg-primary-softer
                      hover:bg-primary-softer
                    `)}>
                      <input type="checkbox" className={cn(BOX, "mt-0.5")} checked={draft.has(p.key)} onChange={() => onToggle(p.key)} />
                      <span className="flex min-w-0 flex-col">
                        <span className="text-sm">{p.label}</span>
                        {p.hint ? <span className="text-ui text-muted">{p.hint}</span> : null}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
