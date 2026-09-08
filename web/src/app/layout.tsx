import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import NavUser from "@/components/NavUser";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "LeGM",
  description: "Fantasy NBA draft assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <AuthProvider>
          <header className="border-b border-white/10 bg-[#0e1729]">
            <nav className="mx-auto flex max-w-[1600px] items-center gap-6 px-4 py-3 text-sm">
              <Link href="/" className="text-lg font-semibold tracking-tight">
                Le<span className="text-amber-400">GM</span>
              </Link>
              <Link href="/" className="text-slate-300 hover:text-white">
                Drafts
              </Link>
              <Link href="/rankings" className="text-slate-300 hover:text-white">
                Rankings
              </Link>
              <NavUser />
            </nav>
          </header>
          <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
