"use client";

import { useState } from "react";
import { MENU_COLLAPSED, MENU_COOKIE } from "./menu-cookie";

/** Menu bên máy tính đang thu gọn (chỉ icon) hay mở rộng; giá trị đầu lấy từ cookie phía server. */
export function useSidebarCollapsed(initial: boolean) {
  const [isCollapsed, setIsCollapsed] = useState(initial);
  const toggle = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    // Không httpOnly vì client ghi; 1 năm; chỉ khu /admin
    document.cookie = `${MENU_COOKIE}=${next ? MENU_COLLAPSED : "mo-rong"}; Path=/admin; Max-Age=31536000; SameSite=Lax`;
  };
  return [isCollapsed, toggle] as const;
}
