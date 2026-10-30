/** Order in which the clip list and the texts/stickers were edited, so undo and redo go back and forth in that
 *  order across both. Each list keeps its own history; this only remembers which one to ask. */
export type Kind = "clips" | "ov";

export type EditLog = {
  undo: Kind[];                                 // newest last
  redo: Kind[];
  clearFuture: Partial<Record<Kind, () => void>>;
};

export const newEditLog = (): EditLog => ({ undo: [], redo: [], clearFuture: {} });

/** A new undo step was made in `kind`: it ends every redo path (also in the other list). */
export function logStep(log: EditLog, kind: Kind) {
  log.undo.push(kind);
  log.redo = [];
  for (const k of ["clips", "ov"] as Kind[]) if (k !== kind) log.clearFuture[k]?.();
}

/** A list tells the log how to drop its own redo path; returns the function that takes it back. */
export function registerClear(log: EditLog, kind: Kind, fn: () => void): () => void {
  log.clearFuture[kind] = fn;
  return () => { delete log.clearFuture[kind]; };
}
