"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { usePolling } from "@/hooks/use-polling";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";
import { FORMAT_LABEL, MAX_MEMBERS } from "../types";
import { hourRange, tierRangeText } from "../utils";
import { personMeta, personName, teamNames } from "./person";
import { getMonitorRoom } from "./requests";
import { Score } from "./score";
import { isLive, QUEUE_LABEL, STATUS_LABEL, STATUS_VARIANT } from "./status";
import type { MonitorRoomDetail } from "./types";

// Chi tiết phòng CHỈ ĐỌC (T-069 AC5): thành viên, mọi trận kèm tỉ số, bảng xếp hạng. Không có nút ghi.

export type MonitorTarget = { id: number; courtName: string };

export function RoomDetailDialog({ target, live, onClose }: { target: MonitorTarget | null; live: boolean; onClose: () => void }) {
  const [data, setData] = useState<{ id: number; detail: MonitorRoomDetail } | null>(null);
  const [error, setError] = useState<{ id: number; text: string } | null>(null);
  const seq = useRef(0);
  const id = target?.id;

  const load = useCallback(async () => {
    if (id === undefined) return;
    const mine = ++seq.current;
    const res = await getMonitorRoom(id);
    if (mine !== seq.current) return; // chỉ nhận kết quả của lần gọi mới nhất
    if (res.ok) {
      setData({ id, detail: res.data });
      setError(null);
    } else setError({ id, text: res.error.status === 404 ? "Không còn tìm thấy phòng này." : errorText(res.error) });
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi mở phòng khác
    void load();
  }, [load]);
  // Phòng hôm nay: tải lại cùng nhịp với lưới (10 giây)
  usePolling(() => {
    if (id !== undefined && live) void load();
  }, 10_000);

  const detail = data && data.id === id ? data.detail : null;
  const err = error && error.id === id ? error.text : "";
  const room = detail?.room;

  return (
    <Modal
      open={target !== null}
      onClose={onClose}
      size="large"
      title={room ? `Phòng ${room.booking_code}` : "Chi tiết phòng"}
      subtitle={room && target ? `${target.courtName} · ${hourRange(room.start_at, room.end_at)}` : undefined}
    >
      {err ? (
        <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
          {err}
        </p>
      ) : !detail || !room ? (
        <p className="py-8 text-center text-muted" aria-busy>
          Đang tải…
        </p>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant={STATUS_VARIANT[room.status]}>{STATUS_LABEL[room.status]}</Badge>
            <span className="rounded-full bg-background px-2.5 py-0.5 text-xs ring-1 ring-border">{FORMAT_LABEL[room.format]}</span>
            <span className="rounded-full bg-background px-2.5 py-0.5 text-xs ring-1 ring-border">{tierRangeText({ min: room.min_tier, max: room.max_tier }) ?? "Không có hạng"}</span>
            <span className="text-muted">
              Host: <b className="font-semibold text-foreground">{personName(room.host)}</b>
            </span>
          </div>

          <section aria-labelledby="mon-members">
            <h3 id="mon-members" className="text-sm font-bold">
              Thành viên{" "}
              <span className="font-normal text-muted tabular-nums">
                ({detail.members.length}/{MAX_MEMBERS})
              </span>
            </h3>
            {detail.members.length === 0 ? (
              <p className="mt-2 text-sm text-muted">Phòng chưa có thành viên.</p>
            ) : (
              <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                {detail.members.map((m) => (
                  <li key={m.customer_id} className="flex items-center gap-3 rounded-lg border border-border px-3 py-2">
                    <Avatar url={m.avatar_url} name={m.nickname || m.full_name} size={36} />
                    <span className="min-w-0 flex-1">
                      <b className="block truncate text-sm">{personName(m)}</b>
                      <span className="block truncate text-xs text-muted">{personMeta(m) || "Chưa có mã HV"}</span>
                    </span>
                    {m.role === "host" ? <Badge variant="warning">Host</Badge> : null}
                    <Badge variant={m.queue_state === "playing" ? "success" : "neutral"}>{QUEUE_LABEL[m.queue_state]}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="mon-matches">
            <h3 id="mon-matches" className="text-sm font-bold">
              Các trận <span className="font-normal text-muted tabular-nums">({detail.matches.length})</span>
            </h3>
            <div className="relative mt-2 overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[34rem] text-left text-sm">
                <thead className="text-muted">
                  <tr className="border-b border-border">
                    <th className="px-3 py-2 font-medium">Trận</th>
                    <th className="px-3 py-2 font-medium">Đội A</th>
                    <th className="px-3 py-2 text-center font-medium">Tỉ số</th>
                    <th className="px-3 py-2 font-medium">Đội B</th>
                    <th className="px-3 py-2 font-medium">Giờ</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.matches.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-3 py-6 text-center text-muted">
                        Chưa có trận nào.
                      </td>
                    </tr>
                  ) : (
                    detail.matches.map((m) => (
                      <tr key={m.no} className="border-b border-border last:border-0">
                        <td className="px-3 py-2 font-semibold">#{m.no}</td>
                        <td className="px-3 py-2">{teamNames(m.team_a)}</td>
                        <td className="px-3 py-2 text-center">{isLive(m) ? <span className="text-xs font-bold text-primary">Đang đánh</span> : <Score m={m} />}</td>
                        <td className="px-3 py-2">{teamNames(m.team_b)}</td>
                        <td className="px-3 py-2 text-xs whitespace-nowrap text-muted tabular-nums">{m.ended_at ? formatTime(m.ended_at) : m.started_at ? `từ ${formatTime(m.started_at)}` : "–"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section aria-labelledby="mon-ranking">
            <h3 id="mon-ranking" className="text-sm font-bold">
              Bảng xếp hạng phòng
            </h3>
            <div className="relative mt-2 overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[26rem] text-left text-sm">
                <thead className="text-muted">
                  <tr className="border-b border-border">
                    <th className="px-3 py-2 font-medium">Hạng</th>
                    <th className="px-3 py-2 font-medium">Người chơi</th>
                    <th className="px-3 py-2 text-right font-medium">Thắng</th>
                    <th className="px-3 py-2 text-right font-medium">Thua</th>
                    <th className="px-3 py-2 text-right font-medium">Tỉ lệ</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.ranking.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-3 py-6 text-center text-muted">
                        Chưa có trận nào được lưu.
                      </td>
                    </tr>
                  ) : (
                    detail.ranking.map((r) => (
                      <tr key={r.customer_id} className="border-b border-border last:border-0">
                        <td className={cn("px-3 py-2 font-semibold tabular-nums", r.rank === 1 && "text-accent-fg")}>{r.rank}</td>
                        <td className="px-3 py-2">
                          <b className="block font-medium">{personName(r)}</b>
                          <span className="block text-xs text-muted">{personMeta(r)}</span>
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{r.wins}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{r.losses}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{Math.round(r.win_rate * 100)}%</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </Modal>
  );
}
