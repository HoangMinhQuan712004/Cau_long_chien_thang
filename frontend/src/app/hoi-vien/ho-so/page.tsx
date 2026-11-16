import type { Metadata } from "next";
import { ProfileScreen } from "@/components/member-area/profile-screen";

export const metadata: Metadata = { title: "Hồ sơ của tôi" };

export default function ProfilePage() {
  return <ProfileScreen />;
}
