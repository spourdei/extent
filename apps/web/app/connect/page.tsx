import type { Metadata } from "next";

import { ConnectFlow } from "../../components/connect-flow";

export const metadata: Metadata = {
  description:
    "Connect Google Drive with read-only access, then choose the folder you want Extent to check.",
  title: "Connect Google Drive",
};

export default async function ConnectPage({
  searchParams,
}: {
  searchParams: Promise<{
    readonly auth?: string | readonly string[];
    readonly ref?: string | readonly string[];
  }>;
}) {
  const parameters = await searchParams;
  return (
    <ConnectFlow
      initialAuthResult={typeof parameters.auth === "string" ? parameters.auth : null}
      initialReferenceId={typeof parameters.ref === "string" ? parameters.ref : null}
    />
  );
}
