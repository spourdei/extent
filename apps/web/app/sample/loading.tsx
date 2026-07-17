import { ProductHeader } from "../../components/product-header";

export default function SampleLoading() {
  return (
    <div className="public-page">
      <ProductHeader action={<span>Opening the prepared sample</span>} />
      <main className="route-state" id="main-content">
        <div aria-live="polite" className="route-state__content">
          <span aria-hidden="true" className="busy-dot" />
          <div>
            <h1>Opening the prepared sample</h1>
            <p>Loading the public Alder Peak packet and its prepared finding.</p>
          </div>
        </div>
      </main>
    </div>
  );
}
