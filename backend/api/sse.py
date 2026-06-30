"""GET /api/analyze/{analysis_id}/stream — SSE real-time progress."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import json
import asyncio
import time

from backend.core import get_store

router = APIRouter()


@router.get("/api/analyze/{analysis_id}/stream")
async def stream_progress(analysis_id: str):
    """SSE endpoint for real-time analysis progress."""
    store = get_store()
    tracker = store.get(analysis_id)

    if tracker is None:
        raise HTTPException(status_code=404, detail=f"Analysis '{analysis_id}' not found")

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