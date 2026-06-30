import type { HistoryItem as HistoryItemType } from "@/lib/types";
import { HistoryItem } from "./HistoryItem";

interface HistoryListProps {
  items: HistoryItemType[];
  onLoadMore?: () => void;
  hasMore?: boolean;
  isLoading?: boolean;
}

export function HistoryList({ items, onLoadMore, hasMore, isLoading }: HistoryListProps) {
  if (items.length === 0 && !isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-[var(--text-muted)]">
        <span className="text-4xl mb-3">📋</span>
        <p className="text-sm">暂无历史记录</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <HistoryItem key={item.analysis_id} item={item} />
      ))}
      {hasMore && (
        <button
          onClick={onLoadMore}
          disabled={isLoading}
          className="w-full py-3 text-sm text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors disabled:opacity-50"
        >
          {isLoading ? "加载中..." : "加载更多"}
        </button>
      )}
    </div>
  );
}