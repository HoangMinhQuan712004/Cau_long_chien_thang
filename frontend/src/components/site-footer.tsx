import { Suspense } from "react";
import { AddressMap, mapsOpenUrl } from "@/components/address-map";
import { openingText, WithPublicPrices } from "@/components/public-prices";
import { NetMesh } from "@/components/net-mesh";
import { getBranding } from "@/lib/api/server";

// Footer chung của web – kiểu "danh sách icon" người dùng chọn 12/11: nền xanh đậm có lưới mờ như banner; tên sân lớn,
// các dòng icon (địa chỉ → Google Maps, hotline, email, giờ mở cửa) và bản đồ. Điện thoại: xếp dọc, bản đồ rộng hết.
// Giờ mở cửa lấy từ booking engine lúc chạy (một nguồn sự thật); chưa có dữ liệu → ẩn dòng, không in số tĩnh.

const ICON = {
  pin: "M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  phone: "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z",
  mail: "M4 6h16v12H4zM4 7l8 6 8-6",
  clock: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
};

function Row({ icon, children }: { icon: keyof typeof ICON; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-3">
      <svg viewBox="0 0 24 24" className="mt-0.5 size-5 shrink-0 text-accent" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d={ICON[icon]} />
      </svg>
      <span className="min-w-0 wrap-anywhere text-surface/85">{children}</span>
    </li>
  );
}

export async function SiteFooter() {
  const info = await getBranding();
  return (
    <footer className="relative isolate mt-16 overflow-hidden bg-appbar text-sm text-surface">
      {/* Mắt lưới mờ 2 đầu như banner */}
      <NetMesh />
      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-4 py-8 sm:gap-8 sm:py-10 md:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_16rem] lg:items-start">
        <div className="min-w-0">
          <p className="text-xl leading-tight font-extrabold tracking-tight wrap-anywhere sm:text-2xl">{info.name}</p>
          <p className="mt-2 max-w-xs text-surface/70">Đặt sân online, tìm bạn chơi, theo dõi kỷ lục cú đập.</p>
        </div>
        <ul className="min-w-0 space-y-3">
          <Row icon="pin">
            {/* Địa chỉ bấm được: mở Google Maps (link đã lưu ⇒ tọa độ ⇒ địa chỉ); điện thoại vùng chạm cao bằng padding */}
            <a href={mapsOpenUrl(info)} className="-my-2.5 inline-block rounded-sm py-2.5 hover:text-surface hover:underline focus-ring sm:my-0 sm:py-0">
              {info.address}
            </a>
          </Row>
          <Row icon="phone">{info.phone}</Row>
          <Row icon="mail">{info.email}</Row>
          <Suspense fallback={null}>
            <WithPublicPrices>{(data) => (openingText(data) ? <Row icon="clock">Mở cửa hằng ngày {openingText(data)}</Row> : null)}</WithPublicPrices>
          </Suspense>
        </ul>
        <AddressMap place={info} title={`Bản đồ: ${info.address}`} className="h-44 w-full border-surface/20 md:col-span-2 lg:col-span-1 lg:h-40" />
      </div>
    </footer>
  );
}
