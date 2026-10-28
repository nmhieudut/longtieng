"use client";

import { useEffect } from "react";
import { toast } from "sonner";

import { desktopApi } from "@/lib/api";

/**
 * In the desktop app the web view can't download files by itself.
 * Catch clicks on "?download=1" links and let the app show a native Save dialog instead.
 */
export function DesktopBridge() {
  useEffect(() => {
    async function onClick(e: MouseEvent) {
      const bridge = desktopApi();
      if (!bridge || e.defaultPrevented || e.button !== 0) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a) return;
      const url = new URL(a.href, location.href);
      if (url.origin === location.origin && url.searchParams.get("download") === "1") {
        e.preventDefault();
        const r = await bridge.save_file(url.pathname + url.search);
        if (r.saved) {
          const path = r.saved;
          toast.success("Đã lưu file", {
            description: path,
            action: { label: "Mở thư mục", onClick: () => { bridge.reveal(path); } },
          });
        } else if (r.error) {
          toast.error(r.error);
        }
      } else if (url.origin !== location.origin) {
        // external links: open in the normal browser, not inside the app window
        e.preventDefault();
        window.open(url.href, "_blank");
      }
    }
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);
  return null;
}
