"use client";

import { useRouter } from "next/navigation";
import { AvatarEditor } from "@/components/member-area/avatar-editor";
import { avatarBody } from "@/components/member-area/requests";
import type { Crop } from "@/components/member-area/types";
import { SiteLogo } from "@/components/site-logo";
import type { Dictionary } from "@/i18n/dictionaries";
import { api } from "@/lib/api/client";
import { write } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";

type Props = {
  url: string | null;
  /** Server action xóa cache trang khách theo tag API trả về. */
  refresh: (tag: string) => Promise<void>;
  /** Tên chữ cạnh logo trong phần xem trước. */
  brandDark: string;
  brandLight: string;
  t: Dictionary["siteLogo"];
};

/** Phần logo của Thông tin web: dùng lại AvatarEditor (nút máy ảnh, cắt ảnh, xác nhận xóa) ở dạng vuông; lưu ngay khi cắt xong; có xem trước trên header sáng và tối. */
export function LogoSection({ url, refresh, brandDark, brandLight, t }: Props) {
  const router = useRouter();

  // Logo đã lưu mà xóa cache lỗi ⇒ vẫn báo thành công, nói rõ trang khách cập nhật sau (cache tự hết hạn)
  const refreshCache = (tag: string) => refresh(tag).catch(() => toast(t.cacheLater, undefined, "info"));

  async function upload(file: File, crop: Crop) {
    const res = await write(() => api.PUT("/api/v1/admin/site/logo", avatarBody(file, crop)));
    if (!res.ok) return res;
    await refreshCache(res.data.cache_tag);
    return { ...res, data: { avatar_url: res.data.logo_url ?? "" } };
  }
  async function remove() {
    const res = await write(() => api.DELETE("/api/v1/admin/site/logo"));
    if (res.ok) await refreshCache(res.data.cache_tag);
    return res;
  }

  const strip = "flex min-w-0 items-center gap-2 rounded-lg px-2.5 py-1.5 text-ui font-semibold";
  return (
    <section aria-labelledby="logo-title" className="flex flex-col gap-4">
      <h3 id="logo-title" className="text-sm font-semibold">{t.title}</h3>
      {/* Một hàng: ảnh + trạng thái + nút Đổi / Xóa (điện thoại: nút xuống dưới) */}
      <AvatarEditor
        hasImage={url !== null}
        shape="square"
        actions="buttons"
        upload={upload}
        remove={remove}
        onChange={() => router.refresh()}
        texts={t.editor}
        className="flex flex-wrap items-center gap-x-4 gap-y-3"
      >
        <SiteLogo url={url} className="size-18 ring-1 ring-border [&>svg]:size-9" />
        <div className="flex min-w-0 flex-1 basis-40 flex-col gap-0.5">
          <p className="text-sm font-semibold">{url ? t.statusCustom : t.statusDefault}</p>
          <p className="text-ui text-muted">{t.hint}</p>
        </div>
      </AvatarEditor>
      {/* Xem trước đầu trang, nhỏ gọn */}
      <div className="grid gap-2 sm:grid-cols-2" aria-label={t.previewTitle} role="group">
        <div className={cn(strip, "border text-primary")}>
          <SiteLogo url={url} className="size-6 [&>svg]:size-4" />
          <span className="truncate">{brandLight}</span>
        </div>
        <div className={cn(strip, "bg-sidebar text-sidebar-fg")}>
          <SiteLogo url={url} onDark className="size-6 [&>svg]:size-4" />
          <span className="truncate">{brandDark}</span>
        </div>
      </div>
    </section>
  );
}
