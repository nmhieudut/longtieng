import type { Metadata } from "next";
import { Be_Vietnam_Pro, Geist_Mono } from "next/font/google";
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
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Lồng tiếng",
  description: "Lồng tiếng video sang tiếng Việt",
  // the UI is already Vietnamese; browser auto-translate rewrites text nodes and breaks React
  other: { google: "notranslate" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi" translate="no" suppressHydrationWarning className={`${sans.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-muted/40">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <TooltipProvider delayDuration={300}>
            <SiteHeader />
            <main className="flex-1 w-full max-w-[1500px] mx-auto px-4 py-5 sm:px-6">{children}</main>
            <Toaster richColors position="top-center" />
            <DesktopBridge />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
