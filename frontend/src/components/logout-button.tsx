"use client";

import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";

export function LogoutButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={async () => {
        await api.POST("/api/v1/auth/logout").catch(() => {});
        router.replace("/");
        router.refresh();
      }}
      className="text-sm text-muted hover:text-danger"
    >
      Đăng xuất
    </button>
  );
}
