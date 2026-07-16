import type { Metadata } from "next";

import { LiveWorkspace } from "../../../components/live-workspace";

export const metadata: Metadata = {
  title: "Folder workspace",
};

export default async function WorkspacePage({
  params,
}: {
  params: Promise<{ readonly id: string }>;
}) {
  const { id } = await params;
  return <LiveWorkspace workspaceId={id} />;
}
