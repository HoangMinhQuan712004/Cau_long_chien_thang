"use client";

import { useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { type Draft, slotsOf, type SlotRef } from "./lineup";
import type { RoomMember } from "./types";

// Hộp chọn tay cho điện thoại / bàn phím (T-027 AC3): bấm ô trống → chọn người; bấm ô có người → menu;
// bấm người ở "Chờ lượt" → chọn ô.

export type SlotDialogState = { kind: "slot"; ref: SlotRef } | { kind: "member"; id: number };

type Props = {
  state: SlotDialogState;
  draft: Draft;
  members: RoomMember[];
  onClose: () => void;
  onPlace: (id: number, ref: SlotRef) => void;
  onSwitchTeam: (ref: SlotRef) => void;
  onRemove: (ref: SlotRef) => void;
};

export const slotName = (r: SlotRef) => `Đội ${r.team.toUpperCase()} · ô ${r.idx + 1}`;

export function SlotDialog({ state, draft, members, onClose, onPlace, onSwitchTeam, onRemove }: Props) {
  const byId = new Map(members.map((m) => [m.id, m]));
  const placed = new Set(slotsOf(draft).flatMap((s) => (s.id === null ? [] : [s.id])));
  const free = members.filter((m) => !placed.has(m.id));
  const slotId = state.kind === "slot" ? (draft[state.ref.team][state.ref.idx] ?? null) : null;
  const current = slotId === null ? null : (byId.get(slotId) ?? null);
  // Ô có người: mở menu trước, "Đổi người" mới sang danh sách chọn
  const [picking, setPicking] = useState(false);

  // --- Bấm người ở Chờ lượt: chọn ô
  if (state.kind === "member") {
    const m = byId.get(state.id);
    return (
      <Modal sheet open onClose={onClose} title={`Xếp ${m?.display_name ?? "người chơi"} vào sân`} footer={<Button variant="secondary" onClick={onClose}>Đóng</Button>}>
        <ul className="flex flex-col gap-2" aria-label="Chọn ô trên sân">
          {slotsOf(draft).map(({ ref, id }) => {
            const who = id === null ? null : byId.get(id);
            return (
              <li key={`${ref.team}${ref.idx}`}>
                <button
                  type="button"
                  onClick={() => onPlace(state.id, ref)}
                  className="flex min-h-11 w-full items-center justify-between gap-3 rounded-lg border border-border px-3 text-left text-sm hover:bg-primary-softer focus-ring"
                >
                  <span className="font-semibold">{slotName(ref)}</span>
                  <span className="text-muted">{who ? `đang có ${who.display_name}` : "trống"}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </Modal>
    );
  }

  const ref = state.ref;
  // --- Ô có người: menu
  if (current && !picking) {
    return (
      <Modal sheet open onClose={onClose} title={`${slotName(ref)}: ${current.display_name}`} footer={<Button variant="secondary" onClick={onClose}>Đóng</Button>}>
        <div role="group" aria-label="Thao tác" className="flex flex-col gap-2">
          <Button variant="secondary" onClick={() => setPicking(true)} disabled={free.length === 0} title={free.length === 0 ? "Không còn ai chờ để đổi." : undefined}>
            Đổi người
          </Button>
          <Button variant="secondary" onClick={() => onSwitchTeam(ref)}>
            Chuyển sang đội {ref.team === "a" ? "B" : "A"}
          </Button>
          <Button variant="secondary" onClick={() => onRemove(ref)}>
            Bỏ khỏi sân
          </Button>
        </div>
      </Modal>
    );
  }

  // --- Ô trống (hoặc "Đổi người"): chọn người chưa được xếp
  return (
    <Modal sheet open onClose={onClose} title={`${slotName(ref)}: chọn người`} footer={<Button variant="secondary" onClick={onClose}>Đóng</Button>}>
      {free.length === 0 ? (
        <p className="text-sm text-muted">Không còn ai chưa được xếp trong phòng.</p>
      ) : (
        <ul className="flex flex-col gap-2" aria-label="Người trong phòng chưa được xếp">
          {free.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                onClick={() => onPlace(m.id, ref)}
                className="flex min-h-11 w-full items-center gap-2.5 rounded-lg border border-border px-3 text-left text-sm font-semibold hover:bg-primary-softer focus-ring"
              >
                <Avatar url={m.avatar_url} name={m.display_name} size={28} />
                {m.display_name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
