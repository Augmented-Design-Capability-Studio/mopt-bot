import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ConvergencePlotProps = {
  convergence: number[];
  referenceCost?: number | null;
};

type DataPoint = {
  iteration: number;
  cost: number;
};

function formatCost(value: number): string {
  if (value >= 10000) return value.toFixed(0);
  if (value >= 1000) return value.toFixed(1);
  return value.toFixed(2);
}

type TooltipPayloadEntry = {
  value: number;
  name: string;
};

type CustomTooltipProps = {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: number;
};

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #9a958c",
        padding: "0.3rem 0.5rem",
        fontSize: "0.78rem",
        fontFamily: 'ui-monospace, "Cascadia Code", Consolas, monospace',
        lineHeight: 1.5,
      }}
    >
      <div style={{ color: "#5c5952" }}>Iteration {label}</div>
      <div style={{ color: "#3d4a57", fontWeight: 600 }}>Cost: {formatCost(payload[0].value)}</div>
    </div>
  );
}

export function ConvergencePlot({ convergence, referenceCost }: ConvergencePlotProps) {
  const data: DataPoint[] = convergence.map((cost, i) => ({ iteration: i + 1, cost }));

  const minCost = Math.min(...convergence);
  const maxCost = Math.max(...convergence);
  const padding = (maxCost - minCost) * 0.08 || 1;
  const yMin = minCost - padding;
  const yMax = maxCost + padding;

  const refInRange =
    referenceCost != null && referenceCost >= yMin && referenceCost <= yMax;

  return (
    <div style={{ width: "100%", height: 240, marginTop: "0.5rem" }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 24, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0ddd8" />
          <XAxis
            dataKey="iteration"
            tick={{ fontSize: 11, fill: "#5c5952" }}
            label={{ value: "Iteration", position: "insideBottom", offset: -12, fontSize: 11, fill: "#5c5952" }}
            tickLine={false}
          />
          <YAxis
            domain={[yMin, yMax]}
            tickFormatter={formatCost}
            tick={{ fontSize: 11, fill: "#5c5952" }}
            label={{ value: "Cost", angle: -90, position: "insideLeft", offset: 8, fontSize: 11, fill: "#5c5952" }}
            tickLine={false}
            width={60}
          />
          <Tooltip content={<CustomTooltip />} />
          {refInRange && (
            <ReferenceLine
              y={referenceCost!}
              stroke="#9a958c"
              strokeDasharray="5 3"
              label={{ value: "reference", position: "insideTopRight", fontSize: 10, fill: "#9a958c" }}
            />
          )}
          <Line
            type="monotone"
            dataKey="cost"
            stroke="#3d4a57"
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: "#3d4a57" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
