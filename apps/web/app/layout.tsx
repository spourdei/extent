import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  description:
    "Connect a Google Drive folder, ask questions across its documents, and inspect the exact quotes behind each finding. Extent also shows when sources disagree or files could not be checked.",
  openGraph: {
    description:
      "Connect a Google Drive folder, ask questions across its documents, and inspect the exact quotes behind each finding. Extent also shows when sources disagree or files could not be checked.",
    siteName: "Extent",
    title: "Extent | Answers backed by exact source quotes",
    type: "website",
  },
  title: {
    default: "Extent | Answers backed by exact source quotes",
    template: "%s | Extent",
  },
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#faf8f5",
  viewportFit: "cover",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html data-scroll-behavior="smooth" lang="en">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
