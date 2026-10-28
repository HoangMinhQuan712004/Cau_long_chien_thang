import { useLayoutEffect, useRef } from "react";

// Reset state khi trang bị Next giữ ẩn (<Activity>), để quay lại (Back, đăng xuất) là form mới
export function useResetOnHide(reset: () => void) {
  const latest = useRef(reset);
  useLayoutEffect(() => {
    latest.current = reset;
  });
  useLayoutEffect(() => () => latest.current(), []);
}
