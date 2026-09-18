import type { Metadata } from "next";
import { DM_Sans, Fraunces, IBM_Plex_Mono, Source_Serif_4 } from "next/font/google";

import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { SiteGate } from "@/components/site-gate";
import { ThemeProvider } from "@/components/theme-provider";
import { CourseNavProvider } from "@/lib/course-nav";
import { SessionProvider } from "@/lib/session";
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
      suppressHydrationWarning
      className={`${sans.variable} ${heading.variable} ${notes.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        {/* Wraps the shell, not just the page, so a locked instance shows no
            sidebar or navigation to click at. Renders children unchanged when
            the gate is off, which is always the case locally. */}
        <ThemeProvider>
          <SiteGate>
            <SessionProvider>
            <CourseNavProvider>
              {/* One skip link for every breakpoint. It used to live inside
                  SiteHeader, which is lg:hidden, so on a desktop it was
                  display:none and unreachable - precisely where it matters
                  most, since the sidebar carries the whole course library
                  ahead of the content. #main is owned here so the target
                  cannot go missing on a page that forgot to declare it. */}
              <a
                href="#main"
                className="sr-only rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50"
              >
                Skip to content
              </a>

              {/* Sidebar on wide screens; the top header takes over below lg. */}
              <div className="flex min-h-screen">
                <AppSidebar />
                <div className="flex min-w-0 flex-1 flex-col">
                  <SiteHeader />
                  {/* tabIndex makes the skip link actually move focus rather
                      than only scroll. The container then matches
                      :focus-visible and Chrome draws a 1px ring around the
                      whole page, which is noise, not a cue - the region is a
                      landmark, not a control. */}
                  <main
                    id="main"
                    tabIndex={-1}
                    className="flex flex-1 flex-col focus-visible:outline-none"
                  >
                    {children}
                  </main>
                </div>
              </div>
            </CourseNavProvider>
            </SessionProvider>
          </SiteGate>
        </ThemeProvider>
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
