"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { ProductHeader } from "./product-header";

export function ConnectFlow({
  initialAuthResult,
}: {
  initialAuthResult: string | null;
  initialReferenceId: string | null;
}) {
  const [folderUrl, setFolderUrl] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const submitFolder = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (folderUrl.trim().length === 0) return;
    setSubmitted(true);
  };

  return (
    <div className="public-page">
      <ProductHeader action={<Link href="/">About Extent</Link>} />
      <main className="connect" id="main-content">
        <section className="connect__panel" aria-labelledby="connect-title">
          <p className="micro-label">Read-only Google Drive access</p>
          <h1 id="connect-title">Connect the folder you want to question.</h1>
          <p>
            Extent opens files through the connected Google account. It does not request
            permission to edit Drive content.
          </p>
          {initialAuthResult && initialAuthResult !== "success" ? (
            <p role="alert">Google sign-in did not finish. Starting again is safe.</p>
          ) : null}
          <a className="button button--primary" href="/api/backend/v1/auth/google/start">
            Connect Google Drive
          </a>
          <form onSubmit={submitFolder}>
            <label htmlFor="folder-url">Google Drive folder link</label>
            <input
              id="folder-url"
              onChange={(event) => setFolderUrl(event.target.value)}
              placeholder="https://drive.google.com/drive/folders/…"
              type="url"
              value={folderUrl}
            />
            <button className="button" type="submit">
              Check folder
            </button>
          </form>
          {submitted ? (
            <p aria-live="polite">Checking access and preparing the supported files.</p>
          ) : null}
        </section>
      </main>
    </div>
  );
}
