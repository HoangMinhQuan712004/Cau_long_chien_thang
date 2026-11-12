"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { cn } from "@/lib/cn";

// Đèn rọi sân khấu của bục top 3 (Bảng xếp hạng): 3 luồng SVG theo khung bục, kịch bản đổi chỗ / hội tụ, quầng ombre.

// Ombre luồng đèn theo màu đo từ ảnh mẫu: đỉnh trắng mờ (nền + ~15% trắng ≈ #355546) → giữa vàng ấm (nền + ~20%
// vàng ≈ #465832 ô liu) → tan dần về bục
type Stop = [offset: number, color: string, opacity: number];
// Ô liu dịu: vàng pha xanh chủ đạo (đỡ chói hơn vàng nguyên)
const OLIVE = "color-mix(in srgb, var(--cta) 35%, var(--primary))";
// Đỉnh luồng ngà ô liu (trắng pha nửa ô liu) – không trắng gắt
const TOP_TONE = `color-mix(in srgb, var(--surface) 50%, ${OLIVE})`;
const OMBRE: Stop[] = [
  [0, TOP_TONE, 0.1],
  [0.5, OLIVE, 0.13],
  [1, OLIVE, 0],
];
// Lung linh: đỉnh (stop 0) lấp lánh, giữa (stop 1) đổi màu nhẹ – giảm chuyển động ⇒ CSS tắt animation, giữ màu gốc
const SHIMMER = ["animate-beam-twinkle", "animate-beam-tint", ""];
// 3 luồng đèn (toạ độ % theo khung bục: x 0–100 ngang, y 0 = đỉnh đèn (trên mép banner), 100 = chân bục): hẹp ở điểm
// treo, loe ở chân. Edges = [trên-trái, trên-phải, dưới-phải, dưới-trái]
type Edges = [[number, number], [number, number], [number, number], [number, number]];
type Span = [number, number];
// Điểm treo của 3 đèn ở đỉnh (2 đèn bên chồng nhẹ lên mép đèn giữa) và vùng rọi ở chân (theo cột bục)
const LAMP_L: Span = [33.5, 46.5];
const LAMP_C: Span = [44, 56];
const LAMP_R: Span = [53.5, 66.5];
const ON_2: Span = [-1, 33];
const ON_1: Span = [33, 67];
const ON_3: Span = [67, 101];
const FOCUS_1: Span = [38, 62]; // cả 3 đèn hội tụ vào hạng 1: thu hẹp lại
const aim = ([t1, t2]: Span, [b1, b2]: Span): Edges => [[t1, 0], [t2, 0], [b2, 100], [b1, 100]];

// Kịch bản ánh sáng sân khấu (mỗi vòng 4 bước rồi lặp): mở màn rọi 3 hạng → hội tụ vào hạng 1 → 2 đèn bên bắt chéo
// (trái rọi hạng 3, phải rọi hạng 2) → hội tụ lần nữa → về mở màn
const BEAMS = [
  { id: "l", shots: [aim(LAMP_L, ON_2), aim(LAMP_L, FOCUS_1), aim(LAMP_L, ON_3), aim(LAMP_L, FOCUS_1)] },
  { id: "c", shots: [aim(LAMP_C, ON_1), aim(LAMP_C, FOCUS_1), aim(LAMP_C, ON_1), aim(LAMP_C, FOCUS_1)] },
  { id: "r", shots: [aim(LAMP_R, ON_3), aim(LAMP_R, FOCUS_1), aim(LAMP_R, ON_2), aim(LAMP_R, FOCUS_1)] },
];
// Mỗi bước: dừng rọi HOLD giây rồi quét MOVE giây sang bước sau (tăng tốc rồi hãm êm)
const MOVE = 1.8;
const HOLD = 1;
const STEPS = BEAMS[0].shots.length;
const LOOP = STEPS * (MOVE + HOLD);

const pts = (e: [number, number][]) => e.map(([x, y]) => `${x},${y}`).join(" ");

/** Mốc thời gian chung cho mọi hiệu ứng của đèn: [dừng bắt đầu, dừng kết thúc] mỗi bước + điểm cuối vòng. */
function timeline<T>(frames: T[]) {
  const values: T[] = [];
  const times: number[] = [];
  const splines: string[] = [];
  frames.forEach((f, i) => {
    const t = i * (MOVE + HOLD);
    values.push(f, f);
    times.push(t / LOOP, (t + HOLD) / LOOP);
    splines.push("0 0 1 1", "0.65 0 0.35 1"); // dừng: giữ nguyên · quét: tăng tốc rồi hãm êm (như đèn moving-head)
  });
  values.push(frames[0]);
  times.push(1);
  return { values: values.join(";"), keyTimes: times.map((t) => t.toFixed(4)).join(";"), keySplines: splines.join(";") };
}

/** Đổi hình dạng luồng theo kịch bản, lặp vô hạn. */
function Morph({ shapes }: { shapes: string[] }) {
  return <animate attributeName="points" {...timeline(shapes)} calcMode="spline" dur={`${LOOP}s`} repeatCount="indefinite" />;
}

/** Dịu khi quét, sáng khi dừng rọi (như đèn sân khấu thật): opacity 1 lúc dừng, ~0.55 giữa lúc quét. */
function Pulse() {
  // Mỗi bước: giữ 1 suốt lúc dừng, mờ xuống giữa đoạn quét rồi sáng lại khi tới chỗ mới
  const values: string[] = [];
  const times: number[] = [];
  for (let i = 0; i < STEPS; i++) {
    const t0 = i * (MOVE + HOLD);
    values.push("1", "1", "0.55");
    times.push(t0 / LOOP, (t0 + HOLD) / LOOP, (t0 + HOLD + MOVE / 2) / LOOP);
  }
  values.push("1");
  times.push(1);
  return <animate attributeName="opacity" values={values.join(";")} keyTimes={times.map((x) => x.toFixed(4)).join(";")} dur={`${LOOP}s`} repeatCount="indefinite" />;
}

const REDUCED = "(prefers-reduced-motion: reduce)";
const onMotionChange = (cb: () => void) => {
  const m = window.matchMedia(REDUCED);
  m.addEventListener("change", cb);
  return () => m.removeEventListener("change", cb);
};
/** Máy bật "giảm chuyển động" (server: coi như bật ⇒ không dựng hiệu ứng lúc render đầu). */
const useReducedMotion = () => useSyncExternalStore(onMotionChange, () => window.matchMedia(REDUCED).matches, () => true);

/** Đèn rọi sân khấu như mẫu: 3 luồng hẹp trên – loe dưới, 2 đèn bên chồng nhẹ lên đèn giữa ở đỉnh, rọi xuống hạng 2 · 1 · 3; màu ombre
 *  trắng mờ → vàng ô liu ấm (đo từ ảnh mẫu), tan dần về bục; mép có line rất mảnh, mờ, cùng ombre.
 *  Hiệu ứng: kịch bản ánh sáng sân khấu (rọi 3 hạng → hội tụ hạng 1 → bắt chéo → hội tụ), dịu khi quét – sáng khi
 *  dừng, quầng sáng "thở"; giảm chuyển động ⇒ đứng yên ở bước mở màn.
 *  Đỉnh đèn đặt cao hơn mép banner, banner (overflow-hidden) cắt phần thừa. */
/** Đèn đang nằm trong màn hình và trang / app không chạy nền (dừng hiệu ứng khi khuất ⇒ đỡ tốn pin, nhất là trong app). */
function useOnScreen<T extends Element>() {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(true);
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const el = ref.current;
    const io = el ? new IntersectionObserver(([e]) => setInView(e.isIntersecting)) : null;
    if (el && io) io.observe(el);
    const onVis = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVis);
    return () => {
      io?.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);
  return [ref, inView && visible] as const;
}

export function StageLights() {
  const still = useReducedMotion();
  const [ref, active] = useOnScreen<HTMLSpanElement>();
  const svg = useRef<SVGSVGElement>(null);
  // Khuất màn hình / chạy nền ⇒ tạm dừng (SVG giữ nguyên vị trí, chạy tiếp từ chỗ dừng khi quay lại)
  useEffect(() => {
    if (active) svg.current?.unpauseAnimations();
    else svg.current?.pauseAnimations();
  }, [active]);
  return (
    // -top-56: đỉnh đèn nằm trên mép banner (banner cắt phần thừa) ⇒ luồng sáng sát mép trên, không hở dải xanh.
    // Tạm dừng: dừng cả animation CSS của các lớp con (quầng thở, đổi màu, lấp lánh)
    <span ref={ref} aria-hidden className={cn("pointer-events-none absolute inset-x-0 -top-56 bottom-0", !active && "[&_*]:[animation-play-state:paused]")}>
      {/* Quầng ombre mờ (như mẫu): đỉnh ánh trắng nhẹ, quanh hạng 1 ánh vàng ô liu ấm → xanh rêu đậm ở các góc */}
      <span className="absolute inset-x-0 top-0 bottom-0 bg-[radial-gradient(ellipse_30%_35%_at_50%_22%,color-mix(in_srgb,var(--surface)_3%,transparent),transparent_70%)]" />
      <span className="absolute inset-x-0 top-1/4 bottom-0 animate-spot-breathe bg-[radial-gradient(ellipse_40%_55%_at_50%_50%,color-mix(in_srgb,color-mix(in_srgb,var(--cta)_35%,var(--primary))_20%,transparent),color-mix(in_srgb,color-mix(in_srgb,var(--cta)_35%,var(--primary))_7%,transparent)_50%,transparent_78%)]" />
      {/* Điện thoại bỏ blur (nặng với máy yếu, nhìn gần như không khác); từ sm làm nhoè mép luồng */}
      <svg ref={svg} viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-y-0 left-1/2 h-full w-full max-w-xs -translate-x-1/2 overflow-visible sm:max-w-2xl sm:blur-[3px]">
        <defs>
          <linearGradient id="beam-fill" x1="0" y1="0" x2="0" y2="1">
            {OMBRE.map(([o, c, a], i) => (
              <stop key={o} offset={o} stopColor={c} stopOpacity={a} className={SHIMMER[i]} />
            ))}
          </linearGradient>
          <linearGradient id="beam-edge" x1="0" y1="0" x2="0" y2="1">
            {/* Line mép: cùng ombre nhưng mờ hơn ruột luồng, tan sớm hơn */}
            {OMBRE.map(([o, c, a], i) => (
              <stop key={o} offset={o * 0.8} stopColor={c} stopOpacity={a * 0.5} className={i === 1 ? SHIMMER[1] : undefined} />
            ))}
          </linearGradient>
        </defs>
        {BEAMS.map(({ id, shots }) => {
          // Mép trái = trên-trái → dưới-trái; mép phải = trên-phải → dưới-phải
          const left = (e: Edges) => pts([e[0], e[3]]);
          const right = (e: Edges) => pts([e[1], e[2]]);
          return (
            <g key={id}>
              {still ? null : <Pulse />}
              <polygon points={pts(shots[0])} fill="url(#beam-fill)">
                {still ? null : <Morph shapes={shots.map(pts)} />}
              </polygon>
              {/* Hai mép của luồng (nét không giãn theo khung) */}
              <polyline points={left(shots[0])} fill="none" stroke="url(#beam-edge)" strokeWidth="1" vectorEffect="non-scaling-stroke">
                {still ? null : <Morph shapes={shots.map(left)} />}
              </polyline>
              <polyline points={right(shots[0])} fill="none" stroke="url(#beam-edge)" strokeWidth="1" vectorEffect="non-scaling-stroke">
                {still ? null : <Morph shapes={shots.map(right)} />}
              </polyline>
            </g>
          );
        })}
      </svg>
    </span>
  );
}
