"use client";

import Link from "next/link";

const features = [
  {
    title: "Repeat buyers & history",
    href: "/customer-genome/repeat-buyers",
    body: "See who has bought twice or more, search any customer and open their authoritative order timeline.",
  },
  {
    title: "Restore product",
    href: "/customer-genome/product-interests",
    body: "Keep a waiting list per product variant and add customers from their profile or a bubble.",
  },
  {
    title: "Restock events",
    href: "/customer-genome/restock-events",
    body: "A variant coming back in stock is detected and shown to the owner. Nothing is sent until you confirm a batch.",
  },
];

export function GenomeOverview() {
  return (
    <section className="screen" aria-labelledby="screen-title">
      <div className="screen-heading">
        <div>
          <p className="eyebrow">MODULE 1</p>
          <h1 id="screen-title">Customer genome</h1>
          <p className="muted">
            Know your buyers, recognise them when they message, and win them back when a product
            returns.
          </p>
        </div>
      </div>
      <div className="cg-cards">
        {features.map((feature) => (
          <Link className="data-card cg-card" href={feature.href} key={feature.href}>
            <strong>{feature.title}</strong>
            <p className="muted">{feature.body}</p>
            <span className="cg-link">Open</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
