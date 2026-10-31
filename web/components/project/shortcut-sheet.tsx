"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const GROUPS: { title: string; keys: [string, string][] }[] = [
  { title: "Phát và di chuyển", keys: [["Space hoặc K", "Phát / dừng"], ["← →", "Một khung hình (Shift: một giây)"], ["J / L", "Lùi / tiến 5 giây"], ["Home / End", "Về đầu / cuối"], ["+ / − hoặc Ctrl/⌘ cuộn chuột", "Phóng to / thu nhỏ timeline"]] },
  { title: "Dựng", keys: [["S", "Cắt đôi tại đường chỉ"], ["D", "Nhân đôi đoạn (hoặc chữ/hình dán đang chọn)"], ["Delete", "Xoá đoạn hoặc chữ/hình dán đang chọn"], ["Ctrl/⌘ Z / Shift Z", "Hoàn tác / làm lại"]] },
  { title: "Chữ, hình dán, video chồng", keys: [["Bấm đúp chữ", "Gõ chữ ngay trên video"], ["Kéo / kéo góc", "Dời / đổi kích thước"], ["Ctrl/⌘ C, V, D", "Sao chép, dán, nhân đôi"], ["← ↑ ↓ →", "Dời nhẹ (Shift: dời nhiều)"], ["Esc", "Bỏ chọn"]] },
];

export function ShortcutSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Phím tắt</DialogTitle>
          <DialogDescription>Dùng khi con trỏ không nằm trong ô nhập chữ.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          {GROUPS.map((g) => (
            <section key={g.title} className="grid gap-1.5">
              <h3 className="text-xs font-semibold text-muted-foreground">{g.title}</h3>
              {g.keys.map(([k, what]) => (
                <p key={k} className="flex items-baseline justify-between gap-3 text-sm">
                  <span>{what}</span><kbd className="shrink-0 rounded border bg-muted px-1.5 py-0.5 font-mono text-xs">{k}</kbd>
                </p>
              ))}
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
