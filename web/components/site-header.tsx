"use client";

import { AudioLines, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { AppSettingsButton } from "@/components/app-settings";
import { Button } from "@/components/ui/button";
import { UpdateButton } from "@/components/update-button";
import { api } from "@/lib/api";

export function SiteHeader() {
  const { resolvedTheme, setTheme } = useTheme();
  const [translator, setTranslator] = useState("");
  const loadConfig = () => { api.config().then((c) => setTranslator(c.translator)).catch(() => {}); };
  useEffect(loadConfig, []);
  return (
    <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-[10px] bg-brand">
            <AudioLines className="size-4" strokeWidth={2.4} />
          </span>
          <span className="font-heading text-[1.15rem] font-bold tracking-[-0.02em]">Lồng tiếng</span>
        </Link>
        <span className="ml-auto hidden min-w-0 truncate text-xs text-muted-foreground md:block">
          {translator && `Dịch bằng: ${translator}`}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-1 md:ml-0">
        <UpdateButton />
        <AppSettingsButton onChanged={loadConfig} />
        <Button
          variant="ghost"
          size="icon"
          aria-label="Đổi giao diện sáng/tối"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          <Sun className="size-4 dark:hidden" />
          <Moon className="hidden size-4 dark:block" />
        </Button>
        </div>
      </div>
    </header>
  );
}
