// Page-level accessibility checks. Each test renders a page in
// isolation (with a stubbed broker / audit response) and runs axe-core
// against the result. Any AA-level violation fails the build.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import Layout from "../components/Layout";
import Login from "../components/Login";
import PolicyPreCheckPanel from "../components/PolicyPreCheckPanel";
import ServiceCard from "../components/ServiceCard";
import StatusPill from "../components/StatusPill";
import Catalog from "../pages/Catalog";
import Instances from "../pages/Instances";
import type { CatalogResponse, ServiceInstance } from "../types/api";

expect.extend(toHaveNoViolations);

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity },
    },
  });
}

function wrap(ui: React.ReactNode) {
  return (
    <QueryClientProvider client={makeClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={ui} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// Minimal happy-path catalog payload used by the catalog test.
const CATALOG: CatalogResponse = {
  services: [
    {
      id: "sovereign-envoy-lb",
      name: "Self-Service Load Balancer",
      description: "Compliance-checked Envoy LB with regional and multi-region plans.",
      pack: "chassis",
      bindable: true,
      plans: [
        { id: "standard-regional", name: "Standard Regional", description: "One region" },
        { id: "multi-region", name: "Multi Region", description: "Active-active" },
      ],
      compliance_controls: ["AC-6", "AU-2", "SC-8", "SC-13"],
    },
  ],
  packs: [
    { id: "chassis", name: "Base chassis", installed: true, description: "Always-on base services." },
    { id: "ai", name: "AI Pack", installed: false, description: "Inference, RAG, GPU pool." },
  ],
};

const INSTANCES: ServiceInstance[] = [
  {
    instance_id: "demo-lb-a",
    service_id: "sovereign-envoy-lb",
    plan_id: "standard-regional",
    organization_guid: "agency-x",
    space_guid: null,
    status: "succeeded",
    version: 1,
    created_at: "2026-05-24T01:00:00Z",
    updated_at: "2026-05-24T01:00:00Z",
    parameters: {},
    pack: "chassis",
  },
];

const originalFetch = globalThis.fetch;

beforeEach(() => {
  // Stub fetch so the queries resolve synchronously.
  globalThis.fetch = (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (url.includes("/v2/catalog")) {
      return Promise.resolve(new Response(JSON.stringify(CATALOG), { status: 200, headers: { "content-type": "application/json" } }));
    }
    if (url.includes("/v2/instances")) {
      return Promise.resolve(new Response(JSON.stringify({ instances: INSTANCES }), { status: 200, headers: { "content-type": "application/json" } }));
    }
    return Promise.resolve(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
  };
  // Ensure the layout believes a user is signed in.
  sessionStorage.setItem(
    "sovereign-auth",
    JSON.stringify({ type: "bearer", value: "test", label: "test" }),
  );
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  sessionStorage.clear();
});

describe("Accessibility (axe-core)", () => {
  it("Login screen has no violations", async () => {
    const { container } = render(<Login />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("Layout shell has no violations", async () => {
    const { container } = render(wrap(<p>Page body</p>));
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("Catalog page (with sample data) has no violations", async () => {
    const { container, findByText } = render(wrap(<Catalog />));
    await findByText("Self-Service Load Balancer");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("Instances page has no violations", async () => {
    const { container, findByText } = render(wrap(<Instances />));
    await findByText("demo-lb-a");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("Service card has no violations", async () => {
    const { container } = render(
      <MemoryRouter>
        <ServiceCard service={CATALOG.services[0]} />
      </MemoryRouter>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("Status pill renders meaningful aria label", async () => {
    const { container, getByLabelText } = render(<StatusPill status="succeeded" />);
    expect(getByLabelText(/status:/i)).toBeInTheDocument();
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("Policy pre-check (deny) has no violations", async () => {
    const { container } = render(
      <PolicyPreCheckPanel
        decision={{
          allow: false,
          denies: ["SC-8: TLS must be enabled"],
          matched_layers: ["base"],
        }}
        loading={false}
        error={null}
      />,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
