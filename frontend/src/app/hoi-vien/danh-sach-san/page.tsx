import type { Metadata } from "next";
import { RoomsScreen } from "@/components/play-rooms/rooms-screen";

export const metadata: Metadata = { title: "Danh sách sân" };

export default function Page() {
  return <RoomsScreen />;
}
