"use client";

import { useState } from "react";

const NONE: ReadonlySet<string> = new Set();

/** Danh sách có nhóm thu gọn được (Dropdown dạng cây): chỉ số các mục đang hiện + bật/tắt từng nhóm. Mặc định mở hết. */
export function useGroupCollapse(items: readonly { group?: string }[]) {
  const [collapsed, setCollapsed] = useState(NONE);
  const visibleOf = (set: ReadonlySet<string>) => items.flatMap((o, i) => (o.group && set.has(o.group) ? [] : [i]));

  /** Đảo trạng thái một nhóm; trả các mục hiện sau khi đảo (để giữ mục đang trỏ). */
  function toggle(group: string) {
    const next = new Set(collapsed);
    if (!next.delete(group)) next.add(group);
    setCollapsed(next);
    return visibleOf(next);
  }

  return {
    visible: visibleOf(collapsed),
    isCollapsed: (group: string) => collapsed.has(group),
    hasCollapsed: collapsed.size > 0,
    toggle,
    reset: () => setCollapsed(NONE),
  };
}
