import type { Metadata } from "next";
import { Suspense } from "react";
import { Alert } from "@/components/ui/alert";
import { CalendarIcon, IdCardIcon, PhoneIcon, Svg, UserIcon } from "@/components/ui/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { getDictionary } from "@/i18n/dictionaries";
import { authedApi } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import { formatDayMonthYear, vnDate } from "@/lib/format";
import { ChangeOwnPassword } from "./_components/change-own-password";
import { ProfileName } from "./_components/profile-name";
import { ProfileRow } from "./_components/profile-sheet";
import { SessionsPanel } from "./_components/sessions-panel";

// Hồ sơ của tôi (Admin + nhân viên quầy): một thẻ – đầu hồ sơ (dải xanh hình sân, Admin sửa họ tên tại chỗ),
// nhóm "Tài khoản" và "Đăng nhập và bảo mật" gồm các dòng "›", mỗi dòng mở một bảng con kiểu Meta.

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).adminProfile.metaTitle, robots: { index: false, follow: false } };
}

export default function AdminProfilePage() {
  return (
    <Suspense fallback={<ProfileSkeleton />}>
      <Profile />
    </Suspense>
  );
}

// "Nguyễn Văn An" ⇒ "VA" (giống nút tài khoản trên header)
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words.slice(-2).map((w) => w[0]) : [...(words[0] ?? "?")].slice(0, 2);
  return letters.join("").toLocaleUpperCase("vi");
}

// Cỡ chữ theo token cố định như các màn admin khác; responsive nằm ở bố cục. Thẻ max-w-3xl căn giữa ở mọi màn lớn.
const COLUMN = "mx-auto flex w-full max-w-3xl flex-col gap-4";
const CARD = "overflow-hidden rounded-card bg-surface shadow-card";
const SECTION_TITLE = "text-label font-semibold tracking-wide text-muted uppercase";
const AVATAR = "grid size-16 shrink-0 place-items-center rounded-full -mt-8 ring-4 ring-surface sm:size-20 sm:-mt-10";

/** Đường kẻ sân cầu lông mờ trên dải đầu hồ sơ (trang trí). */
function CourtLines() {
  return (
    <svg aria-hidden viewBox="0 0 320 160" fill="none" stroke="currentColor" strokeWidth="2" className={cn(
      "pointer-events-none absolute -top-4 -right-10 h-[140%] text-sidebar-fg opacity-15",
      "sm:-right-4 lg:right-6",
    )}>
      <rect x="20" y="10" width="280" height="140" />
      <path d="M160 10v140M20 80h280M20 40h280M20 120h280M90 10v140M230 10v140" />
    </svg>
  );
}

/** Khung chờ đúng hình: dải xanh, avatar, tên, các dòng thông tin. */
function ProfileSkeleton() {
  return (
    <div className={COLUMN}>
      <Skeleton className="h-7 w-40" />
      <div className={CARD}>
        <Skeleton className="h-20 w-full rounded-none sm:h-24" />
        <div className="flex flex-col gap-6 px-4 pb-6 sm:px-8">
          <Skeleton className={AVATAR} />
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-24 w-full" />
        </div>
      </div>
    </div>
  );
}

const LockIcon = () => (
  <Svg size={16}>
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </Svg>
);
const DevicesIcon = () => (
  <Svg size={16}>
    <rect x="2.5" y="4" width="14" height="10" rx="1.5" />
    <path d="M6 18h7M9.5 14v4" />
    <rect x="16" y="9" width="5.5" height="11" rx="1.2" />
  </Svg>
);
const fill = (s: string, vars: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (m, k: string) => String(vars[k] ?? m));

async function Profile() {
  const [dictionary, api] = await Promise.all([getDictionary(), authedApi()]);
  const [{ data: a }, { data: sessions }] = await Promise.all([
    api.GET("/api/v1/admin/account"),
    api.GET("/api/v1/admin/account/sessions"),
  ]);
  const t = dictionary.adminProfile;
  // Hết phiên: StaffGate (layout) đã chuyển về màn đăng nhập
  if (!a) return <Alert variant="error">{t.loadError}</Alert>;
  // Trường null ⇒ ẩn mục
  const rows = [
    { icon: PhoneIcon, label: t.phone, value: a.phone },
    { icon: IdCardIcon, label: t.staffCode, value: a.staff_code },
    { icon: UserIcon, label: t.username, value: a.username },
    { icon: CalendarIcon, label: t.joinedAt, value: formatDayMonthYear(vnDate(a.created_at)) },
  ];
  // Chữ phụ "Thông tin tài khoản" theo dữ liệu thật (Admin không có mã NV ⇒ không ghi)
  const infoParts = [a.phone && t.phone, a.staff_code && t.staffCode, a.username && t.username, t.joinedSub].filter(Boolean) as string[];
  const infoSub = infoParts.map((x, i) => (i ? x.toLocaleLowerCase("vi") : x)).join(", ");
  // Dòng phụ "N thiết bị · Thiết bị này: Chrome trên Linux" (cùng cách đặt tên như bảng thiết bị); lỗi tải ⇒ bỏ
  const cur = sessions?.find((x) => x.is_current);
  const curName = cur ? (cur.browser ? (cur.os ? fill(t.deviceOn, { browser: cur.browser, os: cur.os }) : cur.browser) : t.unknownBrowser) : null;
  const sessionsSub = sessions ? [fill(t.sessionsCount, { n: sessions.length }), curName && fill(t.thisDeviceIs, { device: curName })].filter(Boolean).join(" · ") : null;
  const sheet = { kicker: fill(t.sheetKicker, { name: a.full_name }), backLabel: t.back, closeLabel: t.close };

  return (
    <div className={COLUMN}>
      <h1 className="text-2xl font-bold">{t.title}</h1>
      {/* Một thẻ cho cả trang: dải xanh mang hình sân, các nhóm tách bằng đường kẻ mảnh */}
      <div className={CARD}>
        <div aria-hidden className={cn(`
          relative h-20 overflow-hidden bg-linear-to-br from-sidebar to-primary-hover
          sm:h-24
        `)}>
          <CourtLines />
        </div>
        <div className="flex flex-col divide-y px-4 sm:px-8">
          <section aria-label={t.title} className={cn(`
            flex flex-col gap-3 pb-6
            sm:flex-row sm:items-end sm:gap-5
          `)}>
            {/* Avatar đè lên mép dải xanh */}
            <span aria-hidden className={cn(AVATAR, `
              relative z-10 bg-primary-soft text-xl font-bold text-primary-hover shadow-card
              sm:text-2xl
            `)}>
              {initials(a.full_name)}
            </span>
            <ProfileName name={a.full_name} roleLabel={a.role_label} isAdmin={a.kind === "admin"} t={t} />
          </section>

          <section aria-labelledby="group-account" className="flex flex-col gap-2 py-5 sm:py-6">
            <h2 id="group-account" className={SECTION_TITLE}>{t.groupAccount}</h2>
            <ProfileRow icon={<UserIcon size={16} />} label={t.infoTitle} sub={infoSub} description={t.infoDesc} {...sheet}>
              <dl className="flex flex-col divide-y">
                {rows.map(({ icon: Icon, label, value }) => value ? (
                  <div key={label} className="flex items-center gap-3 py-3.5">
                    <Icon size={16} className="shrink-0 text-primary" />
                    <dt className="flex-1 text-sm text-muted">{label}</dt>
                    <dd className={cn(`text-right text-sm font-semibold break-all tabular-nums`)}>{value}</dd>
                  </div>
                ) : null)}
              </dl>
              {/* Nhân viên không tự sửa thông tin; Admin sửa ở mục Nhân viên */}
              {a.kind === "staff" ? <p className="mt-3 text-ui text-muted">{t.infoHint}</p> : null}
            </ProfileRow>
          </section>

          <section aria-labelledby="group-security" className="flex flex-col gap-2 py-5 sm:py-6">
            <h2 id="group-security" className={SECTION_TITLE}>{t.groupSecurity}</h2>
            <div className="flex flex-col divide-y">
              <ProfileRow icon={<LockIcon />} label={t.passwordRow} description={t.passwordHint} {...sheet}>
                <ChangeOwnPassword t={t} rules={dictionary.passwordRules} />
              </ProfileRow>
              <ProfileRow icon={<DevicesIcon />} label={t.sessionsRow} sub={sessionsSub} description={t.sessionsDesc} {...sheet}>
                <SessionsPanel t={t} />
              </ProfileRow>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
