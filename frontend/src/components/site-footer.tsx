import { Suspense } from "react";
import { AddressMap, mapsOpenUrl } from "@/components/address-map";
import { openingText, WithPublicPrices } from "@/components/public-prices";
import { getBranding } from "@/lib/api/server";

const TITLE = "font-semibold wrap-anywhere";
// Địa chỉ là link: điện thoại cao 44px bằng padding, bù lề âm để chữ vẫn cách tiêu đề như cột khác; từ sm chữ thẳng hàng, không cần vùng chạm cao
const ADDRESS = "-mt-1 -mb-3 not-italic sm:mt-2 sm:mb-0";
const ADDRESS_LINK = "block rounded-sm py-3 wrap-anywhere text-muted focus-ring hover:text-primary hover:underline sm:py-0";

export async function SiteFooter() {
  const info = await getBranding();
  return (
    <footer className="mt-16 border-t border-border bg-surface">
      <div className="mx-auto grid max-w-6xl gap-x-8 gap-y-6 px-4 py-10 text-sm sm:grid-cols-3">
        <div>
          <p className={TITLE}>{info.name}</p>
          <address className={ADDRESS}>
            {/* Địa chỉ bấm được: mở Google Maps (link đã lưu ⇒ tọa độ ⇒ địa chỉ) */}
            <a href={mapsOpenUrl(info)} className={ADDRESS_LINK}>
              {info.address}
            </a>
          </address>
          {/* Bản đồ nhỏ ngay dưới địa chỉ */}
          <AddressMap place={info} title={`Bản đồ: ${info.address}`} className="mt-3 h-40 w-full max-w-80" />
        </div>
        <div>
          <p className={TITLE}>Liên hệ</p>
          <p className="mt-2 wrap-anywhere text-muted">
            Hotline: {info.phone}
            <br />
            Email: {info.email}
          </p>
        </div>
        {/* Giờ mở cửa lấy từ booking engine lúc chạy (một nguồn sự thật); chưa có dữ liệu → ẩn cả mục, không in số tĩnh. */}
        <Suspense fallback={null}>
          <WithPublicPrices>
            {(data) =>
              openingText(data) ? (
                <div>
                  <p className={TITLE}>Giờ mở cửa</p>
                  <p className="mt-2 text-muted">Hằng ngày {openingText(data)}</p>
                </div>
              ) : null
            }
          </WithPublicPrices>
        </Suspense>
      </div>
    </footer>
  );
}
