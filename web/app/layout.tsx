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
  description: "Lồng tiếng video sang tiếng Việt, Anh, Trung, Nhật, Hàn",
  // the UI is already Vietnamese; browser auto-translate rewrites text nodes and breaks React
  other: { google: "notranslate" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi" translate="no" suppressHydrationWarning className={`${sans.variable} ${display.variable} ${mono.variable} antialiased`}>
      <body className="flex min-h-dvh flex-col bg-background lg:h-dvh lg:min-h-[700px] lg:min-w-[1000px]">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <TooltipProvider delayDuration={300}>
            <SiteHeader />
            <main className="flex min-h-0 w-full flex-1 flex-col px-3 py-3">{children}</main>
            <Toaster richColors position="top-center" />
            <DesktopBridge />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
