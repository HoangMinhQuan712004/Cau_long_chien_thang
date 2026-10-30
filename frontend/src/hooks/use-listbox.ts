"use client";

import { useRef, useState } from "react";

// Gõ liên tiếp trong khoảng này ⇒ ghép thành một chuỗi tìm
const TYPEAHEAD_MS = 500;

// So khớp đầu chữ không phân biệt hoa thường / dấu ("kh" khớp "Khá")
const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/gi, "d").toLocaleLowerCase("vi");

type Options = {
  labels: readonly string[];
  selectedIndex: number;
  onSelect: (index: number) => void;
};

/** Bàn phím của ô chọn kiểu combobox chỉ chọn (mẫu ARIA "select-only"): mở/đóng, ↑↓ Home End, gõ chữ để nhảy, Enter chọn, Esc/Tab đóng. */
export function useListbox({ labels, selectedIndex, onSelect }: Options) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const typed = useRef({ text: "", at: 0 });

  function open(index = selectedIndex) {
    setActiveIndex(index >= 0 ? index : 0);
    setIsOpen(true);
  }
  const close = () => setIsOpen(false);
  function choose(index: number) {
    if (index >= 0) onSelect(index);
    close();
  }

  // Gõ chữ: nhảy tới mục đầu tiên bắt đầu bằng chuỗi đã gõ, tính từ sau mục hiện tại
  function typeahead(key: string) {
    const now = Date.now();
    const text = now - typed.current.at < TYPEAHEAD_MS ? typed.current.text + key : key;
    typed.current = { text, at: now };
    const start = text.length === 1 ? activeIndex + 1 : Math.max(activeIndex, 0);
    const order = labels.map((_, i) => (start + i) % labels.length);
    const hit = order.find((i) => fold(labels[i]).startsWith(fold(text)));
    if (hit === undefined) return;
    if (isOpen) setActiveIndex(hit);
    else onSelect(hit);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const last = labels.length - 1;
    const move = (index: number) => {
      e.preventDefault();
      if (isOpen) setActiveIndex(Math.min(last, Math.max(0, index)));
      else open();
    };
    switch (e.key) {
      case "ArrowDown":
        return move(activeIndex + 1);
      case "ArrowUp":
        return move(activeIndex - 1);
      case "Home":
        return move(0);
      case "End":
        return move(last);
      case "Enter":
      case " ":
        e.preventDefault();
        return isOpen ? choose(activeIndex) : open();
      case "Escape":
        if (!isOpen) return;
        // Chỉ đóng danh sách, không để Esc đóng luôn popup / ngăn kéo chứa nó
        e.preventDefault();
        e.stopPropagation();
        return close();
      case "Tab":
        return close();
      default:
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) typeahead(e.key);
    }
  }

  return { isOpen, activeIndex, setActiveIndex, open, close, choose, onKeyDown };
}
