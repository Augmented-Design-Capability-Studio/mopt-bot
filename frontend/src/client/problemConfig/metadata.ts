const WEIGHT_INFO: Record<string, { label: string; description: string }> = {
  travel_time: {
    label: "Travel Time",
    description:
      "Penalizes total time spent in transit between stops. Higher values favour shorter, faster routes.",
  },
  fuel_cost: {
    label: "Fuel & Operating Cost",
    description:
      "Penalizes fuel consumption (scaled from travel time). Higher values favour fuel-efficient routes.",
  },
  deadline_penalty: {
    label: "On-Time Delivery",
    description:
      "Penalizes arriving after a stop's allowed time window. Higher values enforce stricter punctuality.",
  },
  capacity_penalty: {
    label: "Load Capacity Limits",
    description:
      "Penalizes loading beyond a vehicle's capacity. Higher values keep loads within safe limits.",
  },
  workload_balance: {
    label: "Workload Balance",
    description:
      "Penalizes unequal shift lengths across workers. Higher values produce a fairer distribution of work.",
  },
  worker_preference: {
    label: "Worker Preferences",
    description:
      "Penalizes assigning workers to tasks or conditions they prefer to avoid. Higher values respect preferences more strongly.",
  },
  priority_penalty: {
    label: "Priority Order Deadlines",
    description:
      "Penalizes late delivery of express or high-priority tasks. Higher values protect critical deadlines.",
  },
};

const ALGORITHM_DESC: Record<string, string> = {
  GA: "Genetic Algorithm - evolves a population of candidate solutions through selection, crossover, and mutation.",
  PSO: "Particle Swarm - a swarm of candidates converge collaboratively toward promising search regions.",
  SA: "Simulated Annealing - cools the search gradually to escape local optima and converge to good solutions.",
  SwarmSA:
    "Swarm Simulated Annealing - combines swarm-based exploration with annealing-style cooling.",
  ACOR: "Ant Colony Optimization (Continuous) - guides search by modelling pheromone accumulation along good paths.",
};

const CONDITION_LABEL: Record<string, string> = {
  zone_d: "trips through a specific congested zone",
  express_order: "priority/express order assignments",
  shift_over_hours: "shifts exceeding a comfortable length",
};

export { ALGORITHM_DESC, CONDITION_LABEL, WEIGHT_INFO };
