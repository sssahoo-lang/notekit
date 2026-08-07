import type { Metadata } from "next";
import { DM_Sans, Fraunces, IBM_Plex_Mono, Source_Serif_4 } from "next/font/google";

import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { SiteGate } from "@/components/site-gate";
import { CourseNavProvider } from "@/lib/course-nav";
import { Toaster } from "@/components/ui/sonner";

import "./globals.css";

const sans = DM_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
});

const heading = Fraunces({
  variable: "--font-heading",
  subsets: ["latin"],
});

const notes = Source_Serif_4({
  variable: "--font-notes",
  subsets: ["latin"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "NoteKit",
  description:
    "Grounded course notes from real sources, with citations streamed module by module.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${sans.variable} ${heading.variable} ${notes.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        {/* Wraps the shell, not just the page, so a locked instance shows no
            sidebar or navigation to click at. Renders children unchanged when
            the gate is off, which is always the case locally. */}
        <SiteGate>
          <CourseNavProvider>
            {/* Sidebar on wide screens; the top header takes over below lg. */}
            <div className="flex min-h-screen">
              <AppSidebar />
              <div className="flex min-w-0 flex-1 flex-col">
                <SiteHeader />
                <main className="flex flex-1 flex-col">{children}</main>
              </div>
            </div>
          </CourseNavProvider>
        </SiteGate>
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
