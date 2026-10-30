"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { createRacket, listRackets } from "./requests";
import { fold, racketLabel, type RacketGroup, type RacketRef } from "./types";

type Props = {
  id: string;
  value: RacketRef | null;
  onChange: (r: RacketRef | null) => void;
  disabled?: boolean;
};

/** Ô "Vợt đang dùng" (BR-012): gõ để lọc, gom theo hãng, thêm "+ Khác" vào danh sách chung. Danh sách hiện ngay dưới ô. */
export function RacketSelect({ id, value, onChange, disabled }: Props) {
  const listId = useId();
  const [groups, setGroups] = useState<RacketGroup[]>([]);
  const [loadError, setLoadError] = useState("");
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [typing, setTyping] = useState(false); // false: ô đang hiện tên cây đã chọn, chưa lọc
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");
  const [active, setActive] = useState(-1);

  useEffect(() => {
    let alive = true;
    void listRackets().then((res) => {
      if (!alive) return;
      if (res.ok) setGroups(res.data);
      else setLoadError(errorText(res.error));
    });
    return () => {
      alive = false;
    };
  }, []);

  const needle = typing ? fold(text.trim()) : "";
  const filtered = useMemo(
    () =>
      groups
        .map((g) => ({ brand: g.brand, items: g.items.filter((it) => fold(racketLabel({ brand: g.brand, name: it.name })).includes(needle)) }))
        .filter((g) => g.items.length > 0),
    [groups, needle],
  );
  const flat = filtered.flatMap((g) => g.items.map((it) => ({ id: it.id, brand: g.brand, name: it.name })));
  const typed = text.trim();
  const exact = typing && flat.some((r) => fold(r.name) === fold(typed) || fold(racketLabel(r)) === fold(typed));
  const showOther = typing && typed !== "" && !exact && typed.length <= 100;
  const optionCount = flat.length + (showOther ? 1 : 0);

  function pick(r: RacketRef | null) {
    onChange(r);
    setOpen(false);
    setTyping(false);
    setText("");
    setActive(-1);
  }

  async function addOther() {
    if (adding) return;
    setAdding(true);
    setAddError("");
    const res = await createRacket(typed);
    setAdding(false);
    if (!res.ok) return setAddError(errorText(res.error));
    const r = res.data;
    setGroups((gs) => {
      const has = gs.find((g) => g.brand === r.brand);
      if (has) return gs.map((g) => (g.brand === r.brand ? { ...g, items: g.items.some((i) => i.id === r.id) ? g.items : [...g.items, { id: r.id, name: r.name }] } : g));
      return [...gs, { brand: r.brand, items: [{ id: r.id, name: r.name }] }];
    });
    pick(r);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(a + 1, optionCount - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && open && active >= 0) {
      e.preventDefault();
      if (active < flat.length) pick(flat[active]);
      else void addOther();
    } else if (e.key === "Escape" && open) {
      e.stopPropagation(); // không đóng hộp thoại phía ngoài
      e.preventDefault();
      setOpen(false);
      setTyping(false);
      setText("");
    }
  }

  const shown = typing ? text : value ? racketLabel(value) : "";

  return (
    <div
      onBlur={(e) => {
        // Rời khỏi cả khối (ô + danh sách) thì đóng danh sách, bỏ chữ đang gõ dở
        if (e.currentTarget.contains(e.relatedTarget)) return;
        setOpen(false);
        setTyping(false);
        setText("");
        setActive(-1);
      }}
    >
      <div className="relative">
        <input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          disabled={disabled}
          maxLength={100}
          value={shown}
          placeholder="Chọn vợt"
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onChange={(e) => {
            setTyping(true);
            setText(e.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onKeyDown={onKeyDown}
          className={cn(
            "h-11 w-full rounded-lg border bg-surface px-3 pr-16 text-base text-ellipsis focus-ring placeholder:text-subtle sm:h-9.5 sm:text-sm",
            open ? "border-primary" : "border-border-strong",
            "disabled:cursor-not-allowed disabled:bg-background disabled:text-muted",
          )}
        />
        <div className="absolute inset-y-0 right-1 flex items-center gap-0.5">
          {value && !disabled ? (
            <button type="button" aria-label="Bỏ chọn vợt" onClick={() => pick(null)} className="grid size-7 place-items-center rounded-sm text-muted hover:text-foreground">
              ✕
            </button>
          ) : null}
          <button
            type="button"
            tabIndex={-1}
            aria-label={open ? "Đóng danh sách vợt" : "Mở danh sách vợt"}
            disabled={disabled}
            onClick={() => setOpen((o) => !o)}
            className="grid size-7 place-items-center rounded-sm text-muted"
          >
            <svg viewBox="0 0 20 20" className={cn("size-4 transition-transform", open && "rotate-180")} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
              <path d="m5 8 5 5 5-5" />
            </svg>
          </button>
        </div>
      </div>

      {open && !disabled ? (
        <div id={listId} role="listbox" aria-label="Danh sách vợt" className="mt-1 max-h-56 overflow-y-auto rounded-lg border border-border-strong bg-surface shadow-card">
          {loadError ? <p className="px-3 py-2 text-sm text-danger">{loadError}</p> : null}
          {filtered.map((g) => (
            <div key={g.brand} role="group" aria-label={g.brand}>
              <p className="px-3 pt-2 pb-1 text-xs font-semibold tracking-wide text-muted uppercase">{g.brand}</p>
              {g.items.map((it) => {
                const idx = flat.findIndex((f) => f.id === it.id);
                const on = value?.id === it.id;
                return (
                  <div
                    key={it.id}
                    id={`${listId}-${idx}`}
                    role="option"
                    aria-selected={on}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => pick({ id: it.id, brand: g.brand, name: it.name })}
                    className={cn(
                      "flex cursor-pointer items-center justify-between gap-2 px-3 py-2 pl-5 text-sm hover:bg-primary-softer",
                      (on || idx === active) && "bg-primary-softer",
                    )}
                  >
                    <span>{racketLabel({ brand: g.brand, name: it.name })}</span>
                    {on ? <span className="text-primary" aria-hidden>✓</span> : null}
                  </div>
                );
              })}
            </div>
          ))}
          {!filtered.length && !showOther && !loadError ? <p className="px-3 py-2 text-sm text-muted">Không có vợt nào.</p> : null}
          {showOther ? (
            <div
              id={`${listId}-${flat.length}`}
              role="option"
              aria-selected={false}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => void addOther()}
              className={cn("cursor-pointer border-t border-border px-3 py-2.5 text-sm font-medium text-primary hover:bg-primary-softer", active === flat.length && "bg-primary-softer")}
            >
              {adding ? "Đang thêm…" : `+ Khác: thêm “${typed}” vào danh sách`}
            </div>
          ) : null}
        </div>
      ) : null}
      {addError ? (
        <p role="alert" className="mt-1 text-xs text-danger">
          {addError}
        </p>
      ) : null}
    </div>
  );
}
