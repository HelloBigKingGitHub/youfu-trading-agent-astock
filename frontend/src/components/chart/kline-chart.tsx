import * as React from 'react';
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type Time,
} from 'lightweight-charts';
import type { ChartRange, Kline } from '@/api/chart';

interface KlineChartProps {
  klines: Kline[];
  range?: ChartRange;
}

type ChartPoint = CandlestickData<Time>;

function movingAverage(klines: Kline[], period: number) {
  return klines.flatMap((kline, index) => {
    if (index < period - 1) return [];
    const values = klines.slice(index - period + 1, index + 1).map((item) => item.close);
    return [{ time: kline.date as Time, value: values.reduce((sum, value) => sum + value, 0) / period }];
  });
}

/** Lightweight Charts v5 wrapper with candle, MA overlays, and volume pane. */
export function KlineChart({ klines, range = '6m' }: KlineChartProps) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const chartRef = React.useRef<IChartApi | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container || klines.length === 0) return undefined;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { color: '#0e131b' },
        textColor: '#8a96a8',
        fontFamily: 'IBM Plex Mono, monospace',
      },
      grid: {
        vertLines: { color: '#1c2532' },
        horzLines: { color: '#1c2532' },
      },
      rightPriceScale: { borderColor: '#2a3548' },
      timeScale: { borderColor: '#2a3548', timeVisible: false },
      crosshair: { vertLine: { color: '#4d9aff' }, horzLine: { color: '#4d9aff' } },
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#00d68f',
      downColor: '#ff4d6d',
      borderVisible: false,
      wickUpColor: '#00d68f',
      wickDownColor: '#ff4d6d',
    });
    const candleData: ChartPoint[] = klines.map((item) => ({
      time: item.date as Time,
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }));
    candles.setData(candleData);

    const movingAverageStyles = [
      { period: 5, color: '#f6c453' },
      { period: 10, color: '#4d9aff' },
      { period: 20, color: '#c084fc' },
    ];
    for (const { period, color } of movingAverageStyles) {
      const series = chart.addSeries(LineSeries, { color, lineWidth: 1, title: `MA${period}` });
      series.setData(movingAverage(klines, period));
    }

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      color: '#4d9aff88',
    }, 1);
    volume.setData(klines.map((item, index) => ({
      time: item.date as Time,
      value: item.volume,
      color: index > 0 && item.close >= klines[index - 1].close ? '#00d68f88' : '#ff4d6d88',
    })));

    chart.timeScale().fitContent();
    return () => {
      chartRef.current = null;
      chart.remove();
    };
  }, [klines, range]);

  if (klines.length === 0) return null;

  return (
    <div
      ref={containerRef}
      data-testid="chart-canvas"
      data-range={range}
      aria-label="K线图"
      role="img"
      className="h-[30rem] min-h-[420px] w-full overflow-hidden rounded-md border border-border-1 bg-bg-surface"
    />
  );
}

export default KlineChart;
