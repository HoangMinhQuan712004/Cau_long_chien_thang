type FieldProps = {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
  /** Lỗi dưới ô; ô nhập nên đặt `aria-describedby={fieldErrorId(htmlFor)}` + `aria-invalid`. */
  error?: React.ReactNode;
  /** Ghi chú nhỏ dưới ô (khi không có lỗi). */
  hint?: React.ReactNode;
};

export const fieldErrorId = (htmlFor: string) => `${htmlFor}-error`;

/** Nhãn + ô nhập (prototype `.field`). */
export function Field({ label, htmlFor, children, error, hint }: FieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-label font-semibold text-muted">
        {label}
      </label>
      {children}
      {error ? (
        <p id={fieldErrorId(htmlFor)} className="text-ui text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-ui text-muted">{hint}</p>
      ) : null}
    </div>
  );
}
