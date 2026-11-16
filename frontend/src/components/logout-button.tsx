"use client";

import { useEffect, useState } from "react";
import { adminLogout } from "@/lib/api/auth";
import { api } from "@/lib/api/client";
import { clearPending } from "@/components/web-booking/pending-checkout";

// Đăng xuất rồi tải lại: hội viên về trang chủ, Admin/NV về /dang-nhap (điều hướng cứng: bỏ các trang Next đang giữ ẩn, Back không quay lại)
export function LogoutButton({
  area = "member",
  className = "text-sm text-muted hover:text-danger disabled:opacity-50",
  children = "Đăng xuất",
}: {
  area?: "member" | "admin";
  className?: string;
  children?: React.ReactNode;
}) {
  const [isPending, setIsPending] = useState(false);

  // Back lấy trang từ bfcache ⇒ tải lại để máy chủ kiểm phiên
  useEffect(() => {
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted) window.location.reload();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  return (
    <button
      type="button"
      disabled={isPending}
      onClick={async () => {
        setIsPending(true);
        if (area === "admin") await adminLogout();
        else {
          await api.POST("/api/v1/auth/logout").catch(() => {});
          clearPending(true); // T-075 AC9: quên lượt đang chờ thanh toán của khu hội viên
        }
        window.location.replace(area === "admin" ? "/dang-nhap" : "/");
      }}
      className={className}
    >
      {children}
    </button>
  );
}
