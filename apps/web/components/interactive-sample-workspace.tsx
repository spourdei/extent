"use client";

import { useRef } from "react";

import { askDemoQuestion } from "../lib/api";
import type { SampleWorkspaceModel } from "../lib/sample-model";
import { WorkspaceShell } from "./workspace-shell";

export function InteractiveSampleWorkspace({ model }: { model: SampleWorkspaceModel }) {
  const questionRequest = useRef<{ key: string; question: string } | null>(null);

  return (
    <WorkspaceShell
      coverageLabel={model.coverageLabel}
      evidence={model.evidence}
      files={model.files}
      folderTitle={model.folderTitle}
      mode="sample"
      onAsk={async (question) => {
        if (questionRequest.current?.question !== question) {
          questionRequest.current = { key: crypto.randomUUID(), question };
        }
        const result = await askDemoQuestion(question, questionRequest.current.key);
        questionRequest.current = null;
        return result;
      }}
      questions={model.questions}
      readyFiles={model.readyFiles}
      totalFiles={model.totalFiles}
    />
  );
}
