type FieldProps = {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
};

/** Nhãn + ô nhập (prototype `.field`). */
export function Field({ label, htmlFor, children }: FieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-label font-semibold text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}
