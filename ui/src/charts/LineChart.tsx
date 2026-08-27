import { useEffect, useRef } from "react";
import { CHART_PALETTE, echarts } from "./echartsSetup";
import { DataTable } from "./DataTable";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import styles from "./Chart.module.css";

interface LineChartProps {
  title: string;
  xAxisLabel: string;
  yAxisLabel: string;
  categories: string[];
  series: { name: string; values: number[] }[];
}

export function LineChart({ title, xAxisLabel, yAxisLabel, categories, series }: LineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const hasData = categories.length > 0 && series.some((entry) => entry.values.length > 0);

  useEffect(() => {
    if (!containerRef.current || !hasData) return;
    const chart = echarts.init(containerRef.current);
    chart.setOption({
      color: CHART_PALETTE,
      animation: !reducedMotion,
      grid: { left: 56, right: 16, top: series.length > 1 ? 40 : 16, bottom: 48 },
      tooltip: { trigger: "axis" },
      legend: series.length > 1 ? { top: 0 } : undefined,
      xAxis: { type: "category", data: categories, name: xAxisLabel, nameLocation: "middle", nameGap: 32 },
      yAxis: { type: "value", name: yAxisLabel, nameLocation: "middle", nameGap: 40 },
      series: series.map((entry) => ({ name: entry.name, type: "line", data: entry.values, symbolSize: 6 })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [categories, series, xAxisLabel, yAxisLabel, reducedMotion, hasData]);

  return (
    <figure className={styles.figure}>
      <figcaption className={styles.title}>{title}</figcaption>
      {hasData ? (
        <div ref={containerRef} className={styles.canvas} role="img" aria-label={`${title} chart`} />
      ) : (
        <p className={styles.empty}>No data was produced for this check.</p>
      )}
      <details className={styles.tableDetails}>
        <summary>View as table</summary>
        <DataTable
          caption={title}
          columns={[xAxisLabel, ...series.map((entry) => entry.name)]}
          rows={categories.map((category, index) => [category, ...series.map((entry) => entry.values[index] ?? "—")])}
        />
      </details>
    </figure>
  );
}
