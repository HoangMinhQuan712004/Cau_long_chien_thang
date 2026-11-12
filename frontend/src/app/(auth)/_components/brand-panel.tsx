import { SiteLogo } from "@/components/site-logo";
import { ShuttlecockIcon } from "@/components/ui/icons";
import { getDictionary } from "@/i18n/dictionaries";
import { getBranding } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import { APP_NAME } from "@/lib/site";

// Phần thương hiệu trên đầu các màn đăng nhập / đăng ký / quên mật khẩu (mọi khổ màn cùng kiểu): logo, tên app, 3 nhãn
// ngắn. Nền mắt lưới mờ như banner khu hội viên đặt ở layout.
export async function BrandPanel() {
  const [{ logo_url: logoUrl }, { auth: t }] = await Promise.all([getBranding(), getDictionary()]);
  return (
    <section className="text-surface">
      <div
        className={cn(
          "mx-auto flex max-w-md flex-col items-center px-6 text-center",
          "pt-[calc(env(safe-area-inset-top)+2rem)] pb-6 sm:pt-12 sm:pb-8",
        )}
      >
        <span className={cn(`
          grid size-14 place-items-center rounded-2xl bg-surface/12 ring-1 ring-surface/20
        `, `sm:size-16`)}>
          {/* Chưa tải logo ⇒ quả cầu lông trắng to thẳng trong ô mờ (không ô xanh lồng nhau); có logo ảnh ⇒ ô trắng như cũ */}
          {logoUrl ? <SiteLogo url={logoUrl} className="size-11 sm:size-12" /> : <ShuttlecockIcon className="
            size-9
            sm:size-10
          " />}
        </span>
        <h2 className="mt-4 text-2xl font-extrabold tracking-tight sm:text-3xl">{APP_NAME}</h2>
        <ul className="mt-3 flex flex-wrap justify-center gap-2">
          {t.tags.map((tag) => (
            <li key={tag} className={cn(`rounded-full bg-surface/12 px-3 py-1 text-xs font-medium`, `
              ring-1 ring-surface/20
              sm:text-sm
            `)}>
              {tag}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
