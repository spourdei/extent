import { ProductHeader } from "../components/product-header";

export default function Loading() {
  return (
    <div className="public-page">
      <ProductHeader action={<span>Opening Extent</span>} />
      <main className="route-state" id="main-content">
        <div aria-live="polite" className="route-state__content">
          <span aria-hidden="true" className="busy-dot" />
          <div>
            <h1>Opening Extent</h1>
            <p>Loading the latest folder and file status.</p>
          </div>
        </div>
      </main>
    </div>
  );
}
