import { SettingsView } from "@/components/SettingsView";

export const dynamic = "force-dynamic";

export default function SettingsPage() {
  return (
    <>
      <h1>Settings</h1>
      <p className="muted">Organization, plan, members and API keys.</p>
      <SettingsView />
    </>
  );
}
