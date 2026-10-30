"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { errorText } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { putAvatar } from "./requests";
import type { Crop } from "./types";

const VIEW = 280; // khung cắt vuông (px màn hình)
const PREVIEW = 96; // xem trước tròn, đúng cỡ hero
const MAX_ZOOM = 4;

/** Hộp cắt ảnh vuông: kéo để dời, thanh trượt để phóng to; xem trước tròn; "Lưu ảnh" lưu ngay (T-016 AC18). */
export function CropDialog({ file, onClose, onSaved }: { file: File; onClose: () => void; onSaved: (url: string) => void }) {
  const [src] = useState(() => URL.createObjectURL(file));
  const [dim, setDim] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 }); // góc trên trái của ảnh trong khung
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const drag = useRef<{ px: number; py: number; ox: number; oy: number } | null>(null);
  const sending = useRef(false);

  useEffect(() => () => URL.revokeObjectURL(src), [src]);

  // Cỡ ảnh gốc → khung mặc định: giữa ảnh, lớn nhất có thể
  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth;
      const h = img.naturalHeight;
      const s = VIEW / Math.min(w, h);
      setDim({ w, h });
      setPos({ x: (VIEW - w * s) / 2, y: (VIEW - h * s) / 2 });
    };
    img.onerror = () => setBanner("Ảnh phải là JPG, PNG hoặc WebP, tối đa 5 MB.");
    img.src = src;
  }, [src]);

  const base = dim ? VIEW / Math.min(dim.w, dim.h) : 1;
  const scale = base * zoom;
  const clamp = (x: number, y: number, s = scale) => ({
    x: dim ? Math.min(0, Math.max(VIEW - dim.w * s, x)) : 0,
    y: dim ? Math.min(0, Math.max(VIEW - dim.h * s, y)) : 0,
  });

  function changeZoom(z: number) {
    if (!dim) return;
    const ns = base * z;
    // Giữ nguyên điểm giữa khung khi phóng to / thu nhỏ
    const cx = (VIEW / 2 - pos.x) / scale;
    const cy = (VIEW / 2 - pos.y) / scale;
    setZoom(z);
    setPos(clamp(VIEW / 2 - cx * ns, VIEW / 2 - cy * ns, ns));
  }

  function crop(): Crop {
    return { x: -pos.x / scale, y: -pos.y / scale, size: VIEW / scale };
  }

  async function save() {
    if (sending.current || !dim) return;
    sending.current = true;
    setBusy(true);
    setBanner("");
    const res = await putAvatar(file, crop());
    sending.current = false;
    setBusy(false);
    if (!res.ok) return setBanner(res.error.code === "E-HV-13" ? res.error.message : errorText(res.error));
    toast("Đã cập nhật ảnh đại diện");
    onSaved(res.data.avatar_url);
  }

  const k = PREVIEW / VIEW;

  return (
    <Modal
      open
      onClose={onClose}
      title="Cắt ảnh đại diện"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Hủy
          </Button>
          <Button onClick={save} loading={busy} disabled={!dim}>
            {busy ? "Đang lưu…" : "Lưu ảnh"}
          </Button>
        </>
      }
    >
      {banner ? (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-sm text-danger">
          {banner}
        </p>
      ) : null}
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
        <div
          role="img"
          aria-label="Khung cắt ảnh: kéo để dời ảnh"
          style={{ width: VIEW, height: VIEW, touchAction: "none" }}
          className="relative shrink-0 cursor-grab overflow-hidden rounded-lg bg-background active:cursor-grabbing"
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            drag.current = { px: e.clientX, py: e.clientY, ox: pos.x, oy: pos.y };
          }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (d) setPos(clamp(d.ox + e.clientX - d.px, d.oy + e.clientY - d.py));
          }}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
        >
          {dim ? (
            // eslint-disable-next-line @next/next/no-img-element -- xem trước tệp đang chọn (blob:)
            <img src={src} alt="" draggable={false} style={{ position: "absolute", left: pos.x, top: pos.y, width: dim.w * scale, height: dim.h * scale, maxWidth: "none" }} />
          ) : null}
          {/* Lưới 1/3 giúp căn khung */}
          <span aria-hidden className="pointer-events-none absolute inset-0 rounded-lg ring-1 ring-black/10 ring-inset" />
        </div>
        <div className="flex w-full flex-col items-center gap-4 sm:w-auto">
          <div>
            <p className="mb-1.5 text-center text-label font-semibold text-muted">Xem trước</p>
            <div style={{ width: PREVIEW, height: PREVIEW }} className="relative overflow-hidden rounded-full bg-background ring-1 ring-border">
              {dim ? (
                // eslint-disable-next-line @next/next/no-img-element -- xem trước tệp đang chọn (blob:)
                <img src={src} alt="" draggable={false} style={{ position: "absolute", left: pos.x * k, top: pos.y * k, width: dim.w * scale * k, height: dim.h * scale * k, maxWidth: "none" }} />
              ) : null}
            </div>
          </div>
          <label className="flex w-full flex-col gap-1.5 text-label font-semibold text-muted">
            Phóng to
            <input
              type="range"
              min={1}
              max={MAX_ZOOM}
              step={0.01}
              value={zoom}
              disabled={!dim}
              onChange={(e) => changeZoom(Number(e.target.value))}
              className="w-full accent-primary"
            />
          </label>
        </div>
      </div>
    </Modal>
  );
}
