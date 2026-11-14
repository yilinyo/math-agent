"""Browser QA with explicitly synthetic timeline events and a dedicated Fake server."""
import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright


def timeline_fixture(task):
    events = []
    started = datetime.fromisoformat(task["accepted_at"])

    def emit(stage, event_type, **payload):
        sequence = len(events) + 1
        events.append({"task_id": task["id"], "session_id": task["session_id"],
                       "sequence": sequence, "stage_id": stage, "event_type": event_type,
                       "created_at": (started + timedelta(milliseconds=sequence)).isoformat(),
                       "payload": payload})

    for stage, text in [("profile", "本题按计算题组织解答，检查定义域和适用条件。"),
                         ("retrieve", "召回方法：代入与等式化简。"),
                         ("plan", "先展开公式，再代回检查符号。")]:
        emit(stage, "stage.started")
        emit(stage, "stage.explanation", content=text, kind="summary")
        if stage == "retrieve":
            emit(stage, "library.selected", references=[{"id": "fixture", "revision": 1, "kind": "skill", "title": "合成定义核验 Skill"}])
        emit(stage, "stage.completed")
    emit("solve", "stage.started")
    emit("solve", "stage.context", node="solve", round=1)
    emit("solve", "model.started", call_type="solver", operation_id="fixture-model")
    emit("solve", "answer.started", stream_id="fixture-solve", preview=True)
    emit("solve", "answer.delta", stream_id="fixture-solve", index=0,
         text="## 详细解题步骤\n合成首轮草稿：$x=1$。\n")
    emit("solve", "answer.completed", stream_id="fixture-solve", chunks=1)
    emit("solve", "model.completed", call_type="solver", operation_id="fixture-model", duration_ms=500, usage={"total_tokens": 32})
    for _ in range(130):
        emit("solve", "model.completed", duration_ms=10)
    emit("solve", "answer.started", stream_id="fixture-failed", preview=True)
    emit("solve", "answer.delta", stream_id="fixture-failed", index=0, text="应撤回的不完整草稿")
    emit("solve", "answer.discarded", stream_id="fixture-failed")
    emit("solve", "model.failed", error_code="incomplete_model_stream", error_type="ChatCompletionError",
         http_status=200, attempts=1, duration_ms=300)
    emit("solve", "stage.completed")
    for round_number in (2, 3):
        emit("verify", "stage.started")
        emit("verify", "stage.explanation", content="检查符号与原题约束，当前候选仍需修正。", kind="summary")
        emit("verify", "stage.completed")
        emit("repair", "stage.started")
        emit("repair", "stage.context", node="repair", round=round_number)
        emit("repair", "stage.explanation", title="本轮修复依据", content="根据已发现的符号问题重新代入。", kind="summary")
        emit("repair", "stage.explanation", kind="solution",
             content=f"## 详细解题步骤\n合成第{round_number}轮修复：$x={round_number}$。\n\n"
                     r"$$\frac{1}{2}+\frac{1}{3}=\frac{5}{6}$$")
        emit("repair", "stage.completed")
    emit("finalize", "stage.started")
    emit("finalize", "reasoning.event", operation="final_candidate_checked", accepted=False,
         format_failures=["multiple_final_candidates"], hard_failure_count=0, budget_exhausted=False)
    emit("finalize", "stage.outcome", node="finalize", round=3, status="rejected", next_stage="terminal", duration_ms=5)
    emit("finalize", "stage.explanation", content="合成展示样例结束，以下为 Fake 运行时的最终结果。", kind="summary")
    emit("finalize", "stage.completed")
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8021")
    parser.add_argument("--output-dir", type=Path, default=Path("sample_outputs/timeline_qa"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url, timeout=10) as api:
        assert api.get("/health/ready").json()["runtime_mode"] == "fake"
        response = api.post("/v1/sessions", json={})
        response.raise_for_status()
        session = response.json()["id"]
        tasks = []
        for number in (1, 2):
            response = api.post(f"/v1/sessions/{session}/tasks", headers={"Idempotency-Key": str(uuid4())},
                                json={"problem": f"合成时间线展示样例 {number}（非模型解答）"})
            response.raise_for_status()
            task = response.json()
            deadline = time.monotonic() + 20
            while task["status"] not in {"succeeded", "failed", "cancelled"}:
                assert time.monotonic() < deadline
                time.sleep(.1)
                task = api.get(f"/v1/sessions/{session}/tasks/{task['id']}").json()
            assert task["status"] == "succeeded"
            tasks.append(task)
    fixtures = {task["id"]: timeline_fixture(task) for task in tasks}

    def replay(route):
        url = urlparse(route.request.url)
        identifier = url.path.split("/tasks/")[1].split("/")[0]
        after = int(parse_qs(url.query).get("after_sequence", ["0"])[0])
        rows = [event for event in fixtures[identifier] if event["sequence"] > after][:500]
        route.fulfill(json={"events": rows, "next_sequence": rows[-1]["sequence"] if rows else after})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        for name, width, height in [("desktop", 1440, 1000), ("mobile", 390, 844), ("narrow", 320, 740)]:
            context = browser.new_context(viewport={"width": width, "height": height})
            context.add_init_script(f"localStorage.setItem('maths-chat-selected-v1', {json.dumps(session)})")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/v1/sessions/*/tasks/*/trace?*", replay)
            for _ in range(2):
                page.goto(args.url + "/chat/")
                expect(page.get_by_test_id("solution-timeline")).to_have_count(2)
                timelines = page.get_by_test_id("solution-timeline")
                for index in (0, 1):
                    timeline = timelines.nth(index)
                    expect(timeline).to_contain_text("合成首轮草稿")
                    expect(timeline).to_contain_text("合成第2轮修复")
                    expect(timeline).to_contain_text("合成第3轮修复")
                    expect(timeline).to_contain_text("第 3 轮公开推导")
                    expect(timeline).not_to_contain_text("应撤回的不完整草稿")
                    expect(timeline.locator(".katex").first).to_be_attached()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
            last = page.get_by_test_id("solution-timeline").last
            last.get_by_label("仅异常与待确认").check()
            last.get_by_label("搜索运行记录").fill("模型响应中断")
            failure = last.get_by_text("推导求解：模型响应中断，未收到完整解答。", exact=False)
            failure.scroll_into_view_if_needed()
            expect(failure).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output_dir / f"{name}-failure.png"))
            last.get_by_label("搜索运行记录").fill("")
            expect(last).to_contain_text("存在冲突或尚无法证明等价的多个答案")
            last.get_by_label("仅异常与待确认").uncheck()
            last.locator(".timeline-draft-label").last.scroll_into_view_if_needed()
            page.screenshot(path=str(args.output_dir / f"{name}.png"))
            last.screenshot(path=str(args.output_dir / f"{name}-timeline.png"))
            last.locator(":scope > summary").click()
            expect(last.locator(":scope > ol")).not_to_be_visible()

            page.goto(args.url + f"/trace-viewer#session={session}&task={tasks[-1]['id']}")
            expect(page.locator("#event-list .trace-stage").first).to_be_visible()
            expect(page.locator("#trace-more")).to_be_visible()
            before = page.locator(".trace-rows > li").count()
            page.locator("#trace-more").click()
            assert page.locator(".trace-rows > li").count() > before
            page.get_by_label("仅异常与待确认").check()
            expect(page.locator("#event-list")).to_contain_text("存在冲突或尚无法证明等价的多个答案")
            page.get_by_label("搜索运行记录").fill("响应中断")
            expect(page.locator("#event-list")).to_contain_text("模型响应中断")
            assert page.locator(".trace-rows > li").count() == 1
            page.locator("#task-section").scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output_dir / f"{name}-trace.png"))
            page.get_by_label("搜索运行记录").fill("")
            page.get_by_label("仅异常与待确认").uncheck()
            page.locator("#trace-stage").select_option("retrieve")
            expect(page.locator("#event-list")).to_contain_text("合成定义核验 Skill")
            page.locator("#trace-stage").select_option("finalize")
            page.locator("#json-tab").click()
            expect(page.locator("#raw-trace")).to_contain_text("multiple_final_candidates")
            with page.expect_download() as download:
                page.get_by_label("下载脱敏 Trace").click()
            assert download.value.suggested_filename.endswith(".json")
            assert not errors, errors
            print(json.dumps({"viewport": name, "history_reload": "passed", "rounds": 3, "browser_errors": errors}))
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
