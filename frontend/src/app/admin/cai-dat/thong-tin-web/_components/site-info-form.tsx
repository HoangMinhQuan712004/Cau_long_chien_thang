"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { AddressMap } from "@/components/address-map";
import { UnsavedGuard } from "@/components/admin/unsaved-guard";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, fieldErrorId } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { Dictionary } from "@/i18n/dictionaries";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { UnsavedBar } from "../../phan-quyen/_components/unsaved-bar";

type SiteInfo = components["schemas"]["SiteInfoOut"];
type FieldKey = "name" | "address" | "phone" | "email";

// Giới hạn khớp API
// Hotline: di động 10 số + 2 khoảng trắng; backend định dạng lại 4-3-3 khi lưu
const MAX: Record<FieldKey, number> = { name: 100, address: 200, phone: 12, email: 254 };
const FIELD_KEYS: FieldKey[] = ["name", "address", "phone", "email"];
const SECTION = "flex flex-col gap-4 border-t pt-6";
const SECTION_TITLE = "text-sm font-semibold";

type MapData = Pick<SiteInfo, "map_url" | "lat" | "lng">;
const pickMap = ({ map_url, lat, lng }: MapData): MapData => ({ map_url, lat, lng });
const NO_MAP: MapData = { map_url: null, lat: null, lng: null };

type Props = {
  initial: SiteInfo;
  /** Server action xóa cache trang khách theo tag API trả về. */
  refresh: (tag: string) => Promise<void>;
  t: Dictionary["siteInfo"];
};

/** Các ô chữ của Thông tin web: lưu kèm `version`; máy khác đã lưu trước (409 E-012) ⇒ báo tải lại, không ghi đè. */
export function SiteInfoForm({ initial, refresh, t }: Props) {
  const router = useRouter();
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(initial);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [isStale, setIsStale] = useState(false);
  const [map, setMap] = useState(pickMap(initial));
  const [link, setLink] = useState(initial.map_url ?? "");
  const [linkError, setLinkError] = useState("");
  const [phoneError, setPhoneError] = useState("");
  const [isResolving, setIsResolving] = useState(false);
  // Chuỗi đã đọc gần nhất: dán rồi rời ô không gọi 2 lần (API giới hạn lượt)
  const lastRead = useRef(initial.map_url ?? "");
  const readId = useRef(0);
  // Bản đồ xem trước theo địa chỉ đã rời ô / đã lưu: không nạp lại theo từng phím
  const [mapAddress, setMapAddress] = useState(initial.address);
  const dirty = FIELD_KEYS.some((key) => draft[key] !== base[key]) || map.map_url !== base.map_url || link.trim() !== (map.map_url ?? "");
  // Ô link có chữ chưa đọc được ⇒ chưa cho lưu, tránh lưu nhầm bản đồ cũ
  const linkPending = isResolving || linkError !== "" || link.trim() !== (map.map_url ?? "");

  function clearLink() {
    readId.current += 1;
    lastRead.current = "";
    setLink("");
    setMap(NO_MAP);
    setLinkError("");
    setIsResolving(false);
  }

  // Dán xong / rời ô: đọc link qua API; bản đồ chỉ dựng từ giá trị API trả về, không dùng chuỗi vừa nhập
  async function readLink(raw: string) {
    const input = raw.trim();
    if (!input) return clearLink();
    if (input === lastRead.current) return;
    lastRead.current = input;
    const id = ++readId.current;
    setIsResolving(true);
    setLinkError("");
    const res = await write(() => api.POST("/api/v1/admin/site/map/resolve", { body: { input } }), { retryRateLimit: false });
    if (id !== readId.current) return; // đã dán link khác
    setIsResolving(false);
    if (!res.ok) {
      // Cho đọc lại cùng link khi rời ô lần sau (lỗi tạm thời)
      lastRead.current = "";
      setLinkError(errorText(res.error));
      return;
    }
    lastRead.current = res.data.map_url ?? "";
    setLink(res.data.map_url ?? "");
    setMap(pickMap(res.data));
  }

  async function save() {
    if (isSaving || linkPending) return;
    setIsSaving(true);
    setError("");
    setPhoneError("");
    const { version } = base;
    const res = await write(() =>
      api.PUT("/api/v1/admin/site/info", {
        body: { name: draft.name, address: draft.address, phone: draft.phone, email: draft.email, ...map, version },
      }),
    );
    if (!res.ok) {
      setIsSaving(false);
      // Lỗi link của API (E-001) hiện ngay tại ô Link Google Maps
      if (res.error.code === "E-001" && /google maps|đọc được link/i.test(res.error.message)) {
        lastRead.current = ""; // cho đọc lại khi rời ô
        setLinkError(res.error.message);
        return;
      }
      // Lỗi hotline của API hiện ngay tại ô Hotline
      if (res.error.code === "E-001" && /hotline/i.test(res.error.message)) {
        setPhoneError(res.error.message);
        return;
      }
      setIsStale(res.error.code === "E-012");
      setError(res.error.code === "E-012" ? t.stale : errorText(res.error));
      return;
    }
    // Thông tin đã lưu mà xóa cache lỗi ⇒ trang khách cập nhật sau khi cache hết hạn
    await refresh(res.data.cache_tag).catch(() => toast(t.cacheLater, undefined, "info"));
    setIsSaving(false);
    const { cache_tag: _tag, ...saved } = res.data;
    void _tag;
    setBase(saved);
    setDraft(saved);
    setMap(pickMap(saved));
    setLink(saved.map_url ?? "");
    lastRead.current = saved.map_url ?? "";
    setMapAddress(saved.address);
    toast(t.saved);
    router.refresh();
  }

  const textField = (key: FieldKey, props?: React.ComponentProps<typeof Input>) => (
    <Field label={t.labels[key]} htmlFor={`site-${key}`} error={key === "phone" ? phoneError || undefined : undefined}>
      <Input
        id={`site-${key}`}
        value={draft[key]}
        maxLength={MAX[key]}
        disabled={isSaving}
        onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
        {...props}
      />
    </Field>
  );

  function cancel() {
    readId.current += 1;
    lastRead.current = base.map_url ?? "";
    setDraft(base);
    setMap(pickMap(base));
    setLink(base.map_url ?? "");
    setLinkError("");
    setPhoneError("");
    setIsResolving(false);
    setMapAddress(base.address);
    setError("");
    setIsStale(false);
  }

  return (
    <>
      <UnsavedGuard dirty={dirty} />
      <section aria-labelledby="site-info-title" className={SECTION}>
        <h3 id="site-info-title" className={SECTION_TITLE}>{t.title}</h3>
        {error ? (
          <Alert variant="error">
            <span className="flex flex-wrap items-center gap-3">
              {error}
              {isStale ? (
                <Button type="button" variant="secondary" onClick={() => router.refresh()}>
                  {t.reload}
                </Button>
              ) : null}
            </span>
          </Alert>
        ) : null}
        {textField("name")}
        {textField("address", { onBlur: () => setMapAddress(draft.address) })}
      </section>

      <section aria-labelledby="site-map-title" className={SECTION}>
        <h3 id="site-map-title" className={SECTION_TITLE}>{t.mapTitleSection}</h3>
        <Field label={t.labels.mapLink} htmlFor="site-map-link" hint={isResolving ? t.reading : t.hints.mapLink} error={linkError || undefined}>
          <Input
            id="site-map-link"
            inputMode="url"
            value={link}
            disabled={isSaving}
            aria-invalid={linkError ? true : undefined}
            aria-describedby={linkError ? fieldErrorId("site-map-link") : undefined}
            onChange={(e) => {
              setLink(e.target.value);
              setLinkError("");
            }}
            onPaste={(e) => {
              const text = e.clipboardData.getData("text");
              e.preventDefault();
              setLink(text);
              void readLink(text);
            }}
            onBlur={() => void readLink(link)}
            onClear={clearLink}
            clearLabel={t.clearLink}
          />
        </Field>
        <AddressMap place={{ address: mapAddress, ...map }} title={t.mapTitle.replace("{address}", mapAddress)} />
      </section>

      <section aria-labelledby="site-contact-title" className={SECTION}>
        <h3 id="site-contact-title" className={SECTION_TITLE}>{t.contactTitle}</h3>
        {/* Khung ~1024 (có sidebar) cột hẹp ⇒ xếp dọc; rộng hơn mới chung hàng */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          {textField("phone", {
            inputMode: "numeric",
            "aria-invalid": phoneError ? true : undefined,
            "aria-describedby": phoneError ? fieldErrorId("site-phone") : undefined,
            // Chỉ giữ chữ số + khoảng trắng (cả khi dán); không tự tách khi đang gõ
            onChange: (e) => {
              setDraft((d) => ({ ...d, phone: e.target.value.replace(/[^\d ]/g, "") }));
              setPhoneError("");
            },
          })}
          {textField("email", { type: "email", inputMode: "email" })}
        </div>
      </section>

      {dirty ? <UnsavedBar t={t.bar} isSaving={isSaving} saveDisabled={linkPending} onCancel={cancel} onSave={() => void save()} className="-mb-4 rounded-b-card lg:-mb-6" /> : null}
    </>
  );
}
