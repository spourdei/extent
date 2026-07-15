import Link from "next/link";
import type { ReactNode } from "react";

export function Wordmark({ link = true }: { link?: boolean }) {
  const content = (
    <>
      <span aria-hidden="true" className="brand-tile">
        E
      </span>
      <span>Extent</span>
    </>
  );
  return link ? (
    <Link className="wordmark" href="/">
      {content}
    </Link>
  ) : (
    <div className="wordmark">{content}</div>
  );
}

export function ProductHeader({
  action,
  context,
}: {
  action?: ReactNode;
  context?: ReactNode;
}) {
  return (
    <header className="product-header">
      <div className="product-header__brand">
        <Wordmark />
        {context ? <div className="product-header__context">{context}</div> : null}
      </div>
      {action ? <div className="product-header__action">{action}</div> : null}
    </header>
  );
}
