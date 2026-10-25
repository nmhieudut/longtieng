"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ProjectView } from "@/components/project/project-view";

function Inner() {
  const id = useSearchParams().get("id") ?? "";
  return <ProjectView key={id} id={id} />;
}

export default function ProjectPage() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
