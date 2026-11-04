import en from "../features/business/en.json";
import ar from "../features/business/ar.json";
import "../features/business/styles.css";
export default {
  lane: "L02",
  namespace: "business",
  dictionaries: { en, ar },
  routes: [
    { path: "/business", roles: ["public"], area: "storefront" },
    {
      path: "/business/contacts",
      roles: ["buyer", "private_seller", "dealer", "brand", "operator"],
      area: "account",
    },
    {
      path: "/business/review-history",
      roles: ["buyer", "private_seller", "operator"],
      area: "account",
    },
    {
      path: "/business/membership",
      roles: ["dealer", "brand", "operator"],
      area: "seller",
    },
    { path: "/operations/verification", roles: ["operator"], area: "operator" },
  ],
  navigation: [
    {
      id: "official-businesses",
      href: "/business",
      label: { en: "Official businesses", ar: "الأعمال الرسمية" },
      order: 30,
      area: "storefront",
      roles: ["public"],
    },
  ],
  gateway: [
    {
      service: "identity",
      path: "/v1/businesses",
      methods: ["GET"],
      roles: ["public"],
    },
    {
      service: "identity",
      path: "/v1/businesses/:id",
      methods: ["GET"],
      roles: ["public"],
    },
    {
      service: "identity",
      path: "/v1/businesses",
      methods: ["POST"],
      roles: ["operator"],
    },
    {
      service: "identity",
      path: "/v1/businesses/:id",
      methods: ["PATCH"],
      roles: ["operator"],
    },
    {
      service: "identity",
      path: "/v1/businesses/manage/records",
      methods: ["GET"],
      roles: ["operator"],
    },
    {
      service: "identity",
      path: "/v1/businesses/:id/memberships",
      methods: ["GET"],
      roles: ["dealer", "brand", "operator"],
    },
    {
      service: "identity",
      path: "/v1/memberships",
      methods: ["POST"],
      roles: ["operator"],
    },
    {
      service: "identity",
      path: "/v1/memberships/:id",
      methods: ["PATCH"],
      roles: ["operator"],
    },
    {
      service: "identity",
      path: "/v1/contacts",
      methods: ["GET"],
      roles: ["buyer", "private_seller", "dealer", "brand", "operator"],
    },
    {
      service: "identity",
      path: "/v1/contacts/challenges",
      methods: ["POST"],
      roles: ["buyer", "private_seller", "dealer", "brand", "operator"],
    },
    {
      service: "identity",
      path: "/v1/contacts/challenges/:id/verify",
      methods: ["POST"],
      roles: ["buyer", "private_seller", "dealer", "brand", "operator"],
    },
    {
      service: "identity",
      path: "/v1/contacts/challenges/:id/sample-code",
      methods: ["GET"],
      roles: ["buyer", "private_seller", "dealer", "brand", "operator"],
    },
    {
      service: "identity",
      path: "/v1/private-reviews",
      methods: ["GET", "POST"],
      roles: ["operator"],
    },
    {
      service: "identity",
      path: "/v1/private-reviews/mine",
      methods: ["GET"],
      roles: ["buyer", "private_seller", "operator"],
    },
    {
      service: "identity",
      path: "/v1/private-reviews/:id",
      methods: ["GET"],
      roles: ["buyer", "private_seller", "operator"],
    },
    {
      service: "identity",
      path: "/v1/private-reviews/:id/verdict",
      methods: ["POST"],
      roles: ["operator"],
    },
    {
      service: "identity",
      path: "/v1/private-reviews/:id/evidence",
      methods: ["GET"],
      roles: ["operator"],
    },
    {
      service: "identity",
      path: "/v1/private-reviews/:id/files/:file",
      methods: ["GET"],
      roles: ["operator"],
      maxResponseBytes: 2097152,
    },
    {
      service: "identity",
      path: "/v1/private-reviews/:id/reassign",
      methods: ["POST"],
      roles: ["operator"],
    },
  ],
  slots: [],
} satisfies import("../registry-types").Registration;
