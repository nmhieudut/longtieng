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
    <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1500px] items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <AudioLines className="size-4" />
          </span>
          <span>Lồng tiếng</span>
        </Link>
        <span className="ml-auto hidden truncate text-xs text-muted-foreground sm:block">
          {translator && `Dịch bằng: ${translator}`}
        </span>
        <div className="ml-auto flex items-center gap-1 sm:ml-0">
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
