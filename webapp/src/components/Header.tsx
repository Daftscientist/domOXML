import { useEffect, useRef, useState } from "react";
import {
  ChevronDown, FileDown, FileCode2, Loader2, MonitorPlay, Moon, Presentation, Sun, Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { engine } from "@/lib/engine";
import type { EngineStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  name: string;
  onNameChange: (name: string) => void;
  slideCount: number;
  dark: boolean;
  onToggleTheme: () => void;
  exporting: boolean;
  onExportPptx: () => void;
  onDownloadHtml: () => void;
  onOpenFile: (file: File) => void;
  onPresent: () => void;
}

const PHASE_LABEL: Record<EngineStatus["phase"], string> = {
  starting: "Starting engine",
  packages: "Downloading packages",
  bundle: "Loading domOXML",
  ready: "Engine ready",
  error: "Engine failed",
};

export function Header(p: Props) {
  const [status, setStatus] = useState<EngineStatus>(engine.currentStatus);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => engine.onStatus(setStatus), []);
  const ready = status.phase === "ready";

  return (
    <header className="flex h-[52px] shrink-0 items-center gap-2 border-b bg-background px-3 sm:gap-3 sm:px-4">
      <div className="flex items-center gap-2.5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Presentation className="h-4 w-4" />
        </div>
        <div className="hidden items-baseline gap-1.5 min-[420px]:flex">
          <span className="text-[15px] font-semibold tracking-tight">domOXML</span>
          <span className="text-[13px] text-muted-foreground">Studio</span>
        </div>
      </div>

      <div className="mx-1 hidden h-5 w-px bg-border sm:block" />

      <Input
        value={p.name}
        onChange={(e) => p.onNameChange(e.target.value)}
        aria-label="Presentation name"
        className="h-8 w-36 border-transparent bg-transparent px-2 text-sm font-medium shadow-none hover:border-input focus-visible:border-input sm:w-52"
      />
      <Badge variant="secondary" className="hidden font-normal text-muted-foreground md:inline-flex">
        {p.slideCount} {p.slideCount === 1 ? "slide" : "slides"}
      </Badge>

      <div className="flex-1" />

      <div
        className={cn(
          "hidden items-center gap-1.5 text-xs text-muted-foreground lg:flex",
          status.phase === "error" && "text-destructive",
        )}
        title={status.detail || PHASE_LABEL[status.phase]}
      >
        {ready ? (
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        ) : status.phase === "error" ? (
          <span className="h-1.5 w-1.5 rounded-full bg-destructive" />
        ) : (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        )}
        {PHASE_LABEL[status.phase]}
      </div>

      <input
        ref={fileInput}
        type="file"
        accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) p.onOpenFile(file);
          e.target.value = "";
        }}
      />
      <Button variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
        <Upload className="h-4 w-4" />
        <span className="hidden sm:inline">Open .pptx</span>
      </Button>

      <Button variant="outline" size="sm" onClick={p.onPresent} disabled={p.slideCount === 0}>
        <MonitorPlay className="h-4 w-4" />
        <span className="hidden sm:inline">Present</span>
      </Button>

      <div className="flex">
        <Button size="sm" onClick={p.onExportPptx} disabled={p.exporting || p.slideCount === 0} className="rounded-r-none">
          {p.exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
          <span className="hidden sm:inline">Export .pptx</span>
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label="More export options"
            render={<Button size="sm" className="rounded-l-none border-l border-primary-foreground/20 px-1.5" />}
          >
            <ChevronDown className="h-4 w-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={p.onDownloadHtml}>
              <FileCode2 className="h-4 w-4" /> Download HTML
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <Button variant="ghost" size="icon" onClick={p.onToggleTheme} aria-label="Toggle colour theme" className="h-8 w-8">
        {p.dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </Button>
    </header>
  );
}
