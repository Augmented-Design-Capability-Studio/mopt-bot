/**
 * Frontend module export for the template problem.
 *
 * Export a MODULE constant that satisfies the ProblemModule interface.
 * The generic frontend shell imports this via problemRegistry.ts — it must
 * never import problem-specific files directly.
 *
 * Minimal required shape: { vizTabs: [] }
 * Add optional fields as your problem needs them.
 */
import type { ProblemModule } from "@problemConfig/problemModule";

// TODO: uncomment and implement as needed:
// import { buildTemplateGoalTermsExtension } from "./TemplateExtras";
// import { TemplateViz } from "./TemplateViz";
// import { TemplateViolationSummary } from "./TemplateViolationSummary";
// import { parseRoutesForEval } from "./schedule";

// TODO: implement if this problem supports plain-text violation summaries in the AI chat.
// function formatRunViolationSummary(result: unknown): string | null {
//   if (!result || typeof result !== "object") return null;
//   const violations = (result as Record<string, unknown>).violations as Record<string, unknown> | undefined;
//   if (!violations) return null;
//   // Return a comma-separated string of notable violations, or "no violations".
//   return "no violations";
// }

export const MODULE: ProblemModule = {
  // TODO: add buildGoalTermsExtension if this problem needs custom config-panel UI.
  // buildGoalTermsExtension: buildTemplateGoalTermsExtension,

  // Visualization tabs shown in the Results panel.
  // Each component receives { currentRun: RunResult } as props.
  // Return [] if no visualizations are needed.
  vizTabs: [
    // TODO: { id: "template_viz", label: "Results", component: TemplateViz },
  ],

  // TODO: add ViolationSummary component if results have structured metrics.
  // ViolationSummary: TemplateViolationSummary,

  // TODO: add parseEvalRoutes if the problem supports manual solution editing + re-evaluation.
  // parseEvalRoutes: parseRoutesForEval,

  // TODO: add formatRunViolationSummary for the AI chat message after a run.
  // formatRunViolationSummary,
};
