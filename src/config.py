"""
Configurações centralizadas do bot
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import Optional
import logging

# Carrega variáveis de ambiente
load_dotenv()

# Configuração de logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.getenv('LOG_FILE', 'logs/bot.log'))
    ]
)

@dataclass
class Config:
    """Configuração principal do bot"""
    
    # Telegram
    BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    USER_CHAT_ID: str = os.getenv('USER_CHAT_ID', '')
    
    # User Position
    USER_BTC_POSITION: float = float(os.getenv('USER_BTC_POSITION', '0.08282513'))
    USER_AVG_PRICE: float = float(os.getenv('USER_AVG_PRICE', '115318.90'))
    BREAKEVEN_THRESHOLD: float = 0.02  # 2% próximo ao breakeven
    
    # APIs
    COINGECKO_API_KEY: Optional[str] = os.getenv('COINGECKO_API_KEY')
    BINANCE_API_KEY: Optional[str] = os.getenv('BINANCE_API_KEY')
    BINANCE_SECRET_KEY: Optional[str] = os.getenv('BINANCE_SECRET_KEY')
    
    # URLs das APIs
    COINGECKO_BASE_URL: str = 'https://api.coingecko.com/api/v3'
    BINANCE_BASE_URL: str = 'https://api.binance.com/api/v3'
    BINANCE_BASE_URL = 'https://api.binance.com/api/v3'
    BINANCE_FUTURES_URL = 'https://fapi.binance.com/fapi/v1'    # USDT-M Futures (novo)
    FEAR_GREED_URL: str = 'https://api.alternative.me/fng/'
    BCB_URL: str = 'https://api.bcb.gov.br/dados/serie/bcdata.sgs.10813/dados/ultimos/1?formato=json'
    
    # Database
    DATABASE_PATH: str = os.getenv('DATABASE_PATH', 'data/bot.db')
    
    # Redis
    USE_REDIS: bool = os.getenv('USE_REDIS', 'false').lower() == 'true'
    REDIS_URL: str = os.getenv('REDIS_URL', 'redis://localhost:6379')
    
    # Intervals
    CHECK_INTERVAL: int = 300  # 5 minutos em segundos
    ALERT_RETRY_INTERVAL: int = 300  # 5 minutos
    ALERT_RETRY_INTERVAL_LONG: int = 900  # 15 minutos
    MAX_ALERT_RETRIES: int = 3
    
    # Timezone
    TIMEZONE: str = os.getenv('TIMEZONE', 'America/Sao_Paulo')
    
    # Horário silencioso (padrão: 23h às 7h)
    SILENT_START_HOUR: int = 23
    SILENT_END_HOUR: int = 7
    
    # Formatação
    BRL_FORMAT: str = 'R$ {:,.2f}'
    USD_FORMAT: str = '${:,.2f}'
    
    # Limites de alertas
    RSI_OVERSOLD: float = 30
    RSI_OVERBOUGHT: float = 70
    LIQUIDATION_THRESHOLD: float = 10_000_000  # $10M
    
    # Horários dos resumos diários
    MORNING_SUMMARY_HOUR: int = 8
    EVENING_SUMMARY_HOUR: int = 20
    DAILY_CLOSE_HOUR: int = 23
    DAILY_CLOSE_MINUTE: int = 59
    
    # Ativa/desativa resumos automáticos
    ENABLE_DAILY_SUMMARIES: bool = True
    ENABLE_MORNING_SUMMARY: bool = True
    ENABLE_EVENING_SUMMARY: bool = True
    ENABLE_DAILY_CLOSE: bool = True
    
    def __post_init__(self):
        """Valida configurações essenciais"""
        if not self.BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN não configurado!")
        
        # Cria diretórios necessários
        Path('data').mkdir(exist_ok=True)
        Path('logs').mkdir(exist_ok=True)

# Instância global de configuração
config = Config()