"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDateTime, formatVnd } from "@/lib/format";
import { getBankTransactions, sendResolve } from "./requests";
import type { BankTransaction } from "./types";

// /admin/tien-ve (chỉ Admin): giao dịch ngân hàng cần xử lý – không khớp mã, cần hoàn tiền, hoặc trả thừa (T-008 AC32).

const OUTCOME: Record<BankTransaction["outcome"], string> = {
  applied: "Trả thừa",
  partial: "Trả thiếu",
  refund_needed: "Cần hoàn tiền",
  unmatched: "Không khớp mã",
  ignored: "Bỏ qua",
};

export function BankTransactionsScreen({ initial }: { initial: BankTransaction[] }) {
  const router = useRouter();
  const [rows, setRows] = useState(initial);
  const [showAll, setShowAll] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [target, setTarget] = useState<BankTransaction | null>(null);

  async function reload(all: boolean) {
    setLoading(true);
    const res = await getBankTransactions(!all);
    setLoading(false);
    if (res.ok) {
      setRows(res.data);
      setError("");
    } else {
      setError(errorText(res.error));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Tiền về cần xử lý</h1>
        <label className="ml-auto flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => {
              setShowAll(e.target.checked);
              void reload(e.target.checked);
            }}
          />
          Hiện cả đã xử lý
        </label>
      </div>
      <p className="text-sm text-muted">
        Giao dịch chuyển khoản không khớp booking nào, đến sau khi hết giữ chỗ, hoặc khách chuyển thừa. Hoàn tiền thực hiện thủ công bên ngoài hệ thống; bấm “Đã xử lý” và ghi chú để đóng mục.
      </p>

      {error ? (
        <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <div className={`overflow-x-auto rounded-lg border border-border bg-surface ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
        <table className="w-full min-w-[56rem] text-left text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-b border-border">
              <th className="px-3 py-2 font-medium">Thời gian</th>
              <th className="px-3 py-2 text-right font-medium">Số tiền</th>
              <th className="px-3 py-2 font-medium">Nội dung CK</th>
              <th className="px-3 py-2 font-medium">Mã</th>
              <th className="px-3 py-2 font-medium">Loại</th>
              <th className="px-3 py-2 text-right font-medium">Cần hoàn</th>
              <th className="px-3 py-2 font-medium">Xử lý</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-muted">
                  Không có giao dịch nào cần xử lý.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0 align-top">
                  <td className="px-3 py-2.5">{formatDateTime(r.transaction_at)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{formatVnd(r.amount)}</td>
                  {/* Nội dung CK do người chuyển khoản nhập – hiển thị nguyên văn (React tự escape). */}
                  <td className="max-w-64 break-words px-3 py-2.5">{r.content}</td>
                  <td className="px-3 py-2.5 font-mono text-xs">{r.booking_codes.length ? r.booking_codes.join(", ") : (r.code ?? "—")}</td>
                  <td className="px-3 py-2.5">{OUTCOME[r.outcome]}</td>
                  <td className="px-3 py-2.5 text-right font-semibold tabular-nums">{r.refund_amount > 0 ? formatVnd(r.refund_amount) : "—"}</td>
                  <td className="px-3 py-2.5">
                    {r.resolved_at ? (
                      <span className="text-muted">
                        Đã xử lý {formatDateTime(r.resolved_at)}
                        {r.resolved_by_label ? ` · ${r.resolved_by_label}` : ""}
                        {r.note ? <span className="block">{r.note}</span> : null}
                      </span>
                    ) : (
                      <button type="button" onClick={() => setTarget(r)} className="rounded-md border border-border px-3 py-1 text-xs font-medium hover:bg-free">
                        Đã xử lý<span className="sr-only"> giao dịch {r.provider_txn_id}</span>
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {target ? (
        <ResolveDialog
          tx={target}
          onClose={() => setTarget(null)}
          onDone={() => {
            setTarget(null);
            void reload(showAll);
            router.refresh(); // cập nhật số đếm ở menu
          }}
        />
      ) : null}
    </div>
  );
}

function ResolveDialog({ tx, onClose, onDone }: { tx: BankTransaction; onClose: () => void; onDone: () => void }) {
  const noteId = useId();
  const [note, setNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const trimmed = note.trim();
  const err = !trimmed ? "Vui lòng nhập ghi chú." : trimmed.length > 500 ? "Ghi chú tối đa 500 ký tự." : "";

  async function submit() {
    setSubmitted(true);
    setBanner("");
    if (err) return;
    setBusy(true);
    try {
      const res = await write((key) => sendResolve(key, tx.id, trimmed));
      if (!res.ok) {
        // E-PAY-1: đã được xử lý ở máy khác → tải lại danh sách
        if (res.error.code === "E-PAY-1") {
          toast(errorText(res.error), undefined, "error");
          onDone();
          return;
        }
        setBanner(errorText(res.error));
        return;
      }
      toast("Đã đánh dấu đã xử lý.");
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Đánh dấu đã xử lý"
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className="rounded-md border border-border px-4 py-2 text-sm disabled:opacity-60">
            Hủy
          </button>
          <button type="button" onClick={submit} disabled={busy} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60">
            {busy ? "Đang lưu…" : "Đã xử lý"}
          </button>
        </>
      }
    >
      {banner ? (
        <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {banner}
        </p>
      ) : null}
      <div className="space-y-1 rounded-lg border border-border bg-background p-3 text-sm">
        <p className="font-semibold">
          {formatVnd(tx.amount)} · {OUTCOME[tx.outcome]}
        </p>
        <p className="break-words text-muted">{tx.content}</p>
        {tx.refund_amount > 0 ? <p>Cần hoàn: <b>{formatVnd(tx.refund_amount)}</b></p> : null}
      </div>
      <div>
        <label htmlFor={noteId} className="mb-1 block text-sm font-medium">
          Ghi chú <span className="text-danger">*</span>
        </label>
        <textarea
          id={noteId}
          value={note}
          maxLength={500}
          placeholder="Ví dụ: đã hoàn tiền cho khách qua chuyển khoản lúc 10:30"
          onChange={(e) => setNote(e.target.value)}
          aria-invalid={Boolean(submitted && err) || undefined}
          className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
        <div className="mt-1 flex text-xs">
          {submitted && err ? <span className="text-danger">{err}</span> : null}
          <span className="ml-auto text-muted">{note.length} / 500</span>
        </div>
      </div>
    </Modal>
  );
}
