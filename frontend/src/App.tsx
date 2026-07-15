import * as React from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { Header } from '@/components/layout/Header';
import { SettingsPage } from '@/pages/SettingsPage';
import { PlaceholderPage } from '@/pages/PlaceholderPage';

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

// 9 routes — one per sidebar entry. /analyze is the default landing per
// existing streamlit convention. Only /settings is fully implemented; the
// other 8 render a PlaceholderPage so the sidebar navigation feels real.
const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <Layout title="分析" subtitle="单股投研分析入口 (Streamlit 共用)">
        <PlaceholderPage title="分析" icon="📝" phase="Phase 2.1" description="单股深度分析 (Bull/Bear 辩论 + 风险管理)" />
      </Layout>
    ),
  },
  {
    path: '/analyze',
    element: <Navigate to="/" replace />,
  },
  {
    path: '/batch',
    element: (
      <Layout title="批量分析" subtitle="多 ticker 并行投研分析">
        <PlaceholderPage title="批量分析" icon="📊" phase="Phase 2.4" description="批量 ticker 分析 + 进度监控" />
      </Layout>
    ),
  },
  {
    path: '/sector',
    element: (
      <Layout title="板块轮动" subtitle="每日板块行情 + 选股热度">
        <PlaceholderPage title="板块轮动" icon="📈" phase="Phase 2.5" description="板块轮动日报 + 资金流" />
      </Layout>
    ),
  },
  {
    path: '/portfolio',
    element: (
      <Layout title="我的仓位" subtitle="持仓 + 业绩归因 + 预警">
        <PlaceholderPage title="仓位" icon="💼" phase="Phase 2.6" description="持仓管理 + 业绩归因 + 预警" />
      </Layout>
    ),
  },
  {
    path: '/history',
    element: (
      <Layout title="历史报告" subtitle="历史分析记录查询">
        <PlaceholderPage title="历史" icon="📋" phase="Phase 2.2" description="历史报告查询 + 详情" />
      </Layout>
    ),
  },
  {
    path: '/logs',
    element: (
      <Layout title="日志" subtitle="LangGraph stream chunks 实时 + 历史">
        <PlaceholderPage title="日志" icon="📋" phase="Phase 2.3" description="LangGraph stream 日志 (LLM / tool / agent_output)" />
      </Layout>
    ),
  },
  {
    path: '/chart',
    element: (
      <Layout title="走势图" subtitle="K 线 + 实时报价">
        <PlaceholderPage title="走势图" icon="📈" phase="Phase 2.7" description="K 线图 + 实时报价 + 多周期" />
      </Layout>
    ),
  },
  {
    path: '/schedule',
    element: (
      <Layout title="定时分析" subtitle="Cron 调度 + 多渠道通知">
        <PlaceholderPage title="定时分析" icon="⏰" phase="Phase 2.8" description="定时分析 + 通知 (WeCom / Email / Desktop)" />
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