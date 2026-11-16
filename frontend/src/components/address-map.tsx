import { cn } from "@/lib/cn";

// Bản đồ dựng từ tọa độ (ghim đúng) hoặc địa chỉ dạng chữ: không dùng chuỗi Admin nhập, tọa độ + link đều đã qua API. Không cần API key.
// CSP: https://www.google.com đã mở ở frame-src (next.config.ts).

type MapPlace = { address: string; map_url?: string | null; lat?: number | null; lng?: number | null };

const mapsQuery = ({ address, lat, lng }: MapPlace) => encodeURIComponent(lat != null && lng != null ? `${lat},${lng}` : address.trim());

/** Link "Mở Google Maps": link Admin đã lưu ⇒ tọa độ ⇒ địa chỉ. */
export const mapsOpenUrl = (place: MapPlace) => place.map_url ?? `https://www.google.com/maps/search/?api=1&query=${mapsQuery(place)}`;

/** Khung bản đồ cỡ cố định. Không có địa chỉ lẫn tọa độ ⇒ không hiện. */
export function AddressMap({ place, title, className = "h-52 w-full" }: { place: MapPlace; /** Tên khung cho trình đọc màn hình. */ title: string; /** Cỡ khung. */ className?: string }) {
  const query = mapsQuery(place);
  if (!query) return null;
  return (
    <iframe
      // Đổi nơi là nạp bản đồ mới
      key={query}
      src={`https://www.google.com/maps?q=${query}&output=embed`}
      title={title}
      loading="lazy"
      referrerPolicy="no-referrer"
      className={cn("rounded-lg border", className)}
    />
  );
}
