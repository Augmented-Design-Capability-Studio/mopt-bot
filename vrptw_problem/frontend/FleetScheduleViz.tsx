import { useEffect, useMemo, useState } from "react";

import type { RunScheduleStop, RunVisualization } from "@shared/api";
import type { ProblemVizProps } from "@problemConfig/problemModule";

function formatClock(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function stopLabel(stop: RunScheduleStop): string {
  return stop.task_id.replace(/^O/, "");
}

function isExpressStop(stop: RunScheduleStop): boolean {
  return stop.priority_express ?? stop.priority_urgent ?? false;
}

function stopPreferenceHit(stop: RunScheduleStop): boolean {
  if (stop.preference_conflict === true) return true;
  const u = stop.preference_penalty_units;
  return u != null && u > 0;
}

/** Per-vehicle Gantt-style schedule (fleet / VRPTW results). */
export function FleetScheduleViz({ currentRun }: ProblemVizProps) {
  const currentResult = currentRun.result;
  const runProblem = (currentRun.request?.problem ?? {}) as Record<string, unknown>;

  const driverPrefs = Array.isArray(runProblem.driver_preferences) ? runProblem.driver_preferences : [];
  const runWeights =
    runProblem.weights && typeof runProblem.weights === "object" && !Array.isArray(runProblem.weights)
      ? (runProblem.weights as Record<string, unknown>)
      : {};
  const wpw = Number(runWeights.worker_preference);
  const schedulePreferencesActive = driverPrefs.length > 0 && Number.isFinite(wpw) && wpw > 0;
  const scheduleEarlyArrivalActive =
    runProblem.early_arrival_threshold_min != null ||
    (Number.isFinite(Number(runWeights.waiting_time)) && Number(runWeights.waiting_time) > 0);
  const earlyArrivalThresholdMin = Number.isFinite(Number(runProblem.early_arrival_threshold_min))
    ? Number(runProblem.early_arrival_threshold_min)
    : 30;

  const schedule = currentResult?.schedule;
  if (!schedule) {
    return <div className="muted">No schedule data available for this run.</div>;
  }

  return (
    <FleetScheduleVizInner
      schedule={schedule}
      schedulePreferencesActive={schedulePreferencesActive}
      scheduleEarlyArrivalActive={scheduleEarlyArrivalActive}
      earlyArrivalThresholdMin={earlyArrivalThresholdMin}
      visualization={currentResult?.visualization ?? null}
    />
  );
}

type FleetScheduleVizInnerProps = {
  schedule: NonNullable<NonNullable<import("@shared/api").RunResult["result"]>["schedule"]>;
  schedulePreferencesActive: boolean;
  scheduleEarlyArrivalActive: boolean;
  earlyArrivalThresholdMin: number;
  visualization: RunVisualization | null | undefined;
};

function FleetScheduleVizInner({
  schedule,
  schedulePreferencesActive,
  scheduleEarlyArrivalActive,
  earlyArrivalThresholdMin,
}: FleetScheduleVizInnerProps) {
  const [selectedStopId, setSelectedStopId] = useState<string | null>(null);

  const stopsByVehicle = useMemo(() => {
    const grouped = new Map<number, RunScheduleStop[]>();
    for (const stop of schedule.stops) {
      const list = grouped.get(stop.vehicle_index) ?? [];
      list.push(stop);
      grouped.set(stop.vehicle_index, list);
    }
    for (const list of grouped.values()) {
      list.sort((a, b) => a.arrival_minutes - b.arrival_minutes);
    }
    return grouped;
  }, [schedule.stops]);

  const stopContext = useMemo(() => {
    const context = new Map<string, { origin: string; destination: string; driveMinutes: number }>();
    for (const [vehicleIndex, list] of stopsByVehicle.entries()) {
      let prevDeparture = schedule.vehicle_summaries.find((v) => v.vehicle_index === vehicleIndex)?.shift_start_minutes ?? 0;
      let prevRegion = "Depot";
      for (const stop of list) {
        const key = `${stop.vehicle_index}:${stop.task_index ?? stop.task_id}`;
        const driveMinutes = Math.max(0, stop.arrival_minutes - prevDeparture);
        context.set(key, { origin: prevRegion, destination: stop.region_name, driveMinutes });
        prevDeparture = stop.departure_minutes;
        prevRegion = stop.region_name;
      }
    }
    return context;
  }, [schedule.vehicle_summaries, stopsByVehicle]);

  const allStops = schedule.stops;
  const selectedStop =
    allStops.find(
      (stop) =>
        `${stop.vehicle_index}:${stop.task_index ?? stop.task_id}` === selectedStopId,
    ) ?? allStops[0];

  useEffect(() => {
    if (!allStops.length) {
      setSelectedStopId(null);
      return;
    }
    if (
      selectedStopId == null ||
      !allStops.some(
        (stop) =>
          `${stop.vehicle_index}:${stop.task_index ?? stop.task_id}` === selectedStopId,
      )
    ) {
      const firstInteresting =
        allStops.find(
          (stop) =>
            stop.time_window_conflict ||
            stop.capacity_conflict ||
            stop.priority_deadline_missed ||
            stopPreferenceHit(stop),
        ) ?? allStops[0];
      setSelectedStopId(
        `${firstInteresting.vehicle_index}:${firstInteresting.task_index ?? firstInteresting.task_id}`,
      );
    }
  }, [allStops, selectedStopId]);

  const start = schedule.time_bounds.start_minutes;
  const end = Math.max(schedule.time_bounds.end_minutes, start + 60);
  const duration = end - start;
  const ticks = Array.from({ length: 7 }, (_, i) => start + (duration * i) / 6);

  if (!schedule.stops.length) {
    return <div className="muted">No stop timing data available for this run.</div>;
  }

  return (
    <div className="run-timeline-wrap">
      <div className="run-timeline-legend muted">
        <span className="timeline-legend-item">
          <span className="timeline-legend-swatch service" />
          Drive &amp; service (blue) · Wait (white)
        </span>
        <span className="timeline-legend-item">
          <span className="timeline-legend-swatch tw-miss" />
          Time-window miss
        </span>
        <span className="timeline-legend-item">
          <span className="timeline-legend-swatch express" />
          Express stop
        </span>
        <span className="timeline-legend-item">
          <span className="timeline-legend-swatch capacity" />
          Capacity overflow
        </span>
        {schedulePreferencesActive ? (
          <span className="timeline-legend-item">
            <span className="timeline-legend-swatch preference" />
            Preference penalty (stop)
          </span>
        ) : null}
        {scheduleEarlyArrivalActive ? (
          <span className="timeline-legend-item">
            <span className="timeline-legend-swatch wait" />
            Pre-window wait time
          </span>
        ) : null}
      </div>
      <div className="run-timeline-axis">
        <div className="run-timeline-label-spacer" />
        <div className="run-timeline-scale">
          {ticks.map((tick) => (
            <div
              key={tick}
              className="run-timeline-tick"
              style={{ left: `${((tick - start) / duration) * 100}%` }}
            >
              <span>{formatClock(tick)}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="run-timeline-rows">
        {schedule.vehicle_summaries.map((vehicle) => {
          const vehicleStops = stopsByVehicle.get(vehicle.vehicle_index) ?? [];
          return (
            <div key={vehicle.vehicle_index} className="run-timeline-row">
              <div className="run-timeline-label mono">
                <div>{vehicle.vehicle_name}</div>
                <div className="muted">
                  {vehicle.assigned_units}/{vehicle.capacity_limit} units · {vehicle.stop_count} stops
                </div>
              </div>
              <div className="run-timeline-lane">
                {vehicleStops.map((stop) => {
                  const ctxKey = `${stop.vehicle_index}:${stop.task_index ?? stop.task_id}`;
                  const driveMinutes = stopContext.get(ctxKey)?.driveMinutes ?? 0;
                  const waitMinutes = stop.wait_minutes ?? 0;
                  const totalBlockMin = driveMinutes + (stop.departure_minutes - stop.arrival_minutes);
                  const barStartMinutes = stop.arrival_minutes - driveMinutes;
                  const leftPct = ((barStartMinutes - start) / duration) * 100;
                  const widthPct = Math.max((totalBlockMin / duration) * 100, 2);
                  const driveFraction = totalBlockMin > 0 ? driveMinutes / totalBlockMin : 0;
                  const waitFraction =
                    waitMinutes > 0 && totalBlockMin > 0
                      ? Math.min(1 - driveFraction, waitMinutes / totalBlockMin)
                      : 0;
                  const selected =
                    selectedStop != null &&
                    selectedStop.vehicle_index === stop.vehicle_index &&
                    selectedStop.task_id === stop.task_id;
                  const prefHit = schedulePreferencesActive && stopPreferenceHit(stop);
                  return (
                    <button
                      key={`${stop.vehicle_index}:${stop.task_id}`}
                      type="button"
                      className={[
                        "run-stop-bar",
                        stop.time_window_conflict ? "violation-tw" : "",
                        stop.capacity_conflict ? "violation-capacity" : "",
                        isExpressStop(stop) ? "express" : "",
                        prefHit ? "violation-preference" : "",
                        selected ? "selected" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                      onClick={() =>
                        setSelectedStopId(
                          `${stop.vehicle_index}:${stop.task_index ?? stop.task_id}`,
                        )
                      }
                      title={`${stop.task_id} · ${formatClock(stop.arrival_minutes)}-${formatClock(stop.departure_minutes)}`}
                    >
                      {waitFraction > 0 && (
                        <span
                          className="stop-bar-wait-stripe"
                          style={{
                            left: `${driveFraction * 100}%`,
                            width: `${waitFraction * 100}%`,
                          }}
                        />
                      )}
                      <span style={{ position: "relative", zIndex: 1 }}>{stopLabel(stop)}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      {selectedStop && (
        <div className="run-stop-detail">
          <div className="panel-header">Selected stop</div>
          <div className="panel-body">
            <div className="run-stop-detail-grid mono">
              <div>task</div>
              <div>{selectedStop.task_id}</div>
              <div>vehicle</div>
              <div>{selectedStop.vehicle_name}</div>
              <div>origin → destination</div>
              <div>
                {stopContext.get(`${selectedStop.vehicle_index}:${selectedStop.task_index ?? selectedStop.task_id}`)?.origin ??
                  "Depot"}{" "}
                →{" "}
                {stopContext.get(`${selectedStop.vehicle_index}:${selectedStop.task_index ?? selectedStop.task_id}`)?.destination ??
                  selectedStop.region_name}
              </div>
              <div>fulfillment period</div>
              <div>
                {formatClock(selectedStop.arrival_minutes + (selectedStop.wait_minutes ?? 0))} -{" "}
                {formatClock(selectedStop.departure_minutes)}
              </div>
              <div>arrival</div>
              <div>{formatClock(selectedStop.arrival_minutes)}</div>
              <div>window</div>
              <div>
                {formatClock(selectedStop.window_open_minutes)} - {formatClock(selectedStop.window_close_minutes)}
              </div>
              <div>drive / wait / service</div>
              <div>
                {(
                  stopContext.get(`${selectedStop.vehicle_index}:${selectedStop.task_index ?? selectedStop.task_id}`)
                    ?.driveMinutes ?? 0
                ).toFixed(0)}
                m / {selectedStop.wait_minutes.toFixed(0)}m / {selectedStop.service_minutes}m
              </div>
              <div>cumulated load / capacity</div>
              <div>
                {selectedStop.load_after_stop}/{selectedStop.capacity_limit}
              </div>
              <div>violations</div>
              <div>
                {[
                  selectedStop.time_window_conflict
                    ? `${selectedStop.time_window_minutes_over.toFixed(0)}m late`
                    : "",
                  selectedStop.priority_deadline_missed ? "express miss" : "",
                  selectedStop.capacity_conflict
                    ? `${selectedStop.capacity_overflow_after_stop} over capacity`
                    : "",
                  schedulePreferencesActive && stopPreferenceHit(selectedStop)
                    ? `preference +${(selectedStop.preference_penalty_units ?? 0).toFixed(1)} units`
                    : "",
                  scheduleEarlyArrivalActive &&
                  Math.max(0, (selectedStop.wait_minutes ?? 0) - earlyArrivalThresholdMin) > 0
                    ? `early +${Math.max(0, (selectedStop.wait_minutes ?? 0) - earlyArrivalThresholdMin).toFixed(0)}m excess`
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ") || "none"}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
