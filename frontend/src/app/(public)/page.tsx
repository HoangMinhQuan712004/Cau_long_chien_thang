import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/json-ld";
import { PriceTable } from "@/components/price-table";
import { getCourts, getPriceRules } from "@/lib/api/server";
import { formatVnd } from "@/lib/format";
import { fullAddress, site } from "@/lib/site";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default async function HomePage() {
  const [courts, rules] = await Promise.all([getCourts(), getPriceRules()]);
  const prices = rules.map((r) => r.price_per_hour);

  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "SportsActivityLocation",
          name: site.name,
          description: site.description,
          url: site.url,
          telephone: site.phone,
          address: {
            "@type": "PostalAddress",
            streetAddress: `${site.address.street}, ${site.address.ward}`,
            addressLocality: site.address.district,
            addressRegion: site.address.city,
            addressCountry: site.address.country,
          },
          geo: { "@type": "GeoCoordinates", latitude: site.geo.lat, longitude: site.geo.lng },
          openingHoursSpecification: {
            "@type": "OpeningHoursSpecification",
            dayOfWeek: [
              "Monday",
              "Tuesday",
              "Wednesday",
              "Thursday",
              "Friday",
              "Saturday",
              "Sunday",
            ],
            opens: site.openingHours.open,
            closes: site.openingHours.close,
          },
          ...(prices.length && {
            priceRange: `${formatVnd(Math.min(...prices))} – ${formatVnd(Math.max(...prices))}/giờ`,
          }),
        }}
      />

      <section className="grid items-center gap-8 py-8 md:grid-cols-2">
        <div>
          <h1 className="text-3xl font-bold leading-tight sm:text-4xl">
            {site.name}
            <span className="block text-primary">Đặt sân online trong 30 giây</span>
          </h1>
          <p className="mt-4 text-muted">{site.description}</p>
          <p className="mt-2 text-sm text-muted">📍 {fullAddress}</p>
          <div className="mt-6 flex gap-3">
            <Link
              href="/dat-san"
              className="rounded-md bg-primary px-5 py-3 font-medium text-surface"
            >
              Xem lịch trống &amp; đặt sân
            </Link>
            <Link href="/bang-gia" className="rounded-md border border-border px-5 py-3">
              Bảng giá
            </Link>
          </div>
        </div>
        <ul className="grid grid-cols-2 gap-3">
          {courts.map((c) => (
            <li key={c.id} className="rounded-lg border border-border bg-surface p-4">
              <p className="font-semibold">{c.name}</p>
              {c.surface && <p className="text-sm text-muted">{c.surface}</p>}
            </li>
          ))}
        </ul>
      </section>

      <section className="py-8">
        <h2 className="mb-4 text-2xl font-semibold">Bảng giá thuê sân</h2>
        <PriceTable rules={rules} />
      </section>
    </>
  );
}
