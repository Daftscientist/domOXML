import { useEffect, useRef, useState } from "react";
import {
  Archive, Box, ChevronDown, ChevronRight, Group, Image, Loader2, Square, Spline, Table,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { IrNode } from "@/lib/types";
import { cn } from "@/lib/utils";

export type IrDeriveState = "idle" | "deriving" | "ready" | "error";

const KIND_ICON = {
  shape: Square,
  group: Group,
  connector: Spline,
  table: Table,
  media: Image,
  preserved: Archive,
  node: Box,
} as const;

const pathKey = (path: number[] | null) => (path ? path.join(".") : "");

function samePath(a: number[] | null, b: number[] | null): boolean {
  if (!a || !b) return false;
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

interface RowProps {
  node: IrNode;
  depth: number;
  focusPath: number[] | null;
  onFocus: (path: number[] | null) => void;
  collapsed: Set<string>;
  onToggle: (key: string) => void;
}

function Row({ node, depth, focusPath, onFocus, collapsed, onToggle }: RowProps) {
  const Icon = KIND_ICON[node.kind] ?? Box;
  const key = pathKey(node.path);
  const isCollapsed = collapsed.has(key);
  const focused = samePath(node.path, focusPath);
  const rowRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (focused) rowRef.current?.scrollIntoView({ block: "nearest" });
  }, [focused]);

  return (
    <>
      <div
        className={cn(
          "group flex items-center gap-1 rounded-md pr-2 text-[13px]",
          focused ? "bg-primary/10 text-foreground" : "text-foreground/90",
        )}
        style={{ paddingLeft: `${depth * 14 + 4}px` }}
      >
        {node.children.length > 0 ? (
          <button
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent"
            aria-label={isCollapsed ? "Expand" : "Collapse"}
            onClick={() => onToggle(key)}
          >
            {isCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="w-5 shrink-0" />
        )}
        <button
          ref={rowRef}
          disabled={!node.path}
          onClick={() => node.path && onFocus(node.path)}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left",
            node.path ? "cursor-pointer" : "cursor-default opacity-80",
          )}
          title={node.path ? "Show on the slide" : undefined}
        >
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate">{node.label}</span>
          {node.fallback && (
            <Badge variant="secondary" className="shrink-0 px-1 py-0 text-[10px] font-normal">
              picture
            </Badge>
          )}
          {node.box && (
            <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
              {node.box.w}×{node.box.h}
            </span>
          )}
        </button>
      </div>
      {!isCollapsed &&
        node.children.map((child, i) => (
          <Row
            key={child.path ? pathKey(child.path) : `n-${i}`}
            node={child}
            depth={depth + 1}
            focusPath={focusPath}
            onFocus={onFocus}
            collapsed={collapsed}
            onToggle={onToggle}
          />
        ))}
    </>
  );
}

interface Props {
  state: IrDeriveState;
  tree: IrNode[] | null;
  error?: string;
  focusPath: number[] | null;
  onFocus: (path: number[] | null) => void;
}

/**
 * The selected slide's IR, derived automatically from the live slide
 * (host capture + the desktop extraction) whenever the slide settles.
 * Rows map back to preview elements by DOM path where provenance
 * allows; clicking one focuses it on the stage.
 */
export function IrTree(p: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 px-4 pt-3 pb-1 text-xs text-muted-foreground">
        {p.state === "deriving" ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Deriving from the live slide…
          </>
        ) : p.state === "error" ? (
          <span className="text-destructive">Could not derive the IR{p.error ? `: ${p.error}` : ""}</span>
        ) : (
          <span>The slide's IR, derived from the live layout as you edit.</span>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {p.tree && p.tree.length > 0 ? (
          p.tree.map((node, i) => (
            <Row
              key={node.path ? pathKey(node.path) : `n-${i}`}
              node={node}
              depth={0}
              focusPath={p.focusPath}
              onFocus={p.onFocus}
              collapsed={collapsed}
              onToggle={toggle}
            />
          ))
        ) : p.state !== "deriving" ? (
          <p className="px-2 pt-2 text-sm text-muted-foreground">
            Nothing derived yet. The tree appears once the slide has content the extractor can map.
          </p>
        ) : null}
      </div>
    </div>
  );
}
