import { useEffect, useRef } from "react";

import {
  mountLineageField,
  type FieldData,
  type FieldNode,
  type LineageFieldHandle,
} from "./lineage-field";

type Props = {
  /** "ambient" = decorative hero field, "interactive" = orbit / hover / click. */
  mode?: "ambient" | "interactive";
  /** Live catalog. Omit for the deterministic showcase constellation. */
  data?: FieldData | null;
  motion?: "Flowing" | "Calm" | "Still";
  className?: string;
  /** URN to keep highlighted from outside (e.g. restored selection). */
  selectedUrn?: string | null;
  /** Free-text filter; non-matching nodes dim instead of unmounting. */
  query?: string;
  onSelect?: (node: FieldNode | null) => void;
  onVisibleCount?: (visible: number) => void;
};

/**
 * React shell around the imperative WebGL field. The renderer is created once
 * per mount; data, query, and selection are pushed in through the handle so a
 * catalog refresh never rebuilds the canvas or resets the camera.
 */
export default function LineageField({
  mode = "ambient",
  data = null,
  motion = "Flowing",
  className,
  selectedUrn = null,
  query = "",
  onSelect,
  onVisibleCount,
}: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const handleRef = useRef<LineageFieldHandle | null>(null);
  const selectRef = useRef(onSelect);
  const countRef = useRef(onVisibleCount);
  selectRef.current = onSelect;
  countRef.current = onVisibleCount;

  useEffect(() => {
    if (!hostRef.current) return undefined;
    const handle = mountLineageField(hostRef.current, {
      mode,
      motion,
      data,
      onSelect: (node) => selectRef.current?.(node),
      onCount: (visible) => countRef.current?.(visible),
    });
    handleRef.current = handle;
    return () => {
      handle.dispose();
      handleRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, motion]);

  useEffect(() => {
    if (data && data.nodes.length) handleRef.current?.setData(data);
  }, [data]);

  useEffect(() => {
    handleRef.current?.setQuery(query);
  }, [query]);

  useEffect(() => {
    handleRef.current?.select(selectedUrn ?? null);
  }, [selectedUrn]);

  return <div ref={hostRef} className={className ?? "lineage-field"} aria-hidden="true" />;
}
