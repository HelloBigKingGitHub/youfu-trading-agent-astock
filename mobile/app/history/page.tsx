"use client";

import { useState, useEffect, useCallback } from "react";
import { HistoryFilters } from "@/components/history/HistoryFilters";
import { HistoryTable } from "@/components/history/HistoryTable";
import { listHistory, deleteHistory } from "@/lib/api";
import type { HistoryItem } from "@/lib/types";

const PAGE_SIZE = 20;

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [filters, setFilters] = useState({ ticker: "", signal: "", status: "" });

  const load = useCallback(
    async (skip = 0, append = false) => {
      try {
        const resp = await listHistory(PAGE_SIZE, skip, filters.ticker, filters.signal, filters.status);
        if (append) {
          setItems((prev) => [...prev, ...resp.items]);
        } else {
          setItems(resp.items);
        }
        setTotal(resp.total);
        setHasMore(resp.items.length === PAGE_SIZE);
        setOffset(skip + resp.items.length);
      } catch (e) {
        console.error("Failed to load history:", e);
      }
    },
    [filters]
  );

  useEffect(() => {
    setLoading(true);
    load(0).finally(() => setLoading(false));
  }, [load]);

  const handleSearch = useCallback((f: { ticker: string; signal: string; status: string }) => {
    setFilters(f);
    setOffset(0);
    setHasMore(false);
    setLoading(true);
    load(0).finally(() => setLoading(false));
  }, [load]);

  const handleLoadMore = async () => {
    setLoadingMore(true);
    await load(offset, true);
    setLoadingMore(false);
  };

  const handleDelete = async (analysisId: string) => {
    setDeleting(analysisId);
    try {
      await deleteHistory(analysisId);
      setItems((prev) => prev.filter((i) => i.analysis_id !== analysisId));
      setTotal((t) => t - 1);
    } catch (e) {
      console.error("Delete failed:", e);
    } finally {
      setDeleting(null);
    }
  };

  return (
    <main className="max-w-lg mx-auto px-4 pt-6 pb-8 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">历史记录</h1>
        <span className="text-xs text-[var(--text-muted)]">{total} 条</span>
      </div>

      <HistoryFilters onSearch={handleSearch} isLoading={loading} />

      {loading ? (
        <div className="flex items-center justify-center h-40">
          <div className="text-[var(--text-muted)] text-sm">加载中...</div>
        </div>
      ) : (
        <HistoryTable items={items} onDelete={handleDelete} isDeleting={deleting} />
      )}

      {hasMore && !loading && (
        <button
          onClick={handleLoadMore}
          disabled={loadingMore}
          className="w-full py-3 text-sm text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors disabled:opacity-50"
        >
          {loadingMore ? "加载中..." : "加载更多"}
        </button>
      )}
    </main>
  );
}