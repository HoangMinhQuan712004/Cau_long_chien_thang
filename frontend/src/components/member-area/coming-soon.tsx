import Link from "next/link";

/** Mục menu khu hội viên chưa có nội dung (đợt sau của T-016). */
export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="mx-auto flex max-w-6xl flex-col items-center px-4 py-20 text-center">
      <h1 className="text-2xl font-bold">{title}</h1>
      <p className="mt-3 text-lg font-semibold text-primary">Sắp ra mắt</p>
      <p className="mt-2 max-w-sm text-sm text-muted">Mục này đang được hoàn thiện. Bạn quay lại sau nhé.</p>
      <Link href="/hoi-vien/ho-so" className="mt-6 rounded-lg border border-primary px-4 py-2 text-sm font-semibold text-primary hover:bg-primary-softer focus-ring">
        Về Hồ sơ của tôi
      </Link>
    </div>
  );
}
