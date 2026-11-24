// Pure helper for the table viewer's row-detail panel. No React and no imports, so
// Node can test it. Values are passed through unchanged: the grid may visually
// shorten long cells, but this detail always carries the complete stored value.

export interface DetailCellInput {
  column: string;
  value: string;
  coord: string | null;
  formula: string | null;
  noCachedValue: boolean;
  truncated: boolean;
}

export interface DetailEntry {
  key: string; // working column key
  label: string; // raw header text when known, else the key
  value: string; // complete stored value (never shortened)
  present: boolean; // false when the row has no cell for this column
  coord: string | null;
  formula: string | null;
  noCachedValue: boolean;
  truncatedAtExtraction: boolean; // the EXTRACTOR capped the cell (MAX_CELL_CHARS)
}

/**
 * Every column of the sheet, in order, with this row's complete value. Cells whose
 * column is not in `columns` are appended at the end so nothing is dropped.
 */
export function rowDetail(
  cells: DetailCellInput[],
  columns: string[],
  headers: string[] | null,
): DetailEntry[] {
  const byColumn = new Map(cells.map((c) => [c.column, c]));
  const entry = (key: string, label: string): DetailEntry => {
    const c = byColumn.get(key);
    return {
      key,
      label,
      value: c ? c.value : "",
      present: Boolean(c),
      coord: c?.coord ?? null,
      formula: c?.formula ?? null,
      noCachedValue: c?.noCachedValue ?? false,
      truncatedAtExtraction: c?.truncated ?? false,
    };
  };
  const out = columns.map((key, i) => entry(key, headers?.[i] || key));
  const known = new Set(columns);
  for (const c of cells) {
    if (!known.has(c.column)) out.push(entry(c.column, c.column));
  }
  return out;
}
