import { fullAddress, site } from "@/lib/site";

export function SiteFooter() {
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
            Hotline: <a href={`tel:${site.phone.replace(/\s/g, "")}`}>{site.phone}</a>
            <br />
            Email: <a href={`mailto:${site.email}`}>{site.email}</a>
          </p>
        </div>
        <div>
          <p className="font-semibold">Giờ mở cửa</p>
          <p className="mt-2 text-muted">
            Hằng ngày {site.openingHours.open} – {site.openingHours.close}
          </p>
        </div>
      </div>
    </footer>
  );
}
