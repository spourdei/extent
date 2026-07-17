import type { Metadata } from "next";

import { WorkspaceShell } from "../../components/workspace-shell";
import { adaptSampleWorkspace } from "../../lib/sample-model";
import { getSampleWorkspaceData } from "../../src/server/sample-query-service";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const metadata: Metadata = {
  description:
    "Explore a prepared set of fictional documents and see how Extent presents findings, exact quotes, and source details.",
  title: "Prepared evidence sample",
};

export default async function SamplePage() {
  const model = adaptSampleWorkspace(await getSampleWorkspaceData());
  return (
    <WorkspaceShell
      coverageLabel={model.coverageLabel}
      evidence={model.evidence}
      files={model.files}
      folderTitle={model.folderTitle}
      mode="sample"
      questions={model.questions}
      readyFiles={model.readyFiles}
      totalFiles={model.totalFiles}
    />
  );
}
