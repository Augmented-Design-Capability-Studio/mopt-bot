/**
 * Single registration point for all problem modules.
 * This is the ONE file in the generic frontend that names individual problem folders.
 * All other generic code calls getProblemModule(id) and never imports problem folders directly.
 */
import { MODULE as VRPTW_MODULE } from "@vrptw/index";
import { MODULE as KNAPSACK_MODULE } from "@knapsack/index";
import type { ProblemModule } from "./problemConfig/problemModule";

const REGISTRY: Record<string, ProblemModule> = {
  vrptw: VRPTW_MODULE,
  knapsack: KNAPSACK_MODULE,
};

const FALLBACK: ProblemModule = { vizTabs: [] };

export function getProblemModule(problemId: string): ProblemModule {
  return REGISTRY[problemId.trim().toLowerCase()] ?? FALLBACK;
}
