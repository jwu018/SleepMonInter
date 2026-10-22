import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { UserMenu } from "@/components/UserMenu";
import { PrototypeBanner } from "@/components/PrototypeBanner";
import "./globals.css";

// next/font downloads the font at build time and serves it from our own domain,
// so there's no request to Google from the user's browser and no layout shift.
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Night Night — Clinician Dashboard",
  description:
    "Prototype dashboard for overnight respiratory recordings (synthetic data only).",
};

// The root layout wraps every page in the app. Anything here (like the banner)
// appears on every route, which is what makes the banner "persistent".
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <PrototypeBanner />
        <header className="border-b border-border print:hidden">
          <div className="mx-auto flex max-w-6xl flex-wrap items-baseline gap-x-6 gap-y-2 px-4 py-4">
            <Link href="/" className="flex items-baseline gap-3">
              <span className="text-lg font-semibold tracking-tight">Night Night</span>
              <span className="text-sm text-muted">Clinician Dashboard</span>
            </Link>
            <nav className="flex gap-4 text-sm">
              <Link href="/" className="hover:underline">
                Patients
              </Link>
              <Link href="/upload" className="hover:underline">
                Upload
              </Link>
            </nav>
            <div className="ml-auto">
              <Suspense fallback={null}>
                <UserMenu />
              </Suspense>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}
