"use client";

import { useEffect, useId, useRef, useState } from "react";
import { TIERS } from "@/app/admin/hoi-vien/_components/member-params";
import { Button } from "@/components/ui/button";
import { Dropdown } from "@/components/ui/dropdown";
import { Input } from "@/components/ui/input";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { Avatar } from "./avatar";
import { AvatarEditor } from "./avatar-editor";
import { useMember } from "./member-shell";
import { deleteAvatar, getMe, putAvatar, putMe } from "./requests";
import { formatPhone, type MemberMe, type MeInput, NICKNAME_MAX } from "./types";

// /hoi-vien/ho-so (T-016 AC7–AC19): hero + hai thẻ; Lưu / Hủy mờ khi chưa sửa; lỗi dưới ô; E-006 / E-007 / E-010 / E-011.

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
  const joined = `${me.joined_at.slice(5, 7)}/${me.joined_at.slice(0, 4)}`;

  return (
    <section aria-label="Thông tin hội viên" className="relative overflow-hidden bg-appbar text-surface">
      <CourtLines />
      <div className="relative mx-auto flex max-w-6xl items-center gap-4 px-4 py-8 sm:gap-6 sm:py-10">
        <AvatarEditor
          hasImage={Boolean(me.avatar_url)}
          upload={putAvatar}
          remove={deleteAvatar}
          // Chỉ đổi ảnh: không đụng phiên bản / các ô đang sửa
          onChange={(url) => setMe((m) => ({ ...m, avatar_url: url }))}
        >
          <Avatar url={me.avatar_url} name={me.short_name} size={96} className="ring-4 ring-surface/25" />
        </AvatarEditor>

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

// Hồ sơ chia hai khối Xem / Sửa (T-038): mặc định chế độ xem, "Sửa" ở tiêu đề từng khối, chỉ một khối sửa tại một thời điểm.
// Hạng (Trình độ): hội viên tự chọn khi Sửa khối Thông tin chơi (T-042, đảo phần khóa Hạng của T-038); NV / Admin vẫn sửa ở quản trị.
type Section = "personal" | "play";
type Values = { full_name: string; nickname: string; email: string; tier: string; racket: string; show_on_records: boolean };
type Errors = { full_name?: string; nickname?: string; email?: string; racket?: string };

const toValues = (m: MemberMe): Values => ({
  full_name: m.full_name,
  nickname: m.nickname ?? "",
  email: m.email ?? "",
  tier: m.tier ?? "",
  racket: m.racket ?? "",
  show_on_records: m.show_on_records,
});

/** Tên vợt sẽ lưu: cắt 2 đầu, gộp khoảng trắng (BE cũng chuẩn hóa như vậy); rỗng ⇒ null. */
const racketName = (v: Values): string | null => v.racket.trim().replace(/\s+/g, " ") || null;

const PENCIL = (
  <svg viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="m13.5 3.5 3 3L7 16H4v-3zM12 5l3 3" />
  </svg>
);
const LOCK = (
  <svg viewBox="0 0 20 20" className="mr-2 size-4 text-muted" fill="none" stroke="currentColor" strokeWidth="1.6" aria-label="Đã khóa" role="img">
    <rect x="4" y="9" width="12" height="8" rx="2" />
    <path d="M7 9V6.5a3 3 0 0 1 6 0V9" />
  </svg>
);

function ProfileForm({ base, onReload }: { base: MemberMe; onReload: () => Promise<void> }) {
  const { setMe, setDirty, leave } = useMember();
  const ids = { name: useId(), nick: useId(), email: useId(), phone: useId(), tier: useId(), racket: useId(), show: useId() };
  const nameRef = useRef<HTMLInputElement>(null);
  const nickRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const sending = useRef(false);
  const [editing, setEditing] = useState<Section | null>(null);
  const [v, setV] = useState<Values>(() => toValues(base));
  const [errors, setErrors] = useState<Errors>({});
  const [banner, setBanner] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloading, setReloading] = useState(false);
  const set = <K extends keyof Values>(k: K, val: Values[K]) => setV((s) => ({ ...s, [k]: val }));

  const saved = toValues(base);
  // Chỉ tính thay đổi của khối đang sửa
  const dirty =
    editing === "personal"
      ? v.full_name.trim() !== saved.full_name.trim() || v.nickname.trim() !== saved.nickname.trim() || v.email.trim() !== saved.email.trim()
      : editing === "play"
        ? v.tier !== saved.tier || racketName(v) !== racketName(saved) || v.show_on_records !== saved.show_on_records
        : false;

  // Báo khung (menu, logo, Đăng xuất) có thay đổi chưa lưu ⇒ hỏi E-007 trước khi rời
  useEffect(() => {
    setDirty(dirty);
    return () => setDirty(false);
  }, [dirty, setDirty]);

  function reset() {
    setV(toValues(base));
    setErrors({});
    setBanner("");
    setConflict(false);
  }

  /** Bấm "Sửa": đang có thay đổi chưa lưu ở khối kia thì hỏi xác nhận trước (E-007), đồng ý thì bỏ thay đổi đó. */
  function startEdit(next: Section) {
    if (editing === next) return;
    leave(() => {
      reset();
      setEditing(next);
    });
  }

  function cancel() {
    reset();
    setEditing(null);
  }

  function validate(): Errors {
    const e: Errors = {};
    if (editing === "personal") {
      if (!v.full_name.trim()) e.full_name = "Vui lòng nhập Họ tên.";
      const email = v.email.trim();
      if (email && (email.length > 254 || !EMAIL_RE.test(email))) e.email = "Email không hợp lệ.";
    }
    return e;
  }

  function focusFirst(e: Errors) {
    const first = (["full_name", "nickname", "email", "racket"] as const).find((k) => e[k]);
    if (first === "racket") document.getElementById(ids.racket)?.focus();
    else if (first === "full_name") nameRef.current?.focus();
    else if (first === "nickname") nickRef.current?.focus();
    else if (first === "email") emailRef.current?.focus();
  }

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    if (!editing || !dirty || sending.current) return;
    setBanner("");
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length) return focusFirst(found);

    // Khối không sửa giữ nguyên giá trị đã lưu; `tier` luôn là hạng hiện tại (BE bỏ qua, không bao giờ đổi qua đường này)
    const next = editing === "personal" ? { ...saved, full_name: v.full_name, nickname: v.nickname, email: v.email } : { ...saved, tier: v.tier, racket: v.racket, show_on_records: v.show_on_records };
    sending.current = true;
    setBusy(true);
    const res = await putMe({
      full_name: next.full_name.trim(),
      nickname: next.nickname.trim() || null,
      email: next.email.trim() || null,
      tier: (next.tier || null) as MeInput["tier"],
      racket: racketName(next),
      show_on_records: next.show_on_records,
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
      const nextErrors: Errors = {};
      for (const f of list) {
        const k = f.field === "full_name" || f.field === "nickname" || f.field === "email" || f.field === "racket" ? f.field : null;
        if (k && f.message && !nextErrors[k]) nextErrors[k] = f.message;
      }
      if (!list.length && code === "E-HV-11") nextErrors.email = res.error.message;
      if (!list.length && code === "E-HV-10") nextErrors.email = res.error.message;
      setErrors(nextErrors);
      if (Object.keys(nextErrors).length) focusFirst(nextErrors);
      else setBanner(errorText(res.error));
      return;
    }
    toast("Đã lưu hồ sơ");
    // Hero + nút tài khoản cập nhật ngay; version mới ⇒ form dựng lại ở chế độ xem (muốn đổi tiếp thì bấm Sửa)
    setMe(res.data);
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
  const none = <span className="text-subtle">Chưa có</span>;

  return (
    <div>
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

      <div className="grid gap-4 lg:grid-cols-2 lg:items-start lg:gap-6">
        <SectionCard id={`${ids.name}-t1`} title="Thông tin cá nhân" editing={editing === "personal"} onEdit={() => startEdit("personal")} onCancel={cancel} onSubmit={save} busy={busy} dirty={dirty}>
          {editing === "personal" ? (
            <div className="space-y-4">
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
                <Input id={ids.phone} value={formatPhone(base.phone)} readOnly aria-describedby={`${ids.phone}-hint`} endSlot={LOCK} />
                <p id={`${ids.phone}-hint`} className="text-xs text-subtle">
                  Muốn đổi số điện thoại, vui lòng liên hệ quầy.
                </p>
              </Row>
            </div>
          ) : (
            <dl className="space-y-4">
              <View label="Họ tên đầy đủ">{base.full_name}</View>
              <View label="Biệt danh">{base.nickname || none}</View>
              <View label="Email">{base.email || none}</View>
              <View label="Số điện thoại" hint="Muốn đổi số điện thoại, vui lòng liên hệ quầy.">
                <span className="inline-flex items-center gap-1">
                  {formatPhone(base.phone)}
                  {LOCK}
                </span>
              </View>
            </dl>
          )}
        </SectionCard>

        <SectionCard id={`${ids.name}-t2`} title="Thông tin chơi" editing={editing === "play"} onEdit={() => startEdit("play")} onCancel={cancel} onSubmit={save} busy={busy} dirty={dirty}>
          <div className="space-y-4">
            {editing === "play" ? (
              <>
                <Row label="Trình độ (Hạng)" htmlFor={ids.tier}>
                  <Dropdown id={ids.tier} value={v.tier} onChange={(t) => set("tier", t)} placeholder="Chưa xếp hạng" options={TIERS.map((t) => ({ value: t, label: t }))} />
                </Row>
                <Row label="Vợt đang dùng" htmlFor={ids.racket}>
                  <Input id={ids.racket} value={v.racket} maxLength={100} autoComplete="off" placeholder="Ví dụ: Yonex Astrox 88D" onChange={(e) => set("racket", e.target.value)} {...err("racket")} />
                  {showErr("racket")}
                </Row>
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
              </>
            ) : (
              <dl className="space-y-4">
                <View label="Trình độ (Hạng)">{base.tier ?? "Chưa xếp hạng"}</View>
                <View label="Vợt đang dùng">{base.racket || none}</View>
                <View label="Hiện trên Video & kỷ lục" hint="Hiện tên và kỷ lục tốc độ của bạn cho hội viên khác">
                  <span className={cn("font-semibold", base.show_on_records ? "text-primary" : "text-muted")}>{base.show_on_records ? "Bật" : "Tắt"}</span>
                </View>
              </dl>
            )}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

/** Khối hồ sơ: tiêu đề + nút "Sửa" (bút); khi sửa thì bọc form và có Hủy / Lưu ngay trong khối. */
function SectionCard({
  id,
  title,
  editing,
  onEdit,
  onCancel,
  onSubmit,
  busy,
  dirty,
  children,
}: {
  id: string;
  title: string;
  editing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSubmit: (e: React.FormEvent) => void;
  busy: boolean;
  dirty: boolean;
  children: React.ReactNode;
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-3">
        <h2 id={id} className="text-base font-bold">
          {title}
        </h2>
        {editing ? null : (
          <button type="button" onClick={onEdit} aria-label={`Sửa ${title.toLowerCase()}`} className="inline-flex h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold text-primary hover:bg-primary-softer focus-ring sm:h-9">
            {PENCIL}
            Sửa
          </button>
        )}
      </div>
      <div className="mt-4">{children}</div>
      {editing ? (
        <div className="mt-5 flex justify-end gap-3 border-t border-border pt-4">
          <Button type="button" variant="secondary" className="h-11 sm:h-10" onClick={onCancel} disabled={busy}>
            Hủy
          </Button>
          <Button type="submit" variant="cta" className="h-11 px-5 sm:h-10 sm:text-sm" disabled={!dirty} loading={busy}>
            {busy ? "Đang lưu…" : "Lưu"}
          </Button>
        </div>
      ) : null}
    </>
  );
  const cls = cn("rounded-card bg-surface p-5 shadow-card sm:p-6", editing && "ring-2 ring-primary/30");
  return editing ? (
    <form aria-labelledby={id} onSubmit={onSubmit} noValidate className={cls}>
      {body}
    </form>
  ) : (
    <section aria-labelledby={id} className={cls}>
      {body}
    </section>
  );
}

/** Một dòng ở chế độ xem: nhãn nhỏ + giá trị chữ (+ ghi chú). */
function View({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-label font-semibold text-muted">{label}</dt>
      <dd className="text-sm break-words">{children}</dd>
      {hint ? <p className="text-xs text-subtle">{hint}</p> : null}
    </div>
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
