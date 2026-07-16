"use client";

import { useEffect, useRef } from "react";

import { ProductHeader } from "../components/product-header";

export default function ErrorPage({ reset }: { reset: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <div className="public-page">
      <ProductHeader action={<span>Page unavailable</span>} />
      <main className="route-state" id="main-content" role="alert">
        <div className="route-state__content">
          <div>
            <h1 ref={headingRef} tabIndex={-1}>
              Extent couldn’t open this page.
            </h1>
            <p>
              Extent did not show a partial evidence result. Try again or open the prepared
              sample.
            </p>
            <button className="button button--primary" onClick={reset} type="button">
              Try again
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
