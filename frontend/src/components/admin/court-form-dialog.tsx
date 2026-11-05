"use client";

import { Modal } from "@/components/ui/modal";
import { CourtForm } from "./court-form";
import type { Form, Resource, ResourceType } from "./court-form-logic";
import { useCourtForm } from "./use-court-form";

/** Popup "Thêm sân" (sửa sân nằm trong ngăn chi tiết). */
export function CourtFormDialog({
  initial,
  resources,
  types,
  onClose,
  onSaved,
  onReload,
}: {
  initial: Form;
  resources: Resource[];
  types: ResourceType[];
  onClose: () => void;
  onSaved: (code: string) => void;
  onReload: () => void;
}) {
  const state = useCourtForm(initial, resources, onSaved);
  return (
    <Modal
      open
      onClose={onClose}
      size="wide"
      title="Thêm sân"
      footer={
        <>
          <button type="button" onClick={onClose} disabled={state.busy} className="min-h-11 rounded-md border border-border px-4 py-2 text-sm sm:min-h-0">
            Hủy
          </button>
          <button
            type="button"
            onClick={() => void state.submit()}
            disabled={state.busy}
            className="min-h-11 rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-60 sm:min-h-0"
          >
            {state.busy ? "Đang lưu…" : "Thêm sân"}
          </button>
        </>
      }
    >
      <CourtForm state={state} types={types} onReload={onReload} />
    </Modal>
  );
}
