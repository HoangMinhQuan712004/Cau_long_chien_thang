import { getPublicPrices } from "@/lib/api/server";
import { fullAddress, phoneHref, site } from "@/lib/site";

export async function SiteFooter() {
  // Giờ mở cửa lấy từ booking engine (một nguồn sự thật); chưa có sân hoạt động → ẩn mục này.
  const hours = (await getPublicPrices())?.opening_hours;
  const open = hours?.earliest_open?.slice(0, 5);
  const close = hours?.latest_close?.slice(0, 5);
  return (
    <footer className="mt-16 border-t border-border bg-surface">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-10 text-sm sm:grid-cols-3">
        <div>
          <p className="font-semibold">{site.name}</p>
          <address className="mt-2 not-italic text-muted">{fullAddress}</address>
        </div>
        <div>
          <p className="font-semibold">Liên hệ</p>
          <p className="mt-2 text-muted">
            Hotline: <a href={phoneHref}>{site.phone}</a>
            <br />
            Email: <a href={`mailto:${site.email}`}>{site.email}</a>
          </p>
        </div>
        {open && close ? (
          <div>
            <p className="font-semibold">Giờ mở cửa</p>
            <p className="mt-2 text-muted">
              Hằng ngày {open} – {close}
            </p>
          </div>
        ) : null}
      </div>
    </footer>
  );
}
