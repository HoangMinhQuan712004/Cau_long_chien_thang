import type { Metadata } from "next";
import { VideoScreen } from "@/components/member-area/video-screen";

export const metadata: Metadata = { title: "Video & kỷ lục" };

export default function Page() {
  return <VideoScreen />;
}
