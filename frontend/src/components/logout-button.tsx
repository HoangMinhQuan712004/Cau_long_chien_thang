"use client";

import { api } from "@/lib/api/client";

export function LogoutButton() {
  return (
    <button
      type="button"
      onClick={async () => {
        await api.POST("/api/v1/auth/logout").catch(() => {});
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.href = "/";
      }}
      className="text-sm text-muted hover:text-danger"
    >
      Đăng xuất
    </button>
  );
}
