"""
Testes básicos para o módulo de mercado
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from src.market import MarketDataCollector
from src.database import Database

@pytest.fixture
async def db():
    """Fixture para banco de dados de teste"""
    database = Database("test.db")
    await database.connect()
    yield database
    await database.close()

@pytest.fixture
async def market_collector(db):
    """Fixture para coletor de mercado"""
    return MarketDataCollector(db)

@pytest.mark.asyncio
async def test_btc_price_structure(market_collector):
    """Testa estrutura do retorno de preço"""
    with patch.object(market_collector, 'session', new_callable=AsyncMock) as mock_session:
        # Mock da resposta da API
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            'bitcoin': {
                'usd': 107000,
                'brl': 650000,
                'usd_24h_change': 3.5,
                'usd_24h_vol': 28000000000,
                'usd_market_cap': 2100000000000
            }
        })
        
        mock_session.get.return_value.__aenter__.return_value = mock_response
        
        async with market_collector:
            market_collector.session = mock_session
            result = await market_collector.get_btc_price()
        
        assert 'usd' in result
        assert 'brl' in result
        assert 'change_24h' in result
        assert 'volume_24h' in result
        assert result['usd'] == 107000

@pytest.mark.asyncio
async def test_breakeven_proximity(market_collector):
    """Testa cálculo de proximidade ao breakeven"""
    async with market_collector:
        # Testa preço próximo ao breakeven
        is_near, diff = market_collector.check_breakeven_proximity(115000)
        assert is_near == True
        assert abs(diff) < 2
        
        # Testa preço distante do breakeven
        is_near, diff = market_collector.check_breakeven_proximity(100000)
        assert is_near == False

@pytest.mark.asyncio
async def test_rsi_calculation(market_collector):
    """Testa cálculo aproximado de RSI"""
    async with market_collector:
        with patch.object(market_collector, 'get_btc_price', 
                         return_value={'change_24h': 10}):
            rsi = await market_collector.calculate_rsi()
            assert rsi >= 70  # Deve indicar overbought
        
        with patch.object(market_collector, 'get_btc_price', 
                         return_value={'change_24h': -10}):
            rsi = await market_collector.calculate_rsi()
            assert rsi <= 30  # Deve indicar oversold

@pytest.mark.asyncio
async def test_market_summary_keys(market_collector):
    """Testa se o resumo de mercado contém todas as chaves necessárias"""
    async with market_collector:
        with patch.object(market_collector, 'get_btc_price', 
                         return_value={'usd': 107000, 'brl': 650000, 
                                     'change_24h': 3.5, 'volume_24h': 28e9}):
            with patch.object(market_collector, 'get_fear_greed_index',
                            return_value={'value': 76, 'classification': 'Extreme Greed'}):
                
                summary = await market_collector.get_market_summary()
                
                assert 'price' in summary
                assert 'fear_greed' in summary
                assert 'dominance' in summary
                assert 'funding_rate' in summary
                assert 'liquidations' in summary
                assert 'rsi' in summary
                assert 'timestamp' in summary