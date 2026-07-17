"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { ProductHeader } from "../../components/product-header";

export default function SampleError({ reset }: { reset: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <div className="public-page">
      <ProductHeader action={<span>Sample unavailable</span>} />
      <main className="route-state" id="main-content" role="alert">
        <div className="route-state__content">
          <div>
            <h1 ref={headingRef} tabIndex={-1}>
              Extent couldn’t open the prepared sample.
            </h1>
            <p>Extent did not show a partial result. Try loading the sample again.</p>
            <div className="intro__actions">
              <button className="button button--primary" onClick={reset} type="button">
                Try the sample again
              </button>
              <Link className="text-link" href="/">
                Return home
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
