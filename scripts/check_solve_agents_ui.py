"""Run against an isolated Fake app with a synthetic connection tester and empty agent catalog."""
import argparse
import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8032")
    parser.add_argument("--output-dir", type=Path, default=Path("sample_outputs/agents_qa"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url) as api:
        assert api.get("/health/ready").json()["runtime_mode"] == "fake"
        assert len(api.get("/v1/solve-agents").json()["items"]) == 1, "Use a disposable empty catalog."
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        for name, width, height in [("desktop", 1440, 1000), ("mobile", 390, 844), ("narrow", 320, 740)]:
            if name != "desktop":
                time.sleep(10)  # The deliberate connection-test action has a global cooldown.
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors, submitted = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())

            def request(request):
                if request.method == "POST" and request.url.endswith("/tasks"):
                    submitted.append(request.post_data_json)

            page.on("request", request)

            def open_panel():
                button = page.get_by_role("button", name="模型与 Agents", exact=True)
                if not button.is_visible():
                    page.get_by_role("button", name="会话列表", exact=True).click()
                page.get_by_role("button", name="模型与 Agents", exact=True).click()
                panel = page.get_by_role("dialog", name="模型与 Agents", exact=True)
                expect(panel).to_be_visible()
                expect(panel.get_by_role("button", name="保存", exact=True)).to_be_enabled()
                return panel

            page.goto(args.url + "/chat/")
            expect(page.get_by_label("Solve Agent", exact=True)).to_be_enabled()
            panel = open_panel()
            title, model = "QA solver " + name, "synthetic-" + name
            panel.get_by_label("名称", exact=True).fill(title)
            panel.get_by_label("API 地址", exact=True).fill("http://127.0.0.1:1/v1/chat/completions")
            panel.get_by_label("模型名称", exact=True).fill(model)
            panel.get_by_role("button", name="保存", exact=True).click()
            expect(panel.get_by_role("status")).to_have_text("已保存")
            row = panel.locator(".library-item").filter(has_text=title)
            expect(row).to_contain_text("v1")
            panel.get_by_role("button", name="测试连接", exact=True).click()
            expect(panel.get_by_role("status")).to_have_text("连接测试通过")
            panel.get_by_role("button", name="设为默认", exact=True).click()
            expect(panel.get_by_role("status")).to_have_text("已设为默认")
            page.screenshot(path=str(args.output_dir / f"{name}-panel.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            panel.get_by_role("button", name="关闭模型配置").click()
            selector = page.get_by_label("Solve Agent", exact=True)
            expect(selector.locator("option:checked")).to_contain_text(title)
            chosen = selector.input_value()
            page.get_by_label("数学问题", exact=True).fill("Synthetic solver selection fixture.")
            page.get_by_role("button", name="发送问题", exact=True).click()
            expect(page.locator(".task-agent").last).to_contain_text(model)
            assert submitted[-1]["solve_agent_id"] == chosen
            expect(page.get_by_test_id("answer").last).to_contain_text("Fake Runtime completed")
            page.screenshot(path=str(args.output_dir / f"{name}-selection.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            panel = open_panel()
            panel.get_by_label("搜索 Agent", exact=True).fill(model)
            expect(panel.locator(".library-item")).to_have_count(1)
            row = panel.locator(".library-item").filter(has_text=title)
            row.click()
            panel.get_by_label("模型名称", exact=True).fill(model + "-v2")
            panel.get_by_role("button", name="保存", exact=True).click()
            expect(row).to_contain_text("v2")
            panel.get_by_label("启用", exact=True).uncheck()
            panel.get_by_role("button", name="保存", exact=True).click()
            expect(row).to_contain_text("已停用")
            panel.get_by_label("启用", exact=True).check()
            panel.get_by_role("button", name="保存", exact=True).click()
            expect(row).to_contain_text("v4")
            panel.get_by_role("button", name="删除 Agent", exact=True).click()
            expect(row).to_have_count(0)
            panel.get_by_role("button", name="关闭模型配置").click()
            expect(page.locator(".task-agent").last).to_contain_text(model + " · v1")
            expect(selector).to_have_value("builtin")
            assert not errors, errors
            print(json.dumps({"viewport": name, "crud_default_test_selection_history": "passed", "browser_errors": errors}))
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
