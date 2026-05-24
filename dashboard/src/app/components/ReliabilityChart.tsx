"use client";

import {
    ComposedChart,
    Bar,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts";

export type ReliabilityBin = {
    bin: number;
    lo: number;
    hi: number;
    n: number;
    yes: number;
    empirical_pct: number | null;
};

export function ReliabilityChart({ bins }: { bins: ReliabilityBin[] }) {
    const data = bins.map((b) => ({
        label: `${b.lo}`,
        ideal: b.lo + 5,            // perfect-calibration diagonal (bin midpoint)
        empirical: b.empirical_pct, // null bins render as gaps
        n: b.n,
    }));

    return (
        <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: -16 }}>
                    <CartesianGrid stroke="#262626" strokeDasharray="3 3" />
                    <XAxis
                        dataKey="label"
                        stroke="#525252"
                        fontSize={11}
                        label={{ value: "Arke forecast %", position: "insideBottom", offset: -4, fill: "#525252", fontSize: 11 }}
                    />
                    <YAxis domain={[0, 100]} stroke="#525252" fontSize={11} />
                    <Tooltip
                        contentStyle={{ background: "#0a0a0a", border: "1px solid #404040", fontSize: 12 }}
                        labelStyle={{ color: "#a3a3a3" }}
                        formatter={(value: number | string, name: string) =>
                            name === "empirical"
                                ? [value === null ? "—" : `${value}%`, "empirical YES"]
                                : [`${value}%`, "ideal"]
                        }
                    />
                    <Bar dataKey="empirical" fill="#f59e0b" isAnimationActive={false} />
                    <Line
                        type="monotone"
                        dataKey="ideal"
                        stroke="#3b82f6"
                        strokeWidth={1}
                        strokeDasharray="4 4"
                        dot={false}
                        isAnimationActive={false}
                    />
                </ComposedChart>
            </ResponsiveContainer>
        </div>
    );
}
