import Link from "next/link";

import { ProductHeader } from "../components/product-header";

export default function NotFound() {
  return (
    <div className="public-page">
      <ProductHeader action={<span>Page not found</span>} />
      <main className="route-state" id="main-content">
        <div className="route-state__content">
          <div>
            <h1>There’s no Extent workspace at this address.</h1>
            <p>You can open the prepared sample or connect a Google Drive folder.</p>
            <div className="intro__actions">
              <Link className="button button--primary" href="/connect">
                Connect Google Drive
              </Link>
              <Link className="text-link" href="/sample">
                Open the sample
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
