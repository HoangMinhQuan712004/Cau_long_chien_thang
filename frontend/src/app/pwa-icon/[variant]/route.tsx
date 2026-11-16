import { ImageResponse } from "next/og";

// Icon PNG cho app cài từ web (PWA): quả cầu lông trắng TO, nét đậm trên nền xanh (người dùng 16/11: icon cũ nhỏ, khó nhận ra).
// Sinh bằng code (không thêm file ảnh). "-maskable": nền tràn hết, hình nằm trong vùng an toàn 60% để Android bo
// tròn / bo góc tuỳ máy không cắt mất hình. Màu phải là mã hex (ảnh PNG không đọc được biến CSS) = --primary.

const PRIMARY = "#1a7354";
const VARIANTS = ["180", "192", "512", "192-maskable", "512-maskable"] as const;
type Variant = (typeof VARIANTS)[number];

export function generateStaticParams() {
  return VARIANTS.map((variant) => ({ variant }));
}

export async function GET(_req: Request, { params }: { params: Promise<{ variant: string }> }) {
  const { variant } = await params;
  if (!VARIANTS.includes(variant as Variant)) return new Response("Not found", { status: 404 });
  const size = Number.parseInt(variant, 10);
  const maskable = variant.endsWith("maskable");
  const glyph = Math.round(size * (maskable ? 0.68 : 0.86));
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: PRIMARY }}>
        <svg width={glyph} height={glyph} viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth={2.1} strokeLinecap="round" strokeLinejoin="round">
          {/* translate: hình xoay 45° bị lệch lên góc phải ⇒ dời về giữa */}
          <g transform="translate(-1.4 1.4) rotate(45 12 12)">
            <path d="M9.6 15.5 6 3.5h12l-3.6 12" fill="rgba(255,255,255,0.22)" />
            <path d="M12 3.5v12" />
            <path d="M7.6 9.5h8.8" />
            <path d="M9.6 15.5h4.8v2.1a2.4 2.4 0 0 1-4.8 0z" fill="#ffffff" />
          </g>
        </svg>
      </div>
    ),
    { width: size, height: size, headers: { "Cache-Control": "public, max-age=86400" } },
  );
}
