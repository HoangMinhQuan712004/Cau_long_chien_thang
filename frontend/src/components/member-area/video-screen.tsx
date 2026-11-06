"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BreakTimeline, RecordCard } from "@/components/member-area/record-breaks";
import { RecordFormDialog } from "@/components/records/record-form-dialog";
import { RecordPlayer } from "@/components/records/record-player";
import { getMineRecords, getRecordBreaks, type MineRecord, type RecordBreakItem, sendMemberWithdrawRecord, type VideoPeriod } from "@/components/records/requests";
import { VideoPlayer } from "@/components/records/video-player";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatDateTime } from "@/lib/format";
import { PageBanner } from "./page-banner";

// /hoi-vien/video-ky-luc (T-048, thay AC4 của T-046; giữ "Của tôi" + "Gửi cú đập" của T-047):
// vùng banner = trình phát + thẻ kỷ lục của lần đang chọn, bên dưới là dòng thời gian "Các lần phá kỷ lục".
// Tên / biệt danh / trình độ / vợt theo quy tắc ẩn danh T-030 (server quyết định).

const PERIODS: { key: VideoPeriod; label: string }[] = [
  { key: "week", label: "Tuần" },
  { key: "month", label: "Tháng" },
  { key: "year", label: "Năm" },
  { key: "all", label: "Mọi thời gian" },
];

type View = "all" | "mine";

const chip = (on: boolean) => cn("h-11 shrink-0 rounded-full border px-5 text-sm font-semibold whitespace-nowrap focus-ring sm:h-10", on ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer");
const seg = (on: boolean) => cn("h-11 shrink-0 rounded-full px-4 text-sm font-semibold whitespace-nowrap focus-ring-inverse sm:h-9", on ? "bg-surface text-primary-hover" : "text-surface hover:bg-surface/15");

export function VideoScreen() {
  const [view, setView] = useState<View>("all");
  const [period, setPeriod] = useState<VideoPeriod>("all");
  const [items, setItems] = useState<RecordBreakItem[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | undefined>();
  const [error, setError] = useState("");
  const [mine, setMine] = useState<MineRecord[] | null>(null);
  const [courts, setCourts] = useState<{ code: string; name: string }[]>([]);
  const [dailyLimit, setDailyLimit] = useState(5);
  const [mineError, setMineError] = useState("");
  const [submitOpen, setSubmitOpen] = useState(false);
  const [withdraw, setWithdraw] = useState<MineRecord | null>(null);
  const seq = useRef(0);
  const stage = useRef<HTMLDivElement>(null);

  const load = useCallback(async (p: VideoPeriod) => {
    const n = ++seq.current;
    setItems(null);
    setSelectedId(undefined); // đổi kỳ thì chọn lại lần mới nhất của kỳ đó (AC8)
    setError("");
    const res = await getRecordBreaks(p);
    if (n !== seq.current) return; // chỉ nhận kết quả của lần gọi mới nhất
    if (res.ok) setItems(res.data.items);
    else setError(errorText(res.error));
  }, []);

  const loadMine = useCallback(async () => {
    const res = await getMineRecords();
    if (res.ok) {
      setMine(res.data.items);
      setCourts(res.data.resources);
      setDailyLimit(res.data.daily_limit);
      setMineError("");
    } else setMineError(errorText(res.error));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải lại khi đổi kỳ
    void load(period);
  }, [load, period]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải số đo của tôi một lần khi vào màn
    void loadMine();
  }, [loadMine]);

  const waiting = mine?.filter((r) => r.status === "pending").length ?? 0;
  const selected = items?.find((r) => r.id === selectedId) ?? items?.[0];
  const breaks = items?.filter((r) => !r.is_baseline).length ?? 0; // dòng phụ không tính mốc đầu

  function pick(r: RecordBreakItem) {
    setSelectedId(r.id); // không tự phát: trình phát dựng lại theo `key`, video cũ dừng
    if (window.matchMedia("(max-width: 1023px)").matches) {
      const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      stage.current?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
    }
  }

  return (
    <>
      <PageBanner
        title="Video & kỷ lục"
        subtitle="Cú cầu nhanh nhất cụm sân · video chỉ đăng khi có kỷ lục mới"
        aside={
          <div className="flex max-w-full gap-1 overflow-x-auto rounded-full bg-surface/10 p-1" role="group" aria-label="Kỳ kỷ lục">
            {PERIODS.map((p) => (
              <button key={p.key} type="button" aria-pressed={period === p.key} onClick={() => setPeriod(p.key)} className={seg(period === p.key)}>
                {p.label}
              </button>
            ))}
          </div>
        }
      >
        <div ref={stage} className="relative mx-auto max-w-6xl scroll-mt-20 px-4 pb-6 sm:pb-8">
          {error ? (
            <div role="alert" className="space-y-2 rounded-2xl bg-surface/10 px-6 py-10 text-center text-sm">
              <p>{error}</p>
              <button type="button" onClick={() => void load(period)} className="h-11 rounded-lg border border-surface/60 px-4 font-semibold hover:bg-surface/15 focus-ring-inverse">
                Thử lại
              </button>
            </div>
          ) : items === null ? (
            <p className="py-16 text-center text-surface/80" aria-busy>
              Đang tải…
            </p>
          ) : !selected ? (
            <div className="grid place-items-center rounded-2xl bg-surface/10 px-6 py-14 text-center">
              <h2 className="text-lg font-bold">{period === "all" ? "Chưa có kỷ lục nào" : "Chưa có lần phá kỷ lục trong kỳ này"}</h2>
              <p className="mt-1 max-w-sm text-sm text-surface/80">{period === "all" ? "Kỷ lục sẽ hiện ở đây khi cụm sân ghi nhận cú đập đầu tiên." : "Thử chọn kỳ dài hơn."}</p>
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
              <RecordPlayer key={selected.id} video={selected.video} speed={selected.speed_kmh} name={selected.display_name} />
              <RecordCard item={selected} />
            </div>
          )}
        </div>
      </PageBanner>

      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <section className="rounded-2xl bg-surface p-4 shadow-card sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold">{view === "all" ? "Các lần phá kỷ lục" : "Của tôi"}</h2>
              <p className="text-sm text-muted">{view === "all" ? (items ? `${breaks} lần · mới nhất ở trên · bấm một dòng để xem video` : "") : "Số đo bạn đã gửi, kể cả bản đang chờ duyệt"}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex gap-2" role="tablist" aria-label="Danh sách">
                <button type="button" role="tab" aria-selected={view === "all"} onClick={() => setView("all")} className={chip(view === "all")}>
                  Video kỷ lục
                </button>
                <button type="button" role="tab" aria-selected={view === "mine"} onClick={() => setView("mine")} className={chip(view === "mine")}>
                  Của tôi{mine ? ` (${mine.length})` : ""}
                  {waiting > 0 ? <span className="ml-1.5 rounded-full bg-cta px-1.5 py-0.5 text-xs text-cta-fg">{waiting} chờ duyệt</span> : null}
                </button>
              </div>
              <Button variant="cta" onClick={() => setSubmitOpen(true)} className="h-11 px-5 text-sm">
                Gửi cú đập
              </Button>
            </div>
          </div>

          {view === "all" ? (
            items && items.length > 0 ? (
              <BreakTimeline items={items} selectedId={selected?.id} onSelect={pick} />
            ) : null
          ) : (
            <MineList mine={mine} error={mineError} onRetry={() => void loadMine()} onWithdraw={setWithdraw} onSubmit={() => setSubmitOpen(true)} />
          )}
        </section>
      </div>

      {submitOpen ? (
        <RecordFormDialog
          mode={{ kind: "member-submit" }}
          courts={courts}
          dailyLimit={dailyLimit}
          onClose={() => setSubmitOpen(false)}
          onDone={() => {
            setSubmitOpen(false);
            setView("mine");
            void loadMine();
          }}
        />
      ) : null}
      {withdraw ? (
        <WithdrawDialog
          record={withdraw}
          onClose={() => setWithdraw(null)}
          onDone={() => {
            setWithdraw(null);
            void loadMine();
          }}
        />
      ) : null}
    </>
  );
}

const STATUS_STYLE = {
  approved: { label: "Đã duyệt", cls: "bg-primary-softer text-primary" },
  pending: { label: "Chờ duyệt", cls: "bg-cta text-cta-fg" },
  rejected: { label: "Bị từ chối", cls: "bg-danger text-surface" },
} as const;

function MineList({ mine, error, onRetry, onWithdraw, onSubmit }: { mine: MineRecord[] | null; error: string; onRetry: () => void; onWithdraw: (r: MineRecord) => void; onSubmit: () => void }) {
  if (error)
    return (
      <div role="alert" className="mt-5 space-y-2 px-6 py-10 text-center text-sm">
        <p className="text-danger">{error}</p>
        <button type="button" onClick={onRetry} className="h-10 rounded-lg border border-border-strong px-4 font-semibold hover:bg-primary-softer focus-ring">
          Thử lại
        </button>
      </div>
    );
  if (mine === null)
    return (
      <p className="mt-5 py-16 text-center text-muted" aria-busy>
        Đang tải…
      </p>
    );
  if (mine.length === 0)
    return (
      <div className="mt-5 grid place-items-center px-6 py-16 text-center">
        <h2 className="text-lg font-bold">Bạn chưa gửi cú đập nào</h2>
        <p className="mt-1 max-w-sm text-sm text-muted">Gửi tốc độ và link video, Admin duyệt xong sẽ tính vào bảng xếp hạng.</p>
        <Button variant="secondary" onClick={onSubmit} className="mt-4 h-11 px-5 text-sm">
          Gửi cú đập
        </Button>
      </div>
    );
  return (
    <ul className="mt-5 space-y-3">
      {mine.map((r) => {
        const st = STATUS_STYLE[r.status];
        return (
          <li key={r.id} className="flex flex-col gap-3 rounded-xl border p-3 sm:flex-row sm:items-center">
            {r.video ? <VideoPlayer video={r.video} title={`${r.speed_kmh} km/h`} className="sm:w-56 sm:shrink-0" /> : null}
            <div className="min-w-0 flex-1 space-y-1 px-1">
              <p className="flex flex-wrap items-baseline gap-2">
                <b className="text-xl tabular-nums">{r.speed_kmh} km/h</b>
                <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", st.cls)}>{st.label}</span>
              </p>
              <p className="text-xs text-muted tabular-nums">
                {formatDateTime(r.measured_at)}
                {r.resource_name ? ` · ${r.resource_name}` : ""}
              </p>
              {r.status === "rejected" ? <p className="text-sm text-danger">Bị từ chối{r.reject_reason ? `: ${r.reject_reason}` : ""}</p> : null}
              {r.status === "pending" ? <p className="text-xs text-muted">Đang chờ Admin duyệt, chưa tính vào bảng xếp hạng.</p> : null}
            </div>
            {r.can_withdraw ? (
              <Button variant="secondary" onClick={() => onWithdraw(r)} className="h-11 px-4 text-sm sm:h-10">
                Rút lại
              </Button>
            ) : null}
            {r.status === "rejected" ? (
              <Button variant="secondary" onClick={onSubmit} className="h-11 px-4 text-sm sm:h-10">
                Gửi bản mới
              </Button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/** Rút lại số đo đang chờ duyệt (xóa hẳn bản đã gửi). */
function WithdrawDialog({ record, onClose, onDone }: { record: MineRecord; onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  async function go() {
    if (busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendMemberWithdrawRecord(key, record.id));
      if (!res.ok) {
        setBanner(errorText(res.error));
        return;
      }
      toast("Đã rút lại số đo", `${record.speed_kmh} km/h`);
      onDone();
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      onClose={onClose}
      title="Rút lại cú đập?"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy} className="h-11 px-4 text-sm">
            Giữ lại
          </Button>
          <Button variant="danger" onClick={() => void go()} loading={busy} className="h-11 px-4 text-sm">
            {busy ? "Đang rút…" : "Rút lại"}
          </Button>
        </>
      }
    >
      {banner ? (
        <p role="alert" className="text-sm text-danger">
          {banner}
        </p>
      ) : null}
      <p className="text-sm">
        Rút lại số đo <b>{record.speed_kmh} km/h</b> đang chờ duyệt. Bạn có thể gửi lại bản khác sau.
      </p>
    </Modal>
  );
}
