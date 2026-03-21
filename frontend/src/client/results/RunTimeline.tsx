import { useEffect, useMemo, useState } from "react";

import type { RunSchedule, RunScheduleStop } from "@shared/api";

function formatClock(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function stopLabel(stop: RunScheduleStop): string {
  return stop.task_id.replace(/^O/, "");
}

type RunTimelineProps = {
  schedule: RunSchedule;
};

export function RunTimeline({ schedule }: RunTimelineProps) {
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
            stop.priority_deadline_missed,
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
        <span className="timeline-legend-item">Solid bar = stop service block</span>
        <span className="timeline-legend-item">Red outline = time-window miss</span>
        <span className="timeline-legend-item">Amber badge = urgent stop</span>
        <span className="timeline-legend-item">Red chip = capacity overflow</span>
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
                  const leftPct = ((stop.arrival_minutes - start) / duration) * 100;
                  const widthPct = Math.max(
                    ((stop.departure_minutes - stop.arrival_minutes) / duration) * 100,
                    2,
                  );
                  const selected =
                    selectedStop != null &&
                    selectedStop.vehicle_index === stop.vehicle_index &&
                    selectedStop.task_id === stop.task_id;
                  return (
                    <button
                      key={`${stop.vehicle_index}:${stop.task_id}`}
                      type="button"
                      className={[
                        "run-stop-bar",
                        stop.time_window_conflict ? "violation-tw" : "",
                        stop.capacity_conflict ? "violation-capacity" : "",
                        stop.priority_urgent ? "urgent" : "",
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
                      <span>{stopLabel(stop)}</span>
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
              <div>region</div>
              <div>{selectedStop.region_name}</div>
              <div>time</div>
              <div>
                {formatClock(selectedStop.arrival_minutes)} - {formatClock(selectedStop.departure_minutes)}
              </div>
              <div>window</div>
              <div>
                {formatClock(selectedStop.window_open_minutes)} - {formatClock(selectedStop.window_close_minutes)}
              </div>
              <div>wait / service</div>
              <div>
                {selectedStop.wait_minutes.toFixed(0)}m / {selectedStop.service_minutes}m
              </div>
              <div>load / capacity</div>
              <div>
                {selectedStop.load_after_stop}/{selectedStop.capacity_limit}
              </div>
              <div>violations</div>
              <div>
                {[
                  selectedStop.time_window_conflict
                    ? `${selectedStop.time_window_minutes_over.toFixed(0)}m late`
                    : "",
                  selectedStop.priority_deadline_missed ? "urgent miss" : "",
                  selectedStop.capacity_conflict
                    ? `${selectedStop.capacity_overflow_after_stop} over capacity`
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
