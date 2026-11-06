"use client";

import { useRouter } from "next/navigation";
import { AvatarEditor } from "@/components/member-area/avatar-editor";
import { avatarBody } from "@/components/member-area/requests";
import { AvatarImage } from "@/components/ui/avatar";
import { api } from "@/lib/api/client";
import { write } from "@/lib/api/write";

/** Ảnh đại diện ở Hồ sơ của tôi (Admin + nhân viên): cùng trải nghiệm với khu hội viên, gọi API quản trị. */
export function ProfileAvatar({ url, initials, className, imageClassName }: {
  url: string | null;
  /** Chữ viết tắt khi chưa có ảnh. */
  initials: string;
  className?: string;
  imageClassName?: string;
}) {
  const router = useRouter();
  return (
    <AvatarEditor
      hasImage={url !== null}
      // Endpoint này không dùng Idempotency-Key (ghi đè / xóa lặp lại vẫn cho cùng kết quả)
      upload={(file, crop) => write(() => api.PUT("/api/v1/admin/auth/me/avatar", avatarBody(file, crop)))}
      remove={() => write(() => api.DELETE("/api/v1/admin/auth/me/avatar"))}
      // Header + Hồ sơ lấy ảnh từ server, URL có ?v= mới ⇒ tải lại dữ liệu server (không tải lại cả trang)
      onChange={() => router.refresh()}
      className={className}
    >
      <span aria-hidden className={imageClassName}>
        <AvatarImage url={url} fallback={initials} />
      </span>
    </AvatarEditor>
  );
}
