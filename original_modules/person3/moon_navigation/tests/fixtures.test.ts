import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { UpstreamSitesResponseSchema } from "../src/server/schemas";

const load = (n: string) => JSON.parse(readFileSync(new URL(`../fixtures/${n}`, import.meta.url), "utf8"));

describe("shared fixtures stay valid against the contract", () => {
  it("sites.mock.json parses as the Site Output list", () => {
    expect(UpstreamSitesResponseSchema.safeParse(load("sites.mock.json")).success).toBe(true);
  });
  it("route example has the Route Output fields", () => {
    const r = load("route_response.example.json");
    for (const k of ["route_id", "generated_at_utc", "data_status", "frame", "alternatives", "operational_validity"]) {
      expect(r).toHaveProperty(k);
    }
    expect(r.frame).toBe("IAU_MOON_ME");
  });
  it("error example uses the standard error envelope", () => {
    const e = load("error.out_of_coverage.example.json");
    expect(e.error.code).toBe("OUT_OF_COVERAGE");
    expect(e).toHaveProperty("request_id");
    expect(e).toHaveProperty("timestamp_utc");
  });
});
