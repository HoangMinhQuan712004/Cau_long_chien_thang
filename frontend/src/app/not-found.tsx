import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-4 px-4 py-16 text-center">
      <h1 className="text-2xl font-bold">Không tìm thấy trang</h1>
      <p className="text-muted">Trang bạn tìm không tồn tại hoặc đã bị xóa.</p>
      <Link href="/" className="inline-block rounded-md bg-primary px-4 py-2 text-white">
        Về trang chủ
      </Link>
    </div>
  );
}
