import en from "../features/listing-editor/en.json";
import ar from "../features/listing-editor/ar.json";
import "../features/listing-editor/styles.css";
const sellers = ["buyer", "private_seller", "dealer", "brand"] as const;
export default {
  lane: "L03",
  namespace: "listing-editor",
  routes: [
    { path: "/seller/listings", roles: [...sellers], area: "seller" },
    { path: "/seller/listings/:id", roles: [...sellers], area: "seller" },
  ],
  navigation: [
    {
      id: "seller-listings",
      href: "/seller/listings",
      label: { en: "My listings", ar: "إعلاناتي" },
      order: 30,
      area: "seller",
      roles: [...sellers],
    },
  ],
  dictionaries: { en, ar },
  gateway: [
    // Listing fee review consumes Pricing's owner-private versioned API.
    // Pricing, not this registration or the browser, validates quote authority.
    {
      service: "pricing",
      path: "/v1/quotes",
      methods: ["POST"],
      roles: [...sellers],
    },
    {
      service: "catalog",
      path: "/v1/seller/listings",
      methods: ["GET", "POST"],
      roles: [...sellers],
    },
    {
      service: "catalog",
      path: "/v1/seller/listings/:id",
      methods: ["GET", "PUT"],
      roles: [...sellers],
    },
    {
      service: "catalog",
      path: "/v1/seller/listings/:id/publish",
      methods: ["POST"],
      roles: [...sellers],
    },
    {
      service: "catalog",
      path: "/v1/seller/listings/:id/media",
      methods: ["GET", "POST"],
      roles: [...sellers],
      maxBodyBytes: 8500000,
    },
    {
      service: "catalog",
      path: "/v1/seller/listings/:id/media/:asset",
      methods: ["GET", "DELETE"],
      roles: [...sellers],
      maxResponseBytes: 8500000,
    },
    {
      service: "catalog",
      path: "/v1/seller/listings/:id/gallery",
      methods: ["PUT"],
      roles: [...sellers],
    },
    {
      service: "catalog",
      path: "/v1/listings/:id/report-subject",
      methods: ["GET"],
      roles: [...sellers, "operator"],
    },
    {
      service: "catalog",
      path: "/v1/listings/:id/publication",
      methods: ["GET"],
      roles: ["public"],
    },
    {
      service: "catalog",
      path: "/v1/listings/:id/photos/:asset/:variant",
      methods: ["GET"],
      roles: ["public"],
      maxResponseBytes: 8500000,
    },
    {
      service: "catalog",
      path: "/v1/listings/:id/photo-credits",
      methods: ["GET"],
      roles: ["public"],
    },
    {
      service: "communications",
      path: "/v1/seller/workspace",
      methods: ["GET"],
      roles: [...sellers],
    },
  ],
  slots: [],
} satisfies import("../registry-types").Registration;
