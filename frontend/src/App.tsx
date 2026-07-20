import * as React from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { Header } from '@/components/layout/Header';
import { SettingsPage } from '@/pages/SettingsPage';
import { HistoryPage } from '@/pages/HistoryPage';
import { LogsPage } from '@/pages/LogsPage';
import ChartPage from '@/pages/ChartPage';
import SectorPage from '@/pages/SectorPage';
import BatchPage from '@/pages/BatchPage';
import PortfolioPage from '@/pages/PortfolioPage';
import SchedulePage from '@/pages/SchedulePage';
import AnalyzePage from '@/pages/AnalyzePage';

function Layout({ children, title, subtitle }: { children: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <div className="flex h-screen bg-bg-base text-text-primary">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden">
        <Header title={title} subtitle={subtitle} />
        <div className="flex-1 overflow-y-auto p-6">{children}</div>
      </main>
    </div>
  );
}

const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/analyze" replace />,
  },
  {
    path: '/analyze',
    element: (
      <Layout title="分析" subtitle="单股投研分析入口">
        <AnalyzePage />
      </Layout>
    ),
  },
  {
    path: '/batch',
    element: (
      <Layout title="批量分析" subtitle="多 ticker 并行投研分析">
        <BatchPage />
      </Layout>
    ),
  },
  {
    path: '/sector',
    element: (
      <Layout title="📈 板块轮动" subtitle="每日板块行情 + 选股热度 + 涨停归因">
        <SectorPage />
      </Layout>
    ),
  },
  {
    path: '/portfolio',
    element: (
      <Layout title="我的仓位" subtitle="持仓 + 业绩归因 + 预警">
        <PortfolioPage />
      </Layout>
    ),
  },
  {
    path: '/history',
    element: (
      <Layout title="📋 历史报告" subtitle="历史分析记录查询 · 详情 · 重跑 · 删除">
        <HistoryPage />
      </Layout>
    ),
  },
  {
    path: '/logs',
    element: (
      <Layout title="📋 日志" subtitle="实时运行日志 + 历史查询">
        <LogsPage />
      </Layout>
    ),
  },
  {
    path: '/chart',
    element: (
      <Layout title="走势图" subtitle="K 线 + 实时报价">
        <ChartPage />
      </Layout>
    ),
  },
  {
    path: '/schedule',
    element: (
      <Layout title="定时分析" subtitle="定时调度 + 多渠道通知">
        <SchedulePage />
      </Layout>
    ),
  },
  {
    path: '/settings',
    element: (
      <Layout title="⚙️ 设置" subtitle="配置 LLM 供应商、模型、API Key">
        <SettingsPage />
      </Layout>
    ),
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}