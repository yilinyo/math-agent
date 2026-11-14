"""Check settings navigation against an isolated Fake backend without model calls."""
import argparse
from contextlib import contextmanager
from pathlib import Path
import socket
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import expect, sync_playwright


@contextmanager
def fixture_server():
    import numpy as np
    import uvicorn
    from agent_platform.app import create_app
    from agent_platform.knowledge_resources import KnowledgeResources, encoded
    from agent_platform.solve_agents import SolveAgents
    from reasoning_agent.lexical_strategy_retrieval import build_lexical_payloads

    with tempfile.TemporaryDirectory(prefix='maths-resource-ui-') as directory:
        root = Path(directory)
        data = root / 'strategy_data'
        data.mkdir()
        for category in ('linear_algebra', 'probability'):
            path = root / 'skill2_en' / category / f'{category}_skill.md'
            path.parent.mkdir(parents=True)
            path.write_text(f'# {category}\n\nFixture handbook with $x^2$.', encoding='utf-8')
        cards = [{'id': i, 'name': f'Fixture strategy {i}', 'description': 'Rank method', 'tags': ['rank'],
                  'applicability': ['Check rank'], 'steps': [{'step': 'Prove rank', 'detail': 'Check assumptions'}],
                  'example': {'problem': 'Example', 'solution': 'Proof'}} for i in range(42)]
        lexical, manifest = build_lexical_payloads(cards)
        for name, value in [('strategy_meta.json', cards), ('strategy_lexical_index.json', lexical),
                            ('strategy_lexical_manifest.json', manifest), ('strategy_index.json', {
                                'embedding_model': 'Qwen/Qwen3-Embedding-0.6B', 'embedding_dim': 1024,
                                'num_strategies': len(cards)})]:
            (data / name).write_bytes(encoded(value))
        np.save(data / 'strategy_embeddings.npy', np.ones((len(cards), 1024), dtype=np.float32) / 32)
        resources = KnowledgeResources(root, embedder=lambda _: np.ones(1024))
        app = create_app(resources=resources, solve_agents=SolveAgents(root / 'agents', available=False),
                         question_dir=root / 'questions', rate_limits=False)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
            thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
            thread.start()
            try:
                yield f'http://127.0.0.1:{port}'
            finally:
                server.should_exit = True
                thread.join(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/maths-settings-qa"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with fixture_server() as url:
        check(url, args.output_dir)


def check(url, output_dir):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for name, width, height in [("desktop", 1440, 1000), ("mobile", 390, 844), ("narrow", 320, 740)]:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors = []
            submitted = []
            dialog_decision = {"accept": False}
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept() if dialog_decision["accept"] else dialog.dismiss())
            page.on("request", lambda request: submitted.append(request.post_data_json)
                    if request.method == "POST" and request.url.endswith("/tasks") else None)
            page.goto(url + "/chat/")
            expect(page.get_by_test_id("runtime-mode")).to_contain_text("演示运行时")
            expect(page.get_by_label("数学问题", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="模型与 Agents", exact=True)).not_to_be_visible()
            expect(page.locator("select:visible")).to_have_count(0)
            if not page.get_by_role("button", name="新建会话", exact=True).is_visible():
                page.get_by_role("button", name="会话列表", exact=True).click()
            page.get_by_role("button", name="新建会话", exact=True).click()
            page.get_by_label("数学问题", exact=True).fill("求解 x + 1 = 2")
            page.screenshot(path=str(output_dir / f"{name}-chat.png"))
            page.get_by_role("button", name="设置", exact=True).click()
            expect(page).to_have_url(url + "/chat/#/settings/general")
            page.get_by_label("解答方式", exact=True).select_option("detailed")
            page.get_by_role("button", name="模型与 Agents", exact=True).click()
            region = page.get_by_role("region", name="模型与 Agents", exact=True)
            expect(region.get_by_role("button", name="默认 Solve Agent", exact=False)).to_be_visible()
            expect(page.get_by_role("dialog")).to_have_count(0)
            region.get_by_label("名称", exact=True).fill("未保存配置")
            page.get_by_role("button", name="策略与 Skills", exact=True).click()
            expect(page).to_have_url(url + "/chat/#/settings/agents")
            expect(region.get_by_label("名称", exact=True)).to_have_value("未保存配置")
            dialog_decision["accept"] = True
            page.get_by_role("button", name="策略与 Skills", exact=True).click()
            library = page.get_by_role("region", name="策略与 Skills", exact=True)
            expect(library.get_by_role("tab", name="Skills")).to_be_visible()
            expect(library.locator('.resource-status')).to_contain_text('策略总数')
            library.get_by_role('button', name='新增策略', exact=True).click()
            new_editor = library.get_by_label('策略 JSON 内容', exact=True)
            library.get_by_role('button', name='保存', exact=True).click()
            expect(library.get_by_role('alert')).to_contain_text('example')
            import json
            new_card = json.loads(new_editor.input_value())
            assert 'id' not in new_card
            new_card.update(name='New UI strategy ' + name, tags=['bijection'], description='Construct inverse maps',
                            applicability=['Finite sets'], steps=[{'step': 'Prove', 'detail': 'Verify both inverse maps'}],
                            example={'problem': 'Count subsets', 'solution': 'Use indicator vectors'})
            new_editor.fill(json.dumps(new_card))
            page.screenshot(path=str(output_dir / f'{name}-new-strategy.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            library.get_by_role('button', name='保存', exact=True).click()
            expect(library.locator('.resource-notice')).to_contain_text('已新增 · ID')
            created_id = json.loads(new_editor.input_value())['id']
            assert isinstance(created_id, int) and created_id >= 42
            expect(library.locator('.resources-list')).to_contain_text('New UI strategy ' + name)
            library.get_by_label('搜索资源', exact=True).fill('')
            expect(library.get_by_role('button', name='下一页', exact=True)).to_be_enabled()
            library.get_by_role('button', name='下一页', exact=True).click()
            expect(library.get_by_role('button', name='Fixture strategy 41', exact=False)).to_be_visible()
            library.get_by_label('搜索资源', exact=True).fill('Fixture strategy 0')
            strategy = library.get_by_role('button', name='Fixture strategy 0', exact=False)
            expect(strategy).to_be_visible()
            strategy.click()
            library.get_by_role('button', name='编辑资源', exact=True).click()
            editor = library.get_by_label('策略 JSON 内容', exact=True)
            card = json.loads(editor.input_value())
            card['description'] = 'Updated rank method ' + name
            editor.fill(json.dumps(card))
            library.get_by_role('button', name='保存', exact=True).click()
            expect(library.get_by_text('已保存', exact=True)).to_be_visible()
            library.get_by_role("tab", name="Skills").click()
            library.get_by_role('button', name='Linear Algebra', exact=False).click()
            expect(library.locator('.resource-preview .katex')).to_have_count(1)
            library.get_by_role('button', name='编辑资源', exact=True).click()
            library.get_by_label('Skill Markdown 内容', exact=True).fill('# Rank\n\nUpdated handbook ' + name + ' $x^2$')
            dialog_decision['accept'] = False
            page.get_by_role('button', name='返回对话', exact=True).click()
            expect(page).to_have_url(url + '/chat/#/settings/library')
            library.get_by_role("button", name="保存", exact=True).click()
            expect(library.get_by_text('已保存', exact=True)).to_be_visible()
            page.reload()
            library.get_by_role('tab', name='Skills', exact=True).click()
            library.get_by_role('button', name='Linear Algebra', exact=False).click()
            expect(library.locator('.resource-preview')).to_contain_text('Updated handbook ' + name)
            page.screenshot(path=str(output_dir / f"{name}-library.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role("button", name="模型与 Agents", exact=True).click()
            expect(region).to_be_visible()
            page.screenshot(path=str(output_dir / f"{name}-agents.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.go_back()
            expect(library).to_be_visible()
            page.go_forward()
            expect(region).to_be_visible()
            page.get_by_role("button", name="返回对话", exact=True).click()
            # Reload intentionally resets the in-memory chat draft; fresh navigation preserves it below.
            page.get_by_label('数学问题', exact=True).fill('求解 x + 1 = 2')
            page.get_by_role("button", name="设置", exact=True).click()
            page.get_by_label('解答方式', exact=True).select_option('detailed')
            page.get_by_role("button", name="返回对话", exact=True).click()
            expect(page.get_by_label('数学问题', exact=True)).to_have_value('求解 x + 1 = 2')
            page.get_by_label("数学问题", exact=True).fill("求解 x + 1 = 2")
            expect(page.get_by_role("button", name="发送问题", exact=True)).to_be_enabled()
            previous_count = page.get_by_test_id('exchange').count()
            page.get_by_role("button", name="发送问题", exact=True).click()
            expect(page.get_by_test_id("exchange")).to_have_count(previous_count + 1)
            expect(page.get_by_test_id('exchange').last.locator('.answer-toolbar')).to_be_visible(timeout=20000)
            assert submitted[-1]["response_style"] == "detailed"
            page.get_by_role("button", name="执行进度", exact=True).click()
            expect(page.get_by_role("dialog", name="执行进度", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role("button", name="关闭面板", exact=True).click()
            page.get_by_role("button", name="设置", exact=True).click()
            expect(page.get_by_role("heading", name="对话偏好", exact=True)).to_be_visible()
            page.reload()
            expect(page.get_by_role("heading", name="对话偏好", exact=True)).to_be_visible()
            assert not errors, errors
            print(f"PASS {name}: strategy create/validation/search, navigation, unsaved form, Skill save, chat draft, deep link, send, progress")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
