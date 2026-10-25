"use client";

import { useCallback, useEffect, useState } from "react";

import { api, isActive, type Project } from "@/lib/api";

/** Loads a project and keeps polling while it is processing. */
export function useProject(id: string) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    api.get(id).then((p) => live && setProject(p)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);

  useEffect(() => {
    if (!project || !isActive(project)) return;
    let live = true;
    const t = setTimeout(() => {
      api.get(id)
        .then((p) => live && setProject(p))
        .catch(() => live && setTimeout(() => live && setTick((n) => n + 1), 2000));
    }, 1000);
    return () => { live = false; clearTimeout(t); };
  }, [project, id, tick]);

  const apply = useCallback((p: Project) => setProject(p), []);
  return { project, error, apply };
}
