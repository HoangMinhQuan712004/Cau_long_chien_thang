"use client";

import Link from "next/link";

// Khách chưa đăng nhập ở /dat-san bước 2: gợi ý đăng nhập / đăng ký để tự điền thông tin (T-013 AC39).
// `next` là /dat-san?ngay=… ⇒ hội viên đăng nhập xong vào /hoi-vien/dat-san cùng ngày. `onLeave` (trước khi rời trang)
// lưu các khung đang chọn để màn đặt sân sau đăng nhập mở lại đúng bước xác nhận, thông tin tự điền (người dùng 17/11).
export function MemberHint({ next, compact = false, onLeave }: { next: string; compact?: boolean; onLeave?: () => void }) {
  const q = `?next=${encodeURIComponent(next)}`;
  // Dạng khối xanh gọn trong popup mua vé (T-023 AC17)
  if (compact) {
    return (
      <section aria-labelledby="member-hint-title" className="rounded-xl bg-primary p-4 text-surface">
        <h3 id="member-hint-title" className="text-sm font-bold">
          Đăng nhập để thanh toán nhanh hơn
        </h3>
        <p className="mt-0.5 text-xs text-surface/85">Đăng nhập hoặc đăng ký hội viên để tự điền thông tin.</p>
        <div className="mt-3 flex gap-2">
          <Link href={`/dang-ky${q}`} onClick={onLeave} className="inline-flex min-h-10 items-center rounded-lg bg-primary-hover px-4 text-sm font-semibold text-surface focus-ring">
            Đăng ký
          </Link>
          <Link href={`/dang-nhap${q}`} onClick={onLeave} className="inline-flex min-h-10 items-center rounded-lg bg-surface px-4 text-sm font-semibold text-primary focus-ring">
            Đăng nhập
          </Link>
        </div>
      </section>
    );
  }
  return (
    <section aria-labelledby="member-hint-title" className="rounded-2xl border border-primary/20 bg-primary-softer p-5">
      <h3 id="member-hint-title" className="text-base font-bold">
        Bạn là hội viên?
      </h3>
      <p className="mt-1 text-sm text-muted">Đăng nhập để tự điền thông tin.</p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Link
          href={`/dang-nhap${q}`} onClick={onLeave}
          className="inline-flex min-h-11 flex-1 items-center justify-center rounded-lg border border-primary px-4 text-sm font-semibold text-primary hover:bg-surface"
        >
          Đăng nhập
        </Link>
        <Link
          href={`/dang-ky${q}`} onClick={onLeave}
          className="inline-flex min-h-11 flex-1 items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-hover"
        >
          Đăng ký hội viên
        </Link>
      </div>
    </section>
  );
}
