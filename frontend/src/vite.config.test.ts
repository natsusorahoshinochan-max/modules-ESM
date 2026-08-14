import { describe, expect, it } from "vitest";
import config from "../vite.config";

describe("current public development proxy", () => {
  it("upgrades run-scoped /api WebSockets without a legacy /ws path", () => {
    const proxy = config.server!.proxy!;
    expect(proxy["/api"]).toMatchObject({
      target: "http://127.0.0.1:8000",
      ws: true,
    });
    expect(proxy).not.toHaveProperty("/ws");
  });
});
