import copy
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_platform.observability import log_retrieval_results
from reasoning_agent import strategy_retrieval
from reasoning_agent.action_graph.strategy_cards import build_strategy_cards


def test_weight_loading_reports_completion_and_cache_reuse(tmp_path, monkeypatch, capsys):
    model = object()
    factory = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=factory))
    monkeypatch.setattr(strategy_retrieval, "ensure_model_weights", Mock())
    resource = strategy_retrieval._SharedEmbeddingModel(tmp_path, "cpu")
    assert resource.get_model() is model
    assert resource.get_model() is model
    factory.assert_called_once_with(str(tmp_path), device="cpu")
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.count("[权重加载开始]") == 1
    assert output.err.count("[权重加载完成]") == 1
    assert output.err.count("[权重缓存复用]") == 1
    assert "设备=cpu" in output.err and "耗时=" in output.err
    assert str(tmp_path) not in output.err


def test_weight_failure_is_logged_without_exception_text_and_can_retry(tmp_path, monkeypatch, capsys):
    factory = Mock(side_effect=[ValueError("private response and local path"), object()])
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=factory))
    monkeypatch.setattr(strategy_retrieval, "ensure_model_weights", Mock())
    resource = strategy_retrieval._SharedEmbeddingModel(tmp_path, "cpu")
    with pytest.raises(ValueError):
        resource.get_model()
    assert resource.model is None
    assert resource.get_model() is not None
    output = capsys.readouterr().err
    assert "[权重加载失败]" in output and "ValueError" in output
    assert "private response" not in output
    assert "[权重加载完成]" in output


def test_final_strategy_logs_keep_ranks_scores_and_actual_injection(capsys):
    results = [
        {"id": "low", "name": "Low confidence", "score": 0.25, "vector_score": 0.2},
        {"id": "used", "name": "Useful strategy", "score": 0.875, "vector_score": 0.75},
        {"id": "overflow", "name": "Too large", "score": 0.6, "description": "x" * 5000},
    ]
    original = copy.deepcopy(results)
    cards = build_strategy_cards(results, max_chars=1000, detail_levels=["low", "high", "high"])
    log_retrieval_results("test-task", results, cards.executor)
    lines = capsys.readouterr().out.splitlines()
    assert "最终召回=3 条" in lines[0]
    assert "排名=1 ID=low" in lines[1] and "解题注入=否" in lines[1]
    assert "排名=2 ID=used" in lines[2] and "解题注入=是" in lines[2]
    assert "score=0.875000" in lines[2] and "vector_score=0.750000" in lines[2]
    assert "解题注入=否" in lines[3]
    assert results == original


def test_empty_strategy_results_are_explicit(capsys):
    log_retrieval_results("test-task", [], "")
    assert "最终召回=0 条；解题策略卡=未注入" in capsys.readouterr().out
