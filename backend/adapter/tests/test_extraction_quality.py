"""
Smoke test for extraction quality on Russian text.
Requires running Neo4j + LLM. Run manually:
    pytest tests/test_extraction_quality.py -v -s
"""
import pytest
import asyncio
from typing import AsyncGenerator

RULES_TEXT = """
5 жёстких правил работы:
1. СТОП-КРАН: если я прошу остановиться — останавливайся немедленно
2. НЕ ТРОГАЙ salt key — он настроен один раз навсегда  
3. Все API-ключи хранить ТОЛЬКО в .env файлах
4. Перед деплоем ВСЕГДА проверять docker-compose up
5. Логировать каждое изменение в git с осмысленным коммитом
"""

@pytest.mark.skipif(
    not pytest.importorskip("neo4j", reason="Neo4j not available"),
    reason="Integration test"
)
class TestExtractionQuality:
    """Manual smoke tests for extraction quality"""
    
    @pytest.mark.asyncio
    async def test_rules_extraction(self):
        """Each rule should be extracted as a separate fact"""
        # This test requires a running system
        # Run: pytest tests/test_extraction_quality.py::TestExtractionQuality::test_rules_extraction -v -s
        pass  # Placeholder - requires integration setup
