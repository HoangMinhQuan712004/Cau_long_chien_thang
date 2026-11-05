"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { RecordFormDialog } from "@/components/records/record-form-dialog";
import { type MemberRecordVideo, type MineRecord, getMemberVideos, getMineRecords, sendMemberWithdrawRecord, type VideoPeriod } from "@/components/records/requests";
import { VideoPlayer } from "@/components/records/video-player";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatDate, formatDateTime } from "@/lib/format";
import { PageBanner } from "./page-banner";

// /hoi-vien/video-ky-luc (T-046 + T-047): video kỷ lục do Admin gắn, lọc theo kỳ; "Của tôi" = số đo mình đã gửi (Chờ duyệt / Bị từ chối).
// Tên theo quy tắc ẩn danh T-030 (server quyết định).

const PERIODS: { key: VideoPeriod; label: string }[] = [
  { key: "week", label: "Tuần" },
  { key: "month", label: "Tháng" },
  { key: "year", label: "Năm" },
  { key: "all", label: "Mọi thời gian" },
];

type View = "all" | "mine";

const chip = (on: boolean) => cn("h-11 shrink-0 rounded-full border px-5 text-sm font-semibold whitespace-nowrap focus-ring sm:h-10", on ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer");

export function VideoScreen() {
  const [view, setView] = useState<View>("all");
  const [period, setPeriod] = useState<VideoPeriod>("all");
  const [items, setItems] = useState<MemberRecordVideo[] | null>(null);
  const [error, setError] = useState("");
  const [mine, setMine] = useState<MineRecord[] | null>(null);
  const [mineError, setMineError] = useState("");
  const [submitOpen, setSubmitOpen] = useState(false);
  const [withdraw, setWithdraw] = useState<MineRecord | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (p: VideoPeriod) => {
    const n = ++seq.current;
    setItems(null);
    setError("");
    const res = await getMemberVideos(p);
    if (n !== seq.current) return; // chỉ nhận kết quả của lần gọi mới nhất
    if (res.ok) setItems(res.data.items);
    else setError(errorText(res.error));
  }, []);

  const loadMine = useCallback(async () => {
    const res = await getMineRecords();
    if (res.ok) {
      setMine(res.data);
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

  return (
    <>
      <PageBanner title="Video & kỷ lục" subtitle="Cú cầu nhanh nhất cụm sân · video chỉ đăng khi có kỷ lục mới" />
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-2" role="tablist" aria-label="Danh sách video">
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

        {view === "all" ? (
          <>
            <div className="-mx-4 mt-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0" role="group" aria-label="Kỳ kỷ lục">
              {PERIODS.map((p) => (
                <button key={p.key} type="button" aria-pressed={period === p.key} onClick={() => setPeriod(p.key)} className={chip(period === p.key)}>
                  {p.label}
                </button>
              ))}
            </div>

            {error ? (
              <div role="alert" className="mt-5 space-y-2 rounded-xl bg-surface px-6 py-10 text-center text-sm shadow-card">
                <p className="text-danger">{error}</p>
                <button type="button" onClick={() => void load(period)} className="h-10 rounded-lg border border-border-strong px-4 font-semibold hover:bg-primary-softer focus-ring">
                  Thử lại
                </button>
              </div>
            ) : items === null ? (
              <p className="mt-5 py-16 text-center text-muted" aria-busy>
                Đang tải…
              </p>
            ) : items.length === 0 ? (
              <div className="mt-5 grid place-items-center rounded-xl bg-surface px-6 py-16 text-center shadow-card">
                <svg viewBox="0 0 48 48" className="size-12 text-subtle" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <rect x="5" y="12" width="28" height="24" rx="4" />
                  <path d="m33 21 10-6v18l-10-6M6 6l36 36" />
                </svg>
                <h2 className="mt-4 text-lg font-bold">Chưa có video</h2>
                <p className="mt-1 max-w-sm text-sm text-muted">{period === "all" ? "Video sẽ hiện ở đây khi cụm sân gắn video cho kỷ lục." : "Chưa có video nào trong kỳ này. Thử chọn kỳ dài hơn."}</p>
              </div>
            ) : (
              <ul className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((r) => {
                  const title = `${r.speed_kmh} km/h · ${r.display_name}`;
                  return (
                    <li key={`${r.measured_at}-${r.speed_kmh}-${r.display_name}`} className="space-y-3 rounded-xl bg-surface p-3 shadow-card">
                      <VideoPlayer video={r.video} title={title} />
                      <div className="space-y-1 px-1 pb-1">
                        <p className="flex items-baseline justify-between gap-2">
                          <b className="text-xl tabular-nums">{r.speed_kmh} km/h</b>
                          <span className="text-xs text-muted tabular-nums">{formatDate(r.measured_at)}</span>
                        </p>
                        <p className="flex items-center gap-2 text-sm font-semibold">
                          <Avatar url={r.avatar_url} name={r.display_name} size={22} />
                          <span className="truncate">{r.display_name}</span>
                          {r.is_me ? <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">Bạn</span> : null}
                        </p>
                        {r.resource_name ? <p className="truncate text-xs text-muted">{r.resource_name}</p> : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        ) : (
          <MineList mine={mine} error={mineError} onRetry={() => void loadMine()} onWithdraw={setWithdraw} onSubmit={() => setSubmitOpen(true)} />
        )}
      </div>

      {submitOpen ? (
        <RecordFormDialog
          mode={{ kind: "member-submit" }}
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
      <div role="alert" className="mt-5 space-y-2 rounded-xl bg-surface px-6 py-10 text-center text-sm shadow-card">
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
      <div className="mt-5 grid place-items-center rounded-xl bg-surface px-6 py-16 text-center shadow-card">
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
          <li key={r.id} className="flex flex-col gap-3 rounded-xl bg-surface p-3 shadow-card sm:flex-row sm:items-center">
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
            {r.status === "pending" ? (
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
