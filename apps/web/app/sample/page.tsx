import type { Metadata } from "next";

import { InteractiveSampleWorkspace } from "../../components/interactive-sample-workspace";
import { adaptSampleWorkspace } from "../../lib/sample-model";
import { getSampleWorkspaceData } from "../../src/server/sample-query-service";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const metadata: Metadata = {
  description:
    "Ask questions across the public Alder Peak renewal sample and inspect exact source evidence.",
  title: "Interactive Alder Peak sample",
};

export default async function SamplePage() {
  const model = adaptSampleWorkspace(await getSampleWorkspaceData());
  return <InteractiveSampleWorkspace model={model} />;
}
