/**
 * Multi-Instance Agent Manager
 *
 * Manages multiple SPSI flow runners with controlled intervals.
 * Designed for running many agents concurrently with ~1s spacing.
 */

import { type FlowResult, SpsiFlowRunner, type RunnerConfig, SPSI_CONFIG } from "./spsi-flow-runner.js";

export interface AgentInstance {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  result?: FlowResult;
  startedAt?: string;
  finishedAt?: string;
}

export interface ManagerConfig {
  intervalMs: number;
  maxConcurrent: number;
  headless?: boolean;
  stopOnFirstFailure?: boolean;
}

export interface ManagerResult {
  totalInstances: number;
  successful: number;
  failed: number;
  duration: number;
  results: FlowResult[];
}

export class MultiAgentManager {
  private config: ManagerConfig;
  private instances: Map<string, AgentInstance> = new Map();
  private queue: string[] = [];
  private running: Set<string> = new Set();
  private stopRequested: boolean = false;

  constructor(config: Partial<ManagerConfig> = {}) {
    this.config = {
      intervalMs: config.intervalMs ?? 1000,
      maxConcurrent: config.maxConcurrent ?? 3,
      headless: config.headless ?? true,
      stopOnFirstFailure: config.stopOnFirstFailure ?? false
    };
  }

  async run(count: number): Promise<ManagerResult> {
    const startTime = Date.now();
    const results: FlowResult[] = [];
    this.stopRequested = false;

    console.log("=".repeat(60));
    console.log("  Multi-Agent Manager");
    console.log("=".repeat(60));
    console.log(`Instances: ${count}`);
    console.log(`Interval: ${this.config.intervalMs}ms`);
    console.log(`Max Concurrent: ${this.config.maxConcurrent}`);
    console.log(`Headless: ${this.config.headless}`);
    console.log("");

    // Create all instance IDs
    const ids: string[] = [];
    for (let i = 0; i < count; i++) {
      const id = `agent-${Date.now()}-${i}`;
      ids.push(id);
      this.instances.set(id, { id, status: "pending" });
      this.queue.push(id);
    }

    // Process queue
    while (this.queue.length > 0 || this.running.size > 0) {
      if (this.stopRequested) {
        console.log("\n⚠ Stop requested - aborting remaining instances");
        break;
      }

      // Start available instances up to maxConcurrent
      while (this.running.size < this.config.maxConcurrent && this.queue.length > 0) {
        const id = this.queue.shift()!;
        this.startInstance(id);
      }

      // Wait a bit before checking again
      await this.sleep(100);
    }

    // Collect results
    for (const instance of this.instances.values()) {
      if (instance.result) {
        results.push(instance.result);
      }
    }

    const duration = Date.now() - startTime;
    const successful = results.filter(r => r.success).length;
    const failed = results.filter(r => !r.success).length;

    return {
      totalInstances: count,
      successful,
      failed,
      duration,
      results
    };
  }

  private async startInstance(id: string): Promise<void> {
    const instance = this.instances.get(id);
    if (!instance) return;

    instance.status = "running";
    instance.startedAt = new Date().toISOString();
    this.running.add(id);

    const config: RunnerConfig = {
      headless: this.config.headless,
      instanceId: id
    };

    const runner = new SpsiFlowRunner(config);

    // Run in background
    this.runInstance(id, runner).catch(console.error);
  }

  private async runInstance(id: string, runner: SpsiFlowRunner): Promise<void> {
    try {
      const result = await runner.run();

      const instance = this.instances.get(id);
      if (instance) {
        instance.status = result.success ? "completed" : "failed";
        instance.result = result;
        instance.finishedAt = new Date().toISOString();
      }

      // Progress indicator
      const icon = result.success ? "✓" : "✗";
      const totalDone = [...this.instances.values()].filter(i => i.status !== "pending" && i.status !== "running").length;
      console.log(`${icon} [${result.instanceId}] ${result.success ? "SUCCESS" : "FAILED"} - ${result.steps.filter(s => s.passed).length}/${result.steps.length} steps (${result.steps.reduce((s, st) => s + st.duration, 0)}ms)`);

      if (this.config.stopOnFirstFailure && !result.success) {
        this.stopRequested = true;
        // Mark remaining as abandoned
        for (const remainingId of this.queue) {
          const inst = this.instances.get(remainingId);
          if (inst) inst.status = "failed";
        }
        this.queue = [];
      }

    } catch (error) {
      console.error(`Instance ${id} crashed:`, error);
      const instance = this.instances.get(id);
      if (instance) {
        instance.status = "failed";
        instance.finishedAt = new Date().toISOString();
      }
    } finally {
      this.running.delete(id);

      // Wait interval before starting next
      if (this.queue.length > 0 && !this.stopRequested) {
        await this.sleep(this.config.intervalMs);
      }
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  stop(): void {
    this.stopRequested = true;
  }

  getStatus(): { total: number; pending: number; running: number; completed: number; failed: number } {
    const instances = [...this.instances.values()];
    return {
      total: instances.length,
      pending: instances.filter(i => i.status === "pending").length,
      running: instances.filter(i => i.status === "running").length,
      completed: instances.filter(i => i.status === "completed").length,
      failed: instances.filter(i => i.status === "failed").length
    };
  }
}

// CLI
async function main() {
  const args = process.argv.slice(2);

  const count = parseInt(args.find(a => a.startsWith("--count="))?.split("=")[1] ?? "3");
  const interval = parseInt(args.find(a => a.startsWith("--interval="))?.split("=")[1] ?? "1000");
  const maxConcurrent = parseInt(args.find(a => a.startsWith("--concurrent="))?.split("=")[1] ?? "3");
  const headless = !args.includes("--headfull");
  const stopOnFailure = args.includes("--stop-on-failure");

  const manager = new MultiAgentManager({
    intervalMs: interval,
    maxConcurrent: maxConcurrent,
    headless,
    stopOnFirstFailure: stopOnFailure
  });

  // Handle Ctrl+C
  process.on("SIGINT", () => {
    console.log("\n⚠ Received SIGINT - stopping...");
    manager.stop();
  });

  const result = await manager.run(count);

  console.log("");
  console.log("=".repeat(60));
  console.log("  SUMMARY");
  console.log("=".repeat(60));
  console.log(`Total: ${result.totalInstances}`);
  console.log(`Successful: ${result.successful}`);
  console.log(`Failed: ${result.failed}`);
  console.log(`Duration: ${result.duration}ms`);

  // Show individual results
  if (result.results.length <= 20) {
    console.log("");
    console.log("Individual Results:");
    for (const r of result.results) {
      const icon = r.success ? "✓" : "✗";
      const duration = r.steps.reduce((s, st) => s + st.duration, 0);
      console.log(`  ${icon} ${r.instanceId} - ${duration}ms`);
      if (!r.success) {
        const failedStep = r.steps.find(s => !s.passed);
        if (failedStep) console.log(`      └─ ${failedStep.name}: ${failedStep.error}`);
      }
    }
  }

  process.exit(result.failed > 0 ? 1 : 0);
}

main().catch(console.error);