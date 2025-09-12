"""
Coleta e análise de dados de mercado
"""
import aiohttp
import asyncio
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import json
from tenacity import retry, stop_after_attempt, wait_exponential
from src.config import config
from src.database import Database

logger = logging.getLogger(__name__)

class MarketDataCollector:
    """Coletor de dados de mercado Bitcoin"""
    
    def __init__(self, db: Database):
        self.db = db
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def get_btc_price(self) -> Dict[str, Any]:
        """
        Obtém preço atual do Bitcoin em USD e BRL
        Retorna: {usd: float, brl: float, change_24h: float, volume_24h: float}
        """
        try:
            # Tenta primeiro cache
            cached = await self.db.get_cache('btc_price')
            if cached:
                return json.loads(cached)
            
            # Busca preço via CoinGecko
            url = f"{config.COINGECKO_BASE_URL}/simple/price"
            params = {
                'ids': 'bitcoin',
                'vs_currencies': 'usd,brl',
                'include_24hr_change': 'true',
                'include_24hr_vol': 'true',
                'include_market_cap': 'true'
            }
            
            if config.COINGECKO_API_KEY:
                params['x_cg_api_key'] = config.COINGECKO_API_KEY
            
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                
                result = {
                    'usd': data['bitcoin']['usd'],
                    'brl': data['bitcoin']['brl'],
                    'change_24h': data['bitcoin']['usd_24h_change'],
                    'volume_24h': data['bitcoin']['usd_24h_vol'],
                    'market_cap': data['bitcoin']['usd_market_cap'],
                    'timestamp': datetime.now().isoformat()
                }
                
                # Salva no cache
                await self.db.set_cache('btc_price', json.dumps(result))
                
                logger.info(f"Preço BTC atualizado: ${result['usd']:,.2f}")
                return result
                
        except Exception as e:
            logger.error(f"Erro ao obter preço BTC: {e}")
            # Fallback para Binance
            return await self._get_btc_price_binance()
    
    async def _get_btc_price_binance(self) -> Dict[str, Any]:
        """Fallback: obtém preço via Binance"""
        try:
            url = f"{config.BINANCE_BASE_URL}/ticker/24hr"
            params = {'symbol': 'BTCUSDT'}
            
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                
                # Obtém taxa USD/BRL
                brl_rate = await self._get_usd_brl_rate()
                
                usd_price = float(data['lastPrice'])
                return {
                    'usd': usd_price,
                    'brl': usd_price * brl_rate,
                    'change_24h': float(data['priceChangePercent']),
                    'volume_24h': float(data['volume']) * usd_price,
                    'timestamp': datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"Erro no fallback Binance: {e}")
            raise
    
    async def _get_usd_brl_rate(self) -> float:
        """Obtém taxa de câmbio USD/BRL"""
        try:
            # Cache
            cached = await self.db.get_cache('usd_brl_rate')
            if cached:
                return float(cached)
            
            # API do BCB
            async with self.session.get(config.BCB_URL) as response:
                data = await response.json()
                rate = float(data[0]['valor'])
                
                # Cache por 1 hora
                await self.db.set_cache('usd_brl_rate', str(rate))
                return rate
                
        except Exception as e:
            logger.error(f"Erro ao obter taxa USD/BRL: {e}")
            # Fallback para taxa fixa aproximada
            return 6.08
    
    async def get_fear_greed_index(self) -> Dict[str, Any]:
        """Obtém índice Fear & Greed"""
        try:
            cached = await self.db.get_cache('fear_greed')
            if cached:
                return json.loads(cached)
            
            async with self.session.get(config.FEAR_GREED_URL) as response:
                data = await response.json()
                
                result = {
                    'value': int(data['data'][0]['value']),
                    'classification': data['data'][0]['value_classification'],
                    'timestamp': data['data'][0]['timestamp']
                }
                
                await self.db.set_cache('fear_greed', json.dumps(result))
                
                logger.info(f"Fear & Greed: {result['value']} - {result['classification']}")
                return result
                
        except Exception as e:
            logger.error(f"Erro ao obter Fear & Greed: {e}")
            return {'value': 0, 'classification': 'Unknown'}
    
    async def get_btc_dominance(self) -> float:
        """Obtém dominância do Bitcoin"""
        try:
            cached = await self.db.get_cache('btc_dominance')
            if cached:
                return float(cached)
            
            url = f"{config.COINGECKO_BASE_URL}/global"
            
            async with self.session.get(url) as response:
                data = await response.json()
                dominance = data['data']['market_cap_percentage']['btc']
                
                await self.db.set_cache('btc_dominance', str(dominance))
                
                logger.info(f"Dominância BTC: {dominance:.2f}%")
                return dominance
                
        except Exception as e:
            logger.error(f"Erro ao obter dominância BTC: {e}")
            return 0.0
    
    async def get_funding_rate(self) -> float:
        """Obtém funding rate do Bitcoin (perpetual futures)"""
        try:
            url = f"{config.BINANCE_FUTURES_URL}/premiumIndex"
            params = {'symbol': 'BTCUSDT'}
            
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                funding_rate = float(data['lastFundingRate']) * 100
                
                logger.info(f"Funding Rate: {funding_rate:.4f}%")
                return funding_rate
                
        except Exception as e:
            logger.error(f"Erro ao obter funding rate: {e}")
            return 0.0
    
    async def get_liquidations(self) -> Dict[str, float]:
        """Obtém dados de liquidações (simplificado)"""
        # Nota: Para dados reais de liquidação, seria necessário
        # uma API especializada como CoinGlass
        try:
            # Simulação baseada em volume
            price_data = await self.get_btc_price()
            volume = price_data.get('volume_24h', 0)
            
            # Estimativa simplificada
            estimated_liquidations = {
                'total_24h': volume * 0.001,  # 0.1% do volume
                'longs': volume * 0.0004,
                'shorts': volume * 0.0006
            }
            
            return estimated_liquidations
            
        except Exception as e:
            logger.error(f"Erro ao estimar liquidações: {e}")
            return {'total_24h': 0, 'longs': 0, 'shorts': 0}
    
    async def calculate_rsi(self, period: int = 14) -> float:
        """Calcula RSI do Bitcoin"""
        try:
            # Para um RSI real, precisaríamos de dados históricos
            # Esta é uma aproximação baseada na variação 24h
            price_data = await self.get_btc_price()
            change_24h = price_data.get('change_24h', 0)
            
            # Aproximação simplificada do RSI
            if change_24h > 5:
                rsi = 70 + min(change_24h, 10)
            elif change_24h < -5:
                rsi = 30 - min(abs(change_24h), 10)
            else:
                rsi = 50 + (change_24h * 4)
            
            rsi = max(0, min(100, rsi))
            
            logger.info(f"RSI aproximado: {rsi:.2f}")
            return rsi
            
        except Exception as e:
            logger.error(f"Erro ao calcular RSI: {e}")
            return 50.0
    
    async def get_market_summary(self) -> Dict[str, Any]:
        """Obtém resumo completo do mercado"""
        try:
            # Coleta todos os dados em paralelo
            tasks = [
                self.get_btc_price(),
                self.get_fear_greed_index(),
                self.get_btc_dominance(),
                self.get_funding_rate(),
                self.get_liquidations(),
                self.calculate_rsi()
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            price_data = results[0] if not isinstance(results[0], Exception) else {}
            fear_greed = results[1] if not isinstance(results[1], Exception) else {}
            dominance = results[2] if not isinstance(results[2], Exception) else 0
            funding_rate = results[3] if not isinstance(results[3], Exception) else 0
            liquidations = results[4] if not isinstance(results[4], Exception) else {}
            rsi = results[5] if not isinstance(results[5], Exception) else 50
            
            return {
                'price': price_data,
                'fear_greed': fear_greed,
                'dominance': dominance,
                'funding_rate': funding_rate,
                'liquidations': liquidations,
                'rsi': rsi,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter resumo do mercado: {e}")
            return {}
    
    def check_breakeven_proximity(self, current_price: float) -> Tuple[bool, float]:
        """
        Verifica proximidade ao preço de breakeven do usuário
        Retorna: (está_próximo, percentual_diferença)
        """
        breakeven = config.USER_AVG_PRICE
        diff_percent = ((current_price - breakeven) / breakeven) * 100
        
        is_near = abs(diff_percent) <= (config.BREAKEVEN_THRESHOLD * 100)
        
        if is_near:
            logger.info(f"Preço próximo ao breakeven! Diferença: {diff_percent:.2f}%")
        
        return is_near, diff_percent