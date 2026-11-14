import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import App from './App';

it('uses one composer without mode switches or reference attachment controls', () => {
  const html = renderToStaticMarkup(<App />);
  expect(html).not.toContain('文字提问');
  expect(html).not.toContain('输入方式');
  expect(html).toContain('question-upload-slot');
  expect(html).toContain('数学问题');
  expect(html).not.toContain('参考附件');
  expect(html).not.toContain('上传附件');
  expect(html).not.toContain('参考来源');
  expect(html).toContain('aria-label="设置"');
  expect(html).not.toContain('策略与 Skills');
  expect(html).not.toContain('模型与 Agents');
  expect(html).not.toContain('<select');
});
