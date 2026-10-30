"use client";

import { AudioLines, Moon, Sparkles, Sun } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { AppSettingsButton } from "@/components/app-settings";
import { IconButton } from "@/components/ui/icon-button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { UpdateButton } from "@/components/update-button";
import { api } from "@/lib/api";

export function SiteHeader() {
  const { resolvedTheme, setTheme } = useTheme();
  const [translator, setTranslator] = useState("");
  const loadConfig = () => { api.config().then((c) => setTranslator(c.translator)).catch(() => {}); };
  useEffect(loadConfig, []);
  return (
    <header className="z-30 shrink-0 border-b bg-background/80 backdrop-blur-md">
      <div className="flex h-11 items-center gap-3 px-3">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <span className="grid size-7 place-items-center rounded-lg bg-brand">
            <AudioLines className="size-3.5" strokeWidth={2.4} />
          </span>
          <span className="font-heading text-base font-bold tracking-[-0.02em]">Lồng tiếng</span>
        </Link>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {translator && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="mr-1 grid size-7 cursor-default place-items-center rounded-md text-muted-foreground hover:bg-accent"><Sparkles className="size-4" /></span>
              </TooltipTrigger>
              <TooltipContent>Dịch bằng: {translator}</TooltipContent>
            </Tooltip>
          )}
          <UpdateButton />
          <AppSettingsButton onChanged={loadConfig} />
          <IconButton label="Đổi giao diện sáng / tối" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>
            <Sun className="size-4 dark:hidden" />
            <Moon className="hidden size-4 dark:block" />
          </IconButton>
        </div>
      </div>
    </header>
  );
}
