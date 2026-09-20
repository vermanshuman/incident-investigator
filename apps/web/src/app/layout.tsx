import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Incident Investigator",
  description: "Hypothesis-driven AI agent for production incident triage",
};

const nav = [
  ["/", "Dashboard"],
  ["/incidents", "Incidents"],
  ["/runs", "Agent Runs"],
  ["/logs", "Logs"],
  ["/knowledge", "Knowledge"],
  ["/integrations", "Integrations"],
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="sidebar">
            <div className="brand">Incident Investigator</div>
            <nav>
              {nav.map(([href, label]) => (
                <Link key={href} href={href}>
                  {label}
                </Link>
              ))}
            </nav>
          </aside>
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
