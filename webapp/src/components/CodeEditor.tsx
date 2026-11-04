import { useMemo, useRef } from "react";
import { File } from "@pierre/diffs/react";
import type { FileContents } from "@pierre/diffs";

interface Props {
  value: string;
  onChange: (value: string) => void;
  dark: boolean;
  language?: "html" | "css";
  /** Stable identity for this editing surface; retains undo history. */
  stateKey: string;
}

/**
 * Code surface from Pierre's diffs library (the edit mode behind
 * diffs.com/edit): Shiki highlighting, virtualized rendering, and a real
 * text editor attached to the rendered file. No diff UI, no file tree.
 *
 * The editor owns the live document during a session, so the `file` prop
 * is the contents at mount and edits stream out through onEditChange
 * instead of being fed back in. Parents remount (key change) to load a
 * different document.
 */
export function CodeEditor({ value, onChange, dark, language = "html", stateKey }: Props) {
  const initial = useRef(value);
  const file = useMemo<FileContents>(
    () => ({
      name: language === "css" ? "deck.css" : "slide.html",
      contents: initial.current,
      lang: language,
      cacheKey: stateKey,
    }),
    // Mount-scoped by design; see the note above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const options = useMemo(
    () => ({
      theme: { dark: "pierre-dark", light: "pierre-light" },
      themeType: dark ? ("dark" as const) : ("light" as const),
      disableFileHeader: true,
      overflow: "wrap" as const,
    }),
    [dark],
  );

  return (
    <div className="h-full w-full overflow-hidden bg-background">
      <File
        file={file}
        options={options}
        edit
        editStateKey={stateKey}
        onEditChange={(event) => onChange(event.file.contents)}
        onEditComplete={(event) => {
          onChange(event.file.contents);
          return "accept";
        }}
        style={{ height: "100%" }}
      />
    </div>
  );
}
