"""Exercise library management on a dedicated Fake backend, without model calls."""
import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8026")
    parser.add_argument("--output-dir", type=Path, default=Path("sample_outputs/library_qa"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url) as api:
        health = api.get("/health/ready").json()
        assert health["runtime_mode"] == "fake" and health["custom_library"] is True
        assert api.get("/v1/library").json()["items"] == [], "Use an empty, disposable library."
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        for name, width, height in [("desktop", 1440, 1000), ("mobile", 390, 844), ("narrow", 320, 740)]:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())

            def pace_writes(route):
                if route.request.method != "GET":
                    time.sleep(.55)
                route.continue_()

            page.route("**/v1/library**", pace_writes)

            def open_panel():
                if width > 760:
                    page.get_by_role("button", name="策略与 Skills", exact=True).click()
                else:
                    page.get_by_role("button", name="自定义知识", exact=True).click()
                panel = page.get_by_role("dialog", name="自定义知识", exact=True)
                expect(panel).to_be_visible()
                expect(panel.get_by_text("正在载入", exact=True)).not_to_be_visible()
                return panel

            page.goto(args.url + "/chat/")
            panel = open_panel()
            title = "QA " + name + " 双射计数 " + uuid4().hex[:6]
            panel.get_by_label("标题", exact=True).fill(title)
            panel.get_by_label("分类", exact=True).fill("组合数学")
            panel.get_by_label("关键词", exact=True).fill("bijection counting")
            panel.get_by_label("知识内容", exact=True).fill("正文检索标记：一一对应。先证明映射单射，再证明满射。")
            panel.get_by_role("button", name="保存", exact=True).click()
            expect(panel.get_by_role("status")).to_have_text("已保存")
            row = panel.locator(".library-item").filter(has_text=title)
            expect(row).to_contain_text("已启用")
            panel.get_by_label("搜索自定义知识").fill("正文检索标记")
            expect(row).to_be_visible()
            panel.get_by_label("搜索自定义知识").fill("no_matching_material")
            expect(panel.get_by_text("没有匹配的条目")).to_be_visible()
            panel.get_by_label("搜索自定义知识").fill("")
            panel.get_by_label("知识内容", exact=True).fill("编辑后的正文检索标记：双射需要两个方向的证明。")
            panel.get_by_label("启用", exact=True).uncheck()
            panel.get_by_role("button", name="保存", exact=True).click()
            expect(row).to_contain_text("已停用")
            panel.get_by_label("启用", exact=True).check()
            panel.get_by_role("button", name="保存", exact=True).click()
            expect(row).to_contain_text("已启用")
            panel.get_by_role("tab", name="Skills").click()
            markdown = "# 双射 Skill\n\n## 检查条件\n确保映射的定义域和值域一致。\n\n$$|A|=|B|$$\n"
            filename = f"qa-method-{name}.md"
            panel.locator('input[type="file"]').set_input_files({
                "name": filename, "mimeType": "text/markdown", "buffer": markdown.encode(),
            })
            expect(panel.get_by_label("标题", exact=True)).to_have_value(filename[:-3])
            expect(panel.get_by_label("知识内容", exact=True)).to_have_value(markdown)
            panel.get_by_role("button", name="预览内容", exact=True).click()
            expect(panel.locator(".library-preview .katex")).to_have_count(1)
            panel.get_by_role("button", name="保存", exact=True).click()
            expect(panel.get_by_role("status")).to_have_text("已保存")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output_dir / f"{name}-preview.png"))
            page.reload()
            panel = open_panel()
            row = panel.locator(".library-item").filter(has_text=title)
            expect(row).to_contain_text("已启用")
            row.click()
            expect(panel.get_by_label("知识内容", exact=True)).to_have_value("编辑后的正文检索标记：双射需要两个方向的证明。")
            panel.get_by_role("button", name="删除条目", exact=True).click()
            panel.get_by_role("button", name="确认删除", exact=True).click()
            expect(row).to_have_count(0)
            panel.get_by_role("tab", name="Skills").click()
            row = panel.locator(".library-item").filter(has_text=filename[:-3])
            row.click()
            expect(panel.get_by_label("知识内容", exact=True)).to_have_value(markdown.strip())
            panel.get_by_role("button", name="删除条目", exact=True).click()
            panel.get_by_role("button", name="确认删除", exact=True).click()
            expect(row).to_have_count(0)
            panel.locator('input[type="file"]').set_input_files({
                "name": "invalid.md", "mimeType": "text/markdown", "buffer": b"\xff\xfe\x80",
            })
            expect(panel.get_by_role("alert")).to_contain_text("UTF-8")
            panel.locator('input[type="file"]').set_input_files({
                "name": "large.md", "mimeType": "text/markdown", "buffer": b"x" * 50001,
            })
            expect(panel.get_by_role("alert")).to_contain_text("50 KB")
            panel.get_by_role("button", name="关闭知识面板").click()
            expect(panel).not_to_be_visible()
            assert not errors, errors
            print(json.dumps({"viewport": name, "crud_import_preview_reload": "passed", "browser_errors": errors}))
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
