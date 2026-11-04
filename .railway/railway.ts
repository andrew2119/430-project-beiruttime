import { readFileSync } from "node:fs";
import {
  defineRailway, github, postgres, project, service, volume,
  type BuildConfig, type DeployConfig,
} from "railway/iac";

// Per-service deployment descriptors are data, not deprecated railway.json files.
// New Railway services use this project-level IaC entry point instead.
function deployment(name: string): { build: BuildConfig; deploy: DeployConfig } {
  return JSON.parse(readFileSync(new URL(`../infra/railway/${name}.json`, import.meta.url), "utf8"));
}

export default defineRailway(() => {
  const source = github("andrew2119/430-project-beiruttime", {
    branch: "main",
    checkSuites: false,
  });
  const names = [
    "identity", "catalog", "auction", "pricing", "orders", "eligibility",
    "trust", "communications", "service-operations", "web",
  ];
  const apps = names.map((name) => {
    const config = deployment(name);
    return service(name, {
      source,
      build: { buildEnvironment: "V3", ...config.build },
      deploy: config.deploy,
      replicas: { "us-west2": 1 },
    });
  });
  const database = postgres("Postgres", { region: "us-west2" });
  database.networking = { privateNetworkEndpoint: "postgres" };
  const storage = volume("postgres-volume", {
    region: "us-west2",
    sizeMB: 50000,
    allowOnlineResize: true,
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
  });

  return project("beirut-time", {
    // Secrets and environment variables stay in Railway, never in this graph.
    variables: { managed: false },
    resources: [...apps, database, storage],
  });
});
