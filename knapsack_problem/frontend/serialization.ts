/**
 * Knapsack panel config serialization.
 * The knapsack problem uses the generic base parser/serializer with no extensions.
 * Re-exported here so knapsack-specific code has a local canonical import path.
 */

export {
  parseBaseProblemConfig as parseProblemConfig,
  serializeBaseProblemConfig as serializeProblemConfig,
  parseActiveWeightKeys,
} from "@problemConfig/baseSerialization";

export type { ParsedBaseProblemConfig as ParsedProblemConfig } from "@problemConfig/baseSerialization";
