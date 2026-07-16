"""GET /api/analyze/{analysis_id}/stream — SSE real-time progress.

P2.11 hotfix: handle the case where ``TrackerStore`` (in-memory) lost the
analysis on backend restart. For such analyses we still emit a single
``complete`` (or ``error``) event so the React client can transition out of
its loading state instead of silently hanging on the SSE connection.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import json
import asyncio

from backend.core import get_store
from backend.core.history_store import get_history_store

router = APIRouter()


@router.get("/api/analyze/{analysis_id}/stream")
async def stream_progress(analysis_id: str):
    """SSE endpoint for real-time analysis progress.

    - Live tracker: emits ``stage_complete`` / ``progress`` events until
      completion, then a final ``complete`` or ``error`` event.
    - Restarted analysis (TrackerStore lost it): emits one ``complete`` /
      ``error`` event from the HistoryStore entry and closes the stream.
    """
    store = get_store()
    tracker = store.get(analysis_id)

    if tracker is None:
        # P2.11 fallback: TrackerStore is in-memory and loses data on
        # restart. HistoryStore is JSON-backed and survives restarts.
        history = get_history_store()
        entry = history.get(analysis_id)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"分析 {analysis_id!r} 不存在或已过期, "
                    "请从历史列表选择新分析"
                ),
            )

        async def completed_from_history():
            if entry.error:
                yield {
                    "event": "error",
                    "data": json.dumps({"error": entry.error}),
                }
            else:
                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "signal": entry.signal,
                        "final_state": None,
                        "from_history": True,
                    }),
                }

        return StreamingResponse(
            completed_from_history(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def event_generator():
        last_completed = set(tracker.completed_stages)

        while tracker.is_running:
            current_completed = set(tracker.completed_stages)

            # Check for newly completed stages
            new_stages = current_completed - last_completed
            for stage in new_stages:
                report = tracker.stage_reports.get(stage, "")
                yield {
                    "event": "stage_complete",
                    "data": json.dumps({
                        "stage": stage,
                        "report": report[:500] if report else "",
                    }),
                }
            last_completed = current_completed

            # Send progress update
            yield {
                "event": "progress",
                "data": json.dumps({
                    "current_stage": tracker.current_stage,
                    "completed_stages": list(tracker.completed_stages),
                    "stats": {
                        "llm_calls": tracker.llm_calls,
                        "tool_calls": tracker.tool_calls,
                        "tokens_in": tracker.tokens_in,
                        "tokens_out": tracker.tokens_out,
                    },
                    "elapsed": tracker.elapsed,
                }),
            }

            await asyncio.sleep(2)

        # Send completion or error
        if tracker.error:
            yield {
                "event": "error",
                "data": json.dumps({"error": tracker.error}),
            }
        else:
            yield {
                "event": "complete",
                "data": json.dumps({
                    "signal": tracker.signal,
                    "final_state": tracker.final_state,
                }),
            }

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )