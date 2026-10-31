"use client";

import { useEffect, useId, useRef, useState } from "react";
import { TIERS } from "@/app/admin/hoi-vien/_components/member-params";
import { RACKET_OTHER } from "@/app/admin/hoi-vien/_components/member-form-fields";
import { useRackets } from "@/app/admin/hoi-vien/_components/use-rackets";
import { Button } from "@/components/ui/button";
import { Dropdown } from "@/components/ui/dropdown";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { Avatar } from "./avatar";
import { CropDialog } from "./crop-dialog";
import { useMember } from "./member-shell";
import { deleteAvatar, getMe, putMe } from "./requests";
import { formatPhone, type MemberMe, NICKNAME_MAX } from "./types";

// /hoi-vien/ho-so (T-016 AC7–AC19): hero + hai thẻ; Lưu / Hủy mờ khi chưa sửa; lỗi dưới ô; E-006 / E-007 / E-010 / E-011.

const MAX_FILE = 5 * 1024 * 1024;
const FILE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function ProfileScreen() {
  const { me, setMe } = useMember();
  const [loadError, setLoadError] = useState(false);

  async function reload() {
    const res = await getMe();
    if (res.ok) {
      setMe(res.data);
      setLoadError(false);
    } else if (res.error.status === 401) {
      window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien/ho-so")}&ly-do=het-han`);
    } else setLoadError(true);
  }

  return (
    <>
      <Hero me={me} />
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        {loadError ? (
          <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card">
            <p className="font-semibold">Không tải được hồ sơ. Vui lòng thử lại.</p>
            <Button className="mt-4" onClick={() => void reload()}>
              Thử lại
            </Button>
          </div>
        ) : (
          // Tải lại / lưu xong ⇒ phiên bản mới ⇒ dựng form mới từ bản đã lưu
          <ProfileForm key={me.version} base={me} onReload={reload} />
        )}
      </div>
    </>
  );
}

function Hero({ me }: { me: MemberMe }) {
  const { setMe } = useMember();
  const [menu, setMenu] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  function pick(f: File | undefined) {
    // Menu 📷 luôn đóng khi đã có tệp (kể cả khi tệp được đưa vào ô chọn tệp mà không bấm mục menu)
    setMenu(false);
    if (!f) return;
    if (!FILE_TYPES.includes(f.type) || f.size > MAX_FILE) {
      toast("Ảnh phải là JPG, PNG hoặc WebP, tối đa 5 MB.", undefined, "error");
      return;
    }
    setFile(f);
  }

  async function remove() {
    if (busy) return;
    setBusy(true);
    setMenu(false);
    const res = await deleteAvatar();
    setBusy(false);
    if (!res.ok) {
      toast(errorText(res.error), undefined, "error");
      return;
    }
    // Chỉ đổi ảnh: không đụng phiên bản / các ô đang sửa
    setMe((m) => ({ ...m, avatar_url: null }));
    setConfirmDelete(false);
    toast("Đã xóa ảnh đại diện");
  }

  const joined = `${me.joined_at.slice(5, 7)}/${me.joined_at.slice(0, 4)}`;

  return (
    <section aria-label="Thông tin hội viên" className="relative overflow-hidden bg-primary-hover text-surface">
      <CourtLines />
      <div className="relative mx-auto flex max-w-6xl items-center gap-4 px-4 py-8 sm:gap-6 sm:py-10">
        <div className="relative shrink-0" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setMenu(false)}>
          <Avatar url={me.avatar_url} name={me.short_name} size={96} className="ring-4 ring-surface/25" />
          <button
            type="button"
            aria-label="Đổi ảnh đại diện"
            aria-haspopup="menu"
            aria-expanded={menu}
            onClick={() => setMenu((o) => !o)}
            onKeyDown={(e) => e.key === "Escape" && setMenu(false)}
            className="absolute right-0 bottom-0 grid size-8 place-items-center rounded-full bg-surface text-foreground shadow-card hover:bg-primary-softer focus-ring"
          >
            <svg viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
              <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h1.6l1-1.5h5.8l1 1.5h1.6A1.5 1.5 0 0 1 17 7.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5z" />
              <circle cx="10" cy="10.5" r="2.6" />
            </svg>
          </button>
          {menu ? (
            <div role="menu" className="absolute top-full left-0 z-20 mt-2 w-44 rounded-card bg-surface p-1.5 text-sm text-foreground shadow-card ring-1 ring-border">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  input.current?.click();
                }}
                className="w-full rounded-lg px-3 py-2 text-left hover:bg-primary-softer focus-ring"
              >
                Tải ảnh lên
              </button>
              {me.avatar_url ? (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenu(false);
                    setConfirmDelete(true);
                  }}
                  className="w-full rounded-lg px-3 py-2 text-left hover:bg-primary-softer hover:text-danger focus-ring"
                >
                  Xóa ảnh
                </button>
              ) : null}
            </div>
          ) : null}
          <input
            ref={input}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(e) => {
              pick(e.target.files?.[0]);
              e.target.value = ""; // chọn lại cùng tệp vẫn nhận
            }}
          />
        </div>

        <div className="min-w-0">
          <h1 className="text-xl font-bold break-words sm:text-2xl">{me.full_name}</h1>
          {me.nickname ? <p className="mt-0.5 text-sm text-surface/80">“{me.nickname}”</p> : null}
          <p className="mt-1 text-sm text-surface/80">
            Mã hội viên {me.member_code} · tham gia {joined}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {me.tier ? <span className="rounded-full bg-surface/15 px-3 py-1 text-xs font-medium">Trình độ: {me.tier}</span> : null}
            {me.record_kmh !== null ? <span className="rounded-full bg-surface/15 px-3 py-1 text-xs font-medium">Kỷ lục {me.record_kmh} km/h</span> : null}
          </div>
        </div>
      </div>

      {file ? (
        <CropDialog
          file={file}
          onClose={() => setFile(null)}
          onSaved={(url) => {
            setMe((m) => ({ ...m, avatar_url: url }));
            setMenu(false);
            setFile(null);
          }}
        />
      ) : null}
      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Xóa ảnh đại diện?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)} disabled={busy}>
              Hủy
            </Button>
            <Button onClick={() => void remove()} loading={busy}>
              {busy ? "Đang xóa…" : "Xóa ảnh"}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">Ảnh sẽ được thay bằng chữ cái đầu tên của bạn ở mọi nơi.</p>
      </Modal>
    </section>
  );
}

/** Hình sân mờ ở góc phải hero (trang trí). */
function CourtLines() {
  return (
    <svg aria-hidden viewBox="0 0 320 160" className="pointer-events-none absolute -top-2 right-0 hidden h-full max-h-48 text-surface opacity-10 sm:block" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="20" y="10" width="280" height="140" />
      <path d="M160 10v140M20 80h280M20 40h280M20 120h280M90 10v140M230 10v140" />
    </svg>
  );
}

// `tier` / `racket` rỗng = chưa chọn; `racket` = RACKET_OTHER ⇒ tên gõ ở `racketOther` (BE tự thêm vào danh mục)
type Values = { full_name: string; nickname: string; email: string; tier: string; racket: string; racketOther: string; show_on_records: boolean };
type Errors = { full_name?: string; nickname?: string; email?: string; tier?: string; racket?: string };

const toValues = (m: MemberMe): Values => ({
  full_name: m.full_name,
  nickname: m.nickname ?? "",
  email: m.email ?? "",
  tier: m.tier ?? "",
  racket: m.racket ?? "",
  racketOther: "",
  show_on_records: m.show_on_records,
});

/** Tên vợt sẽ lưu: vợt trong danh mục hoặc tên gõ ở ô "Khác…"; rỗng ⇒ null. */
const racketName = (v: Values): string | null => (v.racket === RACKET_OTHER ? v.racketOther.trim() : v.racket) || null;

/** Vợt đã lưu mà danh mục không còn (đã ẩn / đổi tên) ⇒ vẫn đưa vào ô chọn. */
const v0Racket = (m: MemberMe, names: string[]) => Boolean(m.racket) && !names.includes(m.racket as string);

function ProfileForm({ base, onReload }: { base: MemberMe; onReload: () => Promise<void> }) {
  const { setMe, setDirty } = useMember();
  const ids = { name: useId(), nick: useId(), email: useId(), phone: useId(), tier: useId(), racket: useId(), show: useId() };
  const nameRef = useRef<HTMLInputElement>(null);
  const nickRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const sending = useRef(false);
  const [v, setV] = useState<Values>(() => toValues(base));
  const [errors, setErrors] = useState<Errors>({});
  const [banner, setBanner] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloading, setReloading] = useState(false);
  const set = <K extends keyof Values>(k: K, val: Values[K]) => setV((s) => ({ ...s, [k]: val }));

  const saved = toValues(base);
  // Danh mục vợt đang dùng (GET /rackets, danh sách phẳng); vợt hiện tại không có trong danh mục vẫn hiện được
  const rackets = useRackets(false);
  const names = rackets.state.status === "ok" ? rackets.state.items.map((r) => r.name) : [];
  const racketOptions = (v0Racket(base, names) ? [base.racket as string, ...names] : names).map((r) => ({ value: r, label: r }));
  const dirty =
    v.full_name.trim() !== saved.full_name.trim() ||
    v.nickname.trim() !== saved.nickname.trim() ||
    v.email.trim() !== saved.email.trim() ||
    v.tier !== saved.tier ||
    racketName(v) !== racketName(saved) ||
    v.show_on_records !== saved.show_on_records;

  // Báo khung (menu, logo, Đăng xuất) có thay đổi chưa lưu ⇒ hỏi E-007 trước khi rời
  useEffect(() => {
    setDirty(dirty);
    return () => setDirty(false);
  }, [dirty, setDirty]);

  function validate(): Errors {
    const e: Errors = {};
    if (!v.full_name.trim()) e.full_name = "Vui lòng nhập Họ tên.";
    const email = v.email.trim();
    if (email && (email.length > 254 || !EMAIL_RE.test(email))) e.email = "Email không hợp lệ.";
    // Chưa từng xếp hạng thì được để trống; đã có hạng thì không được bỏ trống
    if (!v.tier && saved.tier) e.tier = "Vui lòng chọn Trình độ.";
    return e;
  }

  function focusFirst(e: Errors) {
    const first = (["full_name", "nickname", "email", "tier", "racket"] as const).find((k) => e[k]);
    if (first === "tier") document.getElementById(ids.tier)?.focus();
    else if (first === "racket") document.getElementById(v.racket === RACKET_OTHER ? `${ids.racket}-other` : ids.racket)?.focus();
    else if (first === "full_name") nameRef.current?.focus();
    else if (first === "nickname") nickRef.current?.focus();
    else if (first === "email") emailRef.current?.focus();
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    if (!dirty || sending.current) return;
    setBanner("");
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length) return focusFirst(found);

    sending.current = true;
    setBusy(true);
    const res = await putMe({
      full_name: v.full_name.trim(),
      nickname: v.nickname.trim() || null,
      email: v.email.trim() || null,
      tier: v.tier || null,
      racket: racketName(v),
      show_on_records: v.show_on_records,
      version: base.version,
    });
    sending.current = false;
    setBusy(false);

    if (!res.ok) {
      const { code, status } = res.error;
      if (code === "E-HV-12") return setConflict(true); // E-006
      if (status === 401 || code === "E-AUTH-1") {
        // E-010: hết phiên ⇒ đăng nhập lại, xong quay về Hồ sơ của tôi
        setDirty(false);
        window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien/ho-so")}&ly-do=het-han`);
        return;
      }
      if (code === "E-AUTH-25") {
        // Tài khoản do sân tạo chưa đổi mật khẩu ban đầu ⇒ đổi trước
        setDirty(false);
        window.location.replace("/doi-mat-khau");
        return;
      }
      if (code === "E-AUTH-30") {
        // Mật khẩu ban đầu hết hạn ⇒ dùng Quên mật khẩu
        setDirty(false);
        window.location.replace("/quen-mat-khau");
        return;
      }
      if (code === "E-HV-8" || status === 403) {
        setDirty(false);
        window.location.replace("/tai-khoan");
        return;
      }
      const list = (res.error.extra.fields as { field?: string; message?: string }[] | undefined) ?? [];
      const next: Errors = {};
      for (const f of list) {
        const k = f.field === "full_name" || f.field === "nickname" || f.field === "email" || f.field === "tier" || f.field === "racket" ? f.field : null;
        if (k && f.message && !next[k]) next[k] = f.message;
      }
      if (!list.length && code === "E-HV-11") next.email = res.error.message;
      if (!list.length && code === "E-HV-10") next.email = res.error.message;
      setErrors(next);
      if (Object.keys(next).length) focusFirst(next);
      else setBanner(errorText(res.error));
      return;
    }
    toast("Đã lưu hồ sơ");
    setMe(res.data); // hero + nút tài khoản cập nhật ngay; version mới ⇒ form dựng lại, 2 nút mờ
  }

  function cancel() {
    setV(toValues(base));
    setErrors({});
    setBanner("");
    setConflict(false);
  }

  async function reloadNow() {
    setReloading(true);
    await onReload(); // version mới ⇒ ProfileForm được dựng lại; phần đang sửa bị bỏ (BR-013)
    setReloading(false);
  }

  const err = (k: keyof Errors) => (errors[k] ? { "aria-invalid": true as const, "aria-describedby": `${ids.name}-${k}-err` } : {});
  const showErr = (k: keyof Errors) =>
    errors[k] ? (
      <p id={`${ids.name}-${k}-err`} role="alert" className="text-xs text-danger">
        {errors[k]}
      </p>
    ) : null;

  return (
    <form onSubmit={save} noValidate>
      {conflict ? (
        <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-card border border-danger/40 bg-danger-soft p-4 text-sm text-danger">
          <span>Hồ sơ của bạn vừa được cập nhật ở nơi khác. Tải lại để xem bản mới nhất.</span>
          <Button type="button" variant="secondary" onClick={() => void reloadNow()} loading={reloading}>
            Tải lại
          </Button>
        </div>
      ) : null}
      {banner ? (
        <p role="alert" className="mb-4 rounded-card border border-danger/40 bg-danger-soft p-4 text-sm text-danger">
          {banner}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2 lg:gap-6">
        <section aria-labelledby={`${ids.name}-t1`} className="rounded-card bg-surface p-5 shadow-card sm:p-6">
          <h2 id={`${ids.name}-t1`} className="text-base font-bold">
            Thông tin cá nhân
          </h2>
          <div className="mt-4 space-y-4">
            <Row label="Họ tên đầy đủ" htmlFor={ids.name} required>
              <Input id={ids.name} ref={nameRef} value={v.full_name} maxLength={100} autoComplete="name" onChange={(e) => set("full_name", e.target.value)} {...err("full_name")} />
              {showErr("full_name")}
            </Row>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <label htmlFor={ids.nick} className="text-label font-semibold text-muted">
                  Biệt danh
                </label>
                <span className="text-xs text-subtle tabular-nums" aria-hidden>
                  {v.nickname.length}/{NICKNAME_MAX}
                </span>
              </div>
              <Input
                id={ids.nick}
                ref={nickRef}
                value={v.nickname}
                maxLength={NICKNAME_MAX}
                placeholder="Nhập biệt danh"
                autoComplete="off"
                aria-describedby={`${ids.nick}-hint`}
                onChange={(e) => set("nickname", e.target.value)}
                {...err("nickname")}
              />
              <p id={`${ids.nick}-hint`} className="text-xs text-subtle">
                Hiện trên Video &amp; kỷ lục và phòng chơi thay cho họ tên.
              </p>
              {showErr("nickname")}
            </div>
            <Row label="Email" htmlFor={ids.email}>
              <Input id={ids.email} ref={emailRef} type="text" inputMode="email" autoComplete="email" maxLength={254} value={v.email} onChange={(e) => set("email", e.target.value)} {...err("email")} />
              {showErr("email")}
            </Row>
            <Row label="Số điện thoại" htmlFor={ids.phone}>
              <Input
                id={ids.phone}
                value={formatPhone(base.phone)}
                readOnly
                aria-describedby={`${ids.phone}-hint`}
                endSlot={
                  <svg viewBox="0 0 20 20" className="mr-2 size-4 text-muted" fill="none" stroke="currentColor" strokeWidth="1.6" aria-label="Đã khóa" role="img">
                    <rect x="4" y="9" width="12" height="8" rx="2" />
                    <path d="M7 9V6.5a3 3 0 0 1 6 0V9" />
                  </svg>
                }
              />
              <p id={`${ids.phone}-hint`} className="text-xs text-subtle">
                Muốn đổi số điện thoại, vui lòng liên hệ quầy.
              </p>
            </Row>
          </div>
        </section>

        <section aria-labelledby={`${ids.name}-t2`} className="self-start rounded-card bg-surface p-5 shadow-card sm:p-6">
          <h2 id={`${ids.name}-t2`} className="text-base font-bold">
            Thông tin chơi
          </h2>
          <div className="mt-4 space-y-4">
            <Row label="Trình độ" htmlFor={ids.tier} required>
              <Dropdown id={ids.tier} value={v.tier} onChange={(t) => set("tier", t)} placeholder="Chưa xếp hạng" options={TIERS.map((t) => ({ value: t, label: t }))} />
              {showErr("tier")}
            </Row>
            <Row label="Vợt đang dùng" htmlFor={ids.racket}>
              <Dropdown
                id={ids.racket}
                value={v.racket}
                onChange={(r) => set("racket", r)}
                placeholder="Chọn vợt"
                options={[...racketOptions, { value: RACKET_OTHER, label: "Khác…" }]}
              />
              {v.racket === RACKET_OTHER ? null : showErr("racket")}
            </Row>
            {v.racket === RACKET_OTHER ? (
              <Row label="Tên vợt khác" htmlFor={`${ids.racket}-other`}>
                <Input id={`${ids.racket}-other`} value={v.racketOther} maxLength={100} autoComplete="off" onChange={(e) => set("racketOther", e.target.value)} {...err("racket")} />
                {showErr("racket")}
              </Row>
            ) : null}
            <div className="flex items-start justify-between gap-4 border-t border-border pt-4">
              <div>
                <label htmlFor={ids.show} className="text-sm font-semibold">
                  Hiện trên Video &amp; kỷ lục
                </label>
                <p id={`${ids.show}-hint`} className="mt-0.5 text-xs text-subtle">
                  Hiện tên và kỷ lục tốc độ của bạn cho hội viên khác
                </p>
              </div>
              <Switch id={ids.show} describedBy={`${ids.show}-hint`} checked={v.show_on_records} onChange={(c) => set("show_on_records", c)} />
            </div>
          </div>
        </section>
      </div>

      <div className="mt-6 flex justify-end gap-3">
        <Button type="button" variant="secondary" onClick={cancel} disabled={!dirty || busy}>
          Hủy
        </Button>
        <Button type="submit" disabled={!dirty} loading={busy}>
          {busy ? "Đang lưu…" : "Lưu thay đổi"}
        </Button>
      </div>
    </form>
  );
}

function Row({ label, htmlFor, required, children }: { label: string; htmlFor: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-label font-semibold text-muted">
        {label}
        {required ? <span className="text-danger"> *</span> : null}
      </label>
      {children}
    </div>
  );
}

function Switch({ id, checked, onChange, describedBy }: { id: string; checked: boolean; onChange: (c: boolean) => void; describedBy: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-describedby={describedBy}
      onClick={() => onChange(!checked)}
      className={cn("relative h-6 w-11 shrink-0 rounded-full transition-colors focus-ring", checked ? "bg-primary" : "bg-border-strong")}
    >
      <span className={cn("absolute top-0.5 left-0.5 size-5 rounded-full bg-surface shadow-card transition-transform", checked && "translate-x-5")} />
    </button>
  );
}
