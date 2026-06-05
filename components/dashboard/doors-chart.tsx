"use client";

import { useState } from "react";
import { BarChart3 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { BarChart } from "@/components/charts/bar-chart";
import { Segmented } from "@/components/ui/segmented";
import { EmptyState } from "@/components/ui/empty-state";
import type { BarDatum } from "@/components/charts/bar-chart";

export function DoorsChart({ data }: { data: BarDatum[] }) {
  const [range, setRange] = useState<"week" | "month">("week");

  return (
    <Card className="flex h-full flex-col p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-bold tracking-tight text-ink">Door volume</h3>
          <p className="text-[13px] text-muted">Doors knocked per day</p>
        </div>
        <Segmented
          size="sm"
          value={range}
          onChange={setRange}
          options={[
            { value: "week", label: "Week" },
            { value: "month", label: "Month" },
          ]}
        />
      </div>
      <div className="mt-6 flex-1">
        {data.length ? (
          <BarChart data={data} />
        ) : (
          <EmptyState
            compact
            icon={<BarChart3 className="size-5" />}
            title="No door activity yet"
            description="Volume will appear here once your reps start knocking."
          />
        )}
      </div>
    </Card>
  );
}
