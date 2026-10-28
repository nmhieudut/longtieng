import type { Metadata } from "next";
import { Be_Vietnam_Pro, Bricolage_Grotesque, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "next-themes";

import { DesktopBridge } from "@/components/desktop-bridge";
import { SiteHeader } from "@/components/site-header";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const sans = Be_Vietnam_Pro({
  variable: "--font-be-vietnam",
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700"],
});
const display = Bricolage_Grotesque({ variable: "--font-bricolage", subsets: ["latin", "vietnamese"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Lồng tiếng",
  description: "Lồng tiếng video sang tiếng Việt",
  // the UI is already Vietnamese; browser auto-translate rewrites text nodes and breaks React
  other: { google: "notranslate" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi" translate="no" suppressHydrationWarning className={`${sans.variable} ${display.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <TooltipProvider delayDuration={300}>
            <SiteHeader />
            <main className="flex-1 w-full max-w-[1440px] mx-auto px-4 py-5 sm:px-6 sm:py-7">{children}</main>
            <Toaster richColors position="top-center" />
            <DesktopBridge />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
