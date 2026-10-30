"use client";

import type { ComponentProps, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type Props = Omit<ComponentProps<typeof Button>, "children" | "asChild"> & {
  label: string;          // what it does: the tooltip text and the accessible name
  hint?: string;          // extra line in the tooltip, e.g. a keyboard shortcut
  href?: string;          // a link instead of a button (downloads)
  download?: boolean;
  active?: boolean;       // pressed / selected look
  children: ReactNode;    // the icon
};

/** A button that shows only its icon; the tooltip says what it does. Works while disabled too (a disabled
 *  button gets no pointer events, so the tooltip hangs on a wrapper). */
export function IconButton({ label, hint, href, download, active, disabled, className, variant = "ghost", size = "icon-sm", children, ...rest }: Props) {
  const look = cn(active && "bg-accent text-accent-foreground ring-1 ring-primary/40", className);
  const button = href && !disabled ? (
    <Button asChild variant={variant} size={size} className={look} {...rest}>
      <a href={href} download={download} aria-label={label}>{children}</a>
    </Button>
  ) : (
    <Button type="button" variant={variant} size={size} className={look} disabled={disabled} aria-label={label}
      aria-pressed={active} {...rest}>{children}</Button>
  );
  return (
    <Tooltip>
      <TooltipTrigger asChild>{disabled ? <span tabIndex={0} className="inline-flex">{button}</span> : button}</TooltipTrigger>
      <TooltipContent>{label}{hint ? ` · ${hint}` : ""}</TooltipContent>
    </Tooltip>
  );
}
