"use client";

import { useEffect, useId, useState } from "react";
import { formatPhone, normalizePhone } from "@/lib/phone";
import { searchMembers } from "./requests";
import type { CustomerPayload, MemberHit } from "./types";
import { inputCls } from "./ui";

// Bộ chọn khách dùng chung (Đặt sân / Đăng ký vé): Hồ sơ hội viên (tìm theo mã / tên / SĐT) hoặc Hồ sơ tạm.
// Client chỉ gửi mã hội viên hoặc thông tin hồ sơ tạm; server tự dựng snapshot (ADR-004 S8).

export type CustomerState = {
  mode: "member" | "temp";
  q: string;
  picked: MemberHit | null;
  name: string;
  phone: string;
  note: string;
};

export const emptyCustomer: CustomerState = { mode: "member", q: "", picked: null, name: "", phone: "", note: "" };

export type CustomerErrors = { pick?: string; name?: string; phone?: string };

export function customerErrors(s: CustomerState): CustomerErrors {
  if (s.mode === "member") return s.picked ? {} : { pick: "Vui lòng chọn một hội viên." };
  const e: CustomerErrors = {};
  if (!s.name.trim()) e.name = "Vui lòng nhập Họ tên.";
  else if (s.name.trim().length > 100) e.name = "Họ tên tối đa 100 ký tự.";
  const phone = normalizePhone(s.phone);
  if (!phone) e.phone = "Vui lòng nhập SĐT.";
  else if (!/^0\d{9}$/.test(phone)) e.phone = "Số điện thoại không hợp lệ.";
  return e;
}

/** Dữ liệu gửi server; null khi chưa chọn hội viên (gọi `customerErrors` trước). */
export function customerPayload(s: CustomerState): CustomerPayload | null {
  if (s.mode === "member") return s.picked ? { member_code: s.picked.member_code } : null;
  const note = s.note.trim();
  return { temp: { full_name: s.name.trim(), phone: normalizePhone(s.phone), ...(note ? { note } : {}) } };
}

type Props = {
  state: CustomerState;
  onChange: (next: CustomerState) => void;
  /** Hiện lỗi cho các ô chưa chạm (sau khi bấm nút gửi). */
  submitted: boolean;
  /** Lỗi từ server gắn vào ô tương ứng. */
  serverErrors?: CustomerErrors;
  /** Admin: thêm tab "Đặt sự kiện" (chỉ ở popup Đặt sân). */
  onPickSession?: () => void;
};

export function CustomerPicker({ state, onChange, submitted, serverErrors, onPickSession }: Props) {
  const ids = { q: useId(), name: useId(), phone: useId(), note: useId() };
  const [hits, setHits] = useState<MemberHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [touched, setTouched] = useState<{ name?: boolean; phone?: boolean }>({});
  const errors = { ...customerErrors(state), ...serverErrors };
  const set = (p: Partial<CustomerState>) => onChange({ ...state, ...p });

  // Tìm hội viên sau 250 ms ngừng gõ
  const q = state.q.trim();
  const searching = state.mode === "member" && q !== "";
  useEffect(() => {
    if (!searching) return;
    let live = true;
    const t = setTimeout(async () => {
      setLoading(true);
      const res = await searchMembers(q);
      if (!live) return;
      setLoading(false);
      if (res.ok) {
        setHits(res.data);
        setSearched(true);
        setSearchError("");
      } else {
        setSearchError(res.error.message);
      }
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
      setLoading(false);
    };
  }, [q, searching]);

  const shownHits = searching ? hits : [];
  const noResult = searching && searched && !loading && !hits.length && !searchError;

  const tab = (active: boolean) =>
    `flex-1 rounded-md px-3 py-1.5 text-sm font-medium ${active ? "bg-surface text-foreground shadow-sm" : "text-muted hover:text-foreground"}`;

  return (
    <div className="space-y-3">
      <div role="tablist" aria-label="Loại hồ sơ khách" className="flex gap-1 rounded-lg bg-background p-1">
        <button type="button" role="tab" aria-selected={state.mode === "member"} onClick={() => set({ mode: "member" })} className={tab(state.mode === "member")}>
          Hồ sơ hội viên
        </button>
        <button type="button" role="tab" aria-selected={state.mode === "temp"} onClick={() => set({ mode: "temp" })} className={tab(state.mode === "temp")}>
          Hồ sơ tạm
        </button>
        {onPickSession ? (
          <button type="button" role="tab" aria-selected={false} onClick={onPickSession} className={tab(false)}>
            Đặt sự kiện
          </button>
        ) : null}
      </div>

      {state.mode === "member" ? (
        <div className="space-y-2">
          <label htmlFor={ids.q} className="sr-only">
            Tìm hội viên theo mã, tên hoặc số điện thoại
          </label>
          <input
            id={ids.q}
            value={state.q}
            maxLength={50}
            placeholder="Nhập mã / tên / SĐT hội viên..."
            onChange={(e) => set({ q: e.target.value, picked: null })}
            aria-invalid={noResult || undefined}
            className={inputCls}
          />
          {searchError ? <p className="text-xs text-danger">{searchError}</p> : null}
          {noResult ? (
            <p role="alert" className="text-xs text-danger">
              Không tìm thấy hội viên. Kiểm tra lại hoặc chọn Hồ sơ tạm.
            </p>
          ) : null}
          {shownHits.length ? (
            <div className="max-h-56 overflow-y-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted">
                  <tr className="border-b border-border">
                    <th className="px-3 py-1.5 text-left font-medium">Mã HV</th>
                    <th className="px-3 py-1.5 text-left font-medium">Tên</th>
                    <th className="px-3 py-1.5 text-left font-medium">Hạng</th>
                    <th className="px-3 py-1.5 text-center font-medium">Chọn</th>
                  </tr>
                </thead>
                <tbody>
                  {shownHits.map((m) => {
                    const on = state.picked?.ref === m.ref;
                    return (
                      <tr
                        key={m.ref}
                        onClick={() => set({ picked: m })}
                        className={`cursor-pointer border-b border-border last:border-0 ${on ? "bg-primary-softer" : "hover:bg-primary-softer"}`}
                      >
                        <td className="px-3 py-2 font-mono text-xs">{m.member_code}</td>
                        <td className="px-3 py-2">
                          {m.name}
                          {m.is_active ? null : <span className="ml-1.5 rounded bg-blk-bad px-1.5 text-xs text-blk-bad-fg">Ngừng</span>}
                          <span className="block text-xs text-muted tabular-nums">{formatPhone(m.phone)}</span>
                        </td>
                        <td className="px-3 py-2">{m.tier ?? "—"}</td>
                        <td className="px-3 py-2 text-center">
                          <input type="radio" name="member-pick" checked={on} onChange={() => set({ picked: m })} aria-label={`Chọn ${m.name}`} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
          {submitted && errors.pick && !state.picked ? <p className="text-xs text-danger">{errors.pick}</p> : null}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
                Họ tên <span className="text-danger">*</span>
              </label>
              <input
                id={ids.name}
                value={state.name}
                maxLength={100}
                placeholder="Nhập họ tên khách"
                onChange={(e) => set({ name: e.target.value })}
                onBlur={() => setTouched((t) => ({ ...t, name: true }))}
                aria-invalid={Boolean((submitted || touched.name) && errors.name) || undefined}
                className={inputCls}
              />
              {(submitted || touched.name) && errors.name ? <p className="mt-1 text-xs text-danger">{errors.name}</p> : null}
            </div>
            <div>
              <label htmlFor={ids.phone} className="mb-1 block text-sm font-medium">
                SĐT <span className="text-danger">*</span>
              </label>
              <input
                id={ids.phone}
                value={state.phone}
                inputMode="tel"
                maxLength={13}
                placeholder="VD: 0987 654 321"
                onChange={(e) => set({ phone: e.target.value })}
                onBlur={() => setTouched((t) => ({ ...t, phone: true }))}
                aria-invalid={Boolean((submitted || touched.phone) && errors.phone) || undefined}
                className={inputCls}
              />
              {(submitted || touched.phone) && errors.phone ? <p className="mt-1 text-xs text-danger">{errors.phone}</p> : null}
            </div>
          </div>
          <div>
            <label htmlFor={ids.note} className="mb-1 block text-sm font-medium">
              Ghi chú
            </label>
            <textarea
              id={ids.note}
              value={state.note}
              maxLength={500}
              placeholder="Không bắt buộc"
              onChange={(e) => set({ note: e.target.value })}
              className={`${inputCls} min-h-16`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
