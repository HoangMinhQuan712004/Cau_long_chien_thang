import { cn } from "@/lib/cn";

type RadioGroupProps = {
  name: string;
  legend: string;
  options: readonly { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
};

/** Nhóm chọn một (Figma "Giới tính" 275:12997): radio gốc tô màu thương hiệu, cả dòng chữ bấm được (≥ 44px trên điện thoại). */
export function RadioGroup({ name, legend, options, value, onChange, disabled, className }: RadioGroupProps) {
  return (
    <fieldset className={cn("flex flex-col gap-1.5", className)} disabled={disabled}>
      <legend className="mb-1.5 text-label font-semibold text-muted">{legend}</legend>
      <div className="flex flex-wrap gap-x-6">
        {options.map((o) => (
          <label
            key={o.value}
            className={cn(`
              flex min-h-11 cursor-pointer items-center gap-2 text-sm
              has-disabled:cursor-not-allowed has-disabled:text-muted
              sm:min-h-8
            `)}
          >
            <input
              type="radio"
              name={name}
              value={o.value}
              checked={value === o.value}
              onChange={() => onChange(o.value)}
              className="size-4.5 shrink-0 cursor-[inherit] accent-sidebar focus-ring"
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
