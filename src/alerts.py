"""
Engine de alertas e notificações
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from telegram import Bot
from telegram.constants import ParseMode
from src.config import config
from src.database import Database
from src.market import MarketDataCollector
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

class AlertEngine:
    """Motor de alertas e notificações"""
    
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.market = MarketDataCollector(db)
        self.running = False
        self.check_task = None
        self.scheduler = AsyncIOScheduler(timezone='America/Sao_Paulo')
        
    async def start(self):
        """Inicia o engine de alertas"""
        if self.running:
            return
            
        self.running = True
        self.check_task = asyncio.create_task(self._alert_loop())
        
        # Configura resumos diários
        self._setup_daily_summaries()
        self.scheduler.start()
        
        logger.info("Alert Engine iniciado com resumos diários")
        
    async def stop(self):
        """Para o engine de alertas"""
        self.running = False
        if self.check_task:
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                pass
        
        if self.scheduler.running:
            self.scheduler.shutdown()
            
        logger.info("Alert Engine parado")
        
    async def _alert_loop(self):
        """Loop principal de verificação de alertas"""
        while self.running:
            try:
                await self._check_all_alerts()
                await asyncio.sleep(config.CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Erro no loop de alertas: {e}")
                await asyncio.sleep(60)
    
    async def _check_all_alerts(self):
        """Verifica todos os alertas ativos"""
        try:
            # Obtém dados atuais do mercado
            async with self.market as collector:
                market_data = await collector.get_market_summary()
            
            if not market_data:
                return
            
            # Obtém todos os alertas ativos
            alerts = await self.db.get_active_alerts()
            
            for alert in alerts:
                await self._process_alert(alert, market_data)
                
            # Verifica condições especiais (breakeven, RSI, etc.)
            await self._check_special_conditions(market_data)
            
        except Exception as e:
            logger.error(f"Erro ao verificar alertas: {e}")
    
    async def _process_alert(self, alert: Dict[str, Any], market_data: Dict[str, Any]):
        """Processa um alerta individual"""
        try:
            alert_type = alert['type']
            alert_value = alert['value']
            currency = alert.get('currency', 'USD')
            comparison = alert.get('comparison', 'above')
            
            current_price = market_data['price']['usd' if currency == 'USD' else 'brl']
            
            # Verifica se o alerta deve ser disparado
            should_trigger = False
            
            if alert_type == 'price':
                if comparison == 'above' and current_price >= alert_value:
                    should_trigger = True
                elif comparison == 'below' and current_price <= alert_value:
                    should_trigger = True
            
            elif alert_type == 'change':
                change_24h = market_data['price']['change_24h']
                if abs(change_24h) >= alert_value:
                    should_trigger = True
            
            if should_trigger:
                await self._send_alert(alert, market_data)
                
        except Exception as e:
            logger.error(f"Erro ao processar alerta {alert['id']}: {e}")
    
    async def _send_alert(self, alert: Dict[str, Any], market_data: Dict[str, Any]):
        """Envia notificação de alerta"""
        try:
            # Verifica horário silencioso
            if await self._is_silent_hours(alert['chat_id']):
                logger.info(f"Alerta {alert['id']} adiado - horário silencioso")
                return
            
            # Verifica retry count
            retry_count = alert.get('retry_count', 0)
            if retry_count >= config.MAX_ALERT_RETRIES:
                last_retry = alert.get('last_retry_at')
                if last_retry:
                    last_retry_time = datetime.fromisoformat(last_retry)
                    if datetime.now() - last_retry_time < timedelta(seconds=config.ALERT_RETRY_INTERVAL_LONG):
                        return
            
            # Formata mensagem
            message = self._format_alert_message(alert, market_data, retry_count)
            
            # Envia mensagem
            await self.bot.send_message(
                chat_id=alert['chat_id'],
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Atualiza banco de dados
            await self.db.update_alert_retry(alert['id'])
            await self.db.add_alert_history(
                alert_id=alert['id'],
                chat_id=alert['chat_id'],
                price_usd=market_data['price']['usd'],
                price_brl=market_data['price']['brl'],
                variation_24h=market_data['price']['change_24h'],
                volume_24h=market_data['price']['volume_24h'],
                message=message
            )
            
            logger.info(f"Alerta {alert['id']} enviado - tentativa {retry_count + 1}")
            
        except Exception as e:
            logger.error(f"Erro ao enviar alerta {alert['id']}: {e}")
    
    def _format_alert_message(self, alert: Dict[str, Any], 
                             market_data: Dict[str, Any], 
                             retry_count: int) -> str:
        """Formata mensagem de alerta"""
        price_usd = market_data['price']['usd']
        price_brl = market_data['price']['brl']
        change_24h = market_data['price']['change_24h']
        volume_24h = market_data['price']['volume_24h']
        
        # Emoji baseado na variação
        emoji = "🚀" if change_24h > 0 else "📉"
        
        message = f"""
🚨 *ALERTA BITCOIN #{alert['id']}*

{emoji} BTC atingiu {config.USD_FORMAT.format(price_usd)}
💵 {config.BRL_FORMAT.format(price_brl)}

📊 *Variação 24h:* {change_24h:+.2f}%
📈 *Volume 24h:* ${volume_24h/1e9:.2f}B

⏰ *Alerta criado:* {alert['created_at'][:16]}
📍 *Tentativa:* {retry_count + 1} de {config.MAX_ALERT_RETRIES}

Responda com `/ack {alert['id']}` quando ação tomada
        """.strip()
        
        return message
    
    async def _check_special_conditions(self, market_data: Dict[str, Any]):
        """Verifica condições especiais de alerta"""
        try:
            # Verifica proximidade ao breakeven
            async with self.market as collector:
                price_usd = market_data['price']['usd']
                is_near, diff = collector.check_breakeven_proximity(price_usd)
                
                if is_near:
                    await self._send_breakeven_alert(price_usd, diff, market_data)
            
            # Verifica RSI extremo
            rsi = market_data.get('rsi', 50)
            if rsi <= config.RSI_OVERSOLD or rsi >= config.RSI_OVERBOUGHT:
                await self._send_rsi_alert(rsi, market_data)
            
            # Verifica grandes liquidações
            liquidations = market_data.get('liquidations', {})
            if liquidations.get('total_24h', 0) >= config.LIQUIDATION_THRESHOLD:
                await self._send_liquidation_alert(liquidations, market_data)
                
        except Exception as e:
            logger.error(f"Erro ao verificar condições especiais: {e}")
    
    async def _send_breakeven_alert(self, price: float, diff: float, 
                                   market_data: Dict[str, Any]):
        """Envia alerta de proximidade ao breakeven"""
        # Verifica se já foi enviado recentemente
        cached = await self.db.get_cache('breakeven_alert_sent')
        if cached:
            return
        
        message = f"""
⚠️ *ALERTA BREAKEVEN*

💰 Preço atual: {config.USD_FORMAT.format(price)}
📍 Seu breakeven: {config.USD_FORMAT.format(config.USER_AVG_PRICE)}
📊 Diferença: {diff:+.2f}%

🎯 Posição: {config.USER_BTC_POSITION:.8f} BTC
💵 Valor atual: {config.USD_FORMAT.format(price * config.USER_BTC_POSITION)}

_Preço próximo ao seu ponto de equilíbrio!_
        """.strip()
        
        await self.bot.send_message(
            chat_id=config.USER_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Marca como enviado (cache por 1 hora)
        await self.db.set_cache('breakeven_alert_sent', '1')
    
    async def _send_rsi_alert(self, rsi: float, market_data: Dict[str, Any]):
        """Envia alerta de RSI extremo"""
        cached = await self.db.get_cache(f'rsi_alert_{int(rsi)}')
        if cached:
            return
        
        condition = "OVERSOLD" if rsi <= config.RSI_OVERSOLD else "OVERBOUGHT"
        emoji = "🔥" if condition == "OVERSOLD" else "❄️"
        
        message = f"""
{emoji} *RSI ALERTA - {condition}*

📊 RSI (14): {rsi:.2f}
💰 Preço: {config.USD_FORMAT.format(market_data['price']['usd'])}

⚠️ _Possível reversão de tendência_
        """.strip()
        
        await self.bot.send_message(
            chat_id=config.USER_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        await self.db.set_cache(f'rsi_alert_{int(rsi)}', '1')
    
    async def _send_liquidation_alert(self, liquidations: Dict[str, float], 
                                     market_data: Dict[str, Any]):
        """Envia alerta de grandes liquidações"""
        cached = await self.db.get_cache('liquidation_alert')
        if cached:
            return
        
        total = liquidations['total_24h'] / 1e6  # Em milhões
        longs_pct = (liquidations['longs'] / liquidations['total_24h']) * 100
        
        message = f"""
💥 *GRANDES LIQUIDAÇÕES DETECTADAS*

💸 Total 24h: ${total:.1f}M
📊 Distribuição: {longs_pct:.0f}% longs / {100-longs_pct:.0f}% shorts
💰 Preço atual: {config.USD_FORMAT.format(market_data['price']['usd'])}

⚠️ _Alta volatilidade esperada_
        """.strip()
        
        await self.bot.send_message(
            chat_id=config.USER_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        await self.db.set_cache('liquidation_alert', '1')
    
    async def _is_silent_hours(self, chat_id: str) -> bool:
        """Verifica se está em horário silencioso"""
        try:
            user_config = await self.db.get_user_config(chat_id)
            
            tz = pytz.timezone(user_config['timezone'])
            now = datetime.now(tz)
            current_hour = now.hour
            
            silent_start = user_config['silent_start']
            silent_end = user_config['silent_end']
            
            # Lida com horários que cruzam meia-noite
            if silent_start > silent_end:
                return current_hour >= silent_start or current_hour < silent_end
            else:
                return silent_start <= current_hour < silent_end
                
        except Exception as e:
            logger.error(f"Erro ao verificar horário silencioso: {e}")
            return False
    
    def _setup_daily_summaries(self):
        """Configura envio de resumos diários"""
        if not config.ENABLE_DAILY_SUMMARIES:
            logger.info("Resumos diários desabilitados")
            return
            
        # Resumo da manhã - 8:00
        if config.ENABLE_MORNING_SUMMARY:
            self.scheduler.add_job(
                self._send_morning_summary,
                'cron',
                hour=config.MORNING_SUMMARY_HOUR,
                minute=0,
                id='morning_summary'
            )
        
        # Resumo da noite - 20:00
        if config.ENABLE_EVENING_SUMMARY:
            self.scheduler.add_job(
                self._send_evening_summary,
                'cron',
                hour=config.EVENING_SUMMARY_HOUR,
                minute=0,
                id='evening_summary'
            )
        
        # Resumo de fechamento - 23:59
        if config.ENABLE_DAILY_CLOSE:
            self.scheduler.add_job(
                self._send_daily_close_summary,
                'cron',
                hour=config.DAILY_CLOSE_HOUR,
                minute=config.DAILY_CLOSE_MINUTE,
                id='daily_close'
            )
        
        logger.info("Resumos diários configurados: 8:00, 20:00 e 23:59")
    
    async def _send_morning_summary(self):
        """Envia resumo matinal às 8:00"""
        try:
            async with self.market as collector:
                market_data = await collector.get_market_summary()
                price_data = market_data['price']
                fear_greed = market_data['fear_greed']
                rsi = market_data['rsi']
                
                # Calcula P&L
                user_value = config.USER_BTC_POSITION * price_data['usd']
                user_cost = config.USER_BTC_POSITION * config.USER_AVG_PRICE
                pnl = user_value - user_cost
                pnl_percent = (pnl / user_cost) * 100
                
                # Determina emoji do dia
                if price_data['change_24h'] > 5:
                    day_emoji = "🚀"
                    day_mood = "BULLISH"
                elif price_data['change_24h'] > 0:
                    day_emoji = "📈"
                    day_mood = "Positivo"
                elif price_data['change_24h'] > -5:
                    day_emoji = "📉"
                    day_mood = "Negativo"
                else:
                    day_emoji = "🔻"
                    day_mood = "BEARISH"
                
                message = f"""
☀️ *BOM DIA! RESUMO DO BITCOIN*
{datetime.now().strftime('%d/%m/%Y - %H:%M')}

{day_emoji} *Mercado {day_mood}*

💰 *PREÇO ATUAL:*
• USD: {config.USD_FORMAT.format(price_data['usd'])}
• BRL: {config.BRL_FORMAT.format(price_data['brl'])}
• 24h: {price_data['change_24h']:+.2f}%

📊 *INDICADORES:*
• Fear & Greed: {fear_greed['value']} ({fear_greed['classification']})
• RSI: {rsi:.1f}
• Volume 24h: ${price_data['volume_24h']/1e9:.1f}B

💼 *SUA POSIÇÃO:*
• Valor: {config.USD_FORMAT.format(user_value)}
• P&L: {config.USD_FORMAT.format(pnl)} ({pnl_percent:+.1f}%)
• Dist. Breakeven: {((price_data['usd']/config.USER_AVG_PRICE)-1)*100:+.1f}%

📱 Comandos: /price | /market | /alert_add

Tenha um ótimo dia de trading! 🎯
                """.strip()
                
                await self.bot.send_message(
                    chat_id=config.USER_CHAT_ID,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Erro ao enviar resumo matinal: {e}")
    
    async def _send_evening_summary(self):
        """Envia resumo noturno às 20:00"""
        try:
            async with self.market as collector:
                market_data = await collector.get_market_summary()
                price_data = market_data['price']
                
                # Busca dados do dia (simulado - ideal seria armazenar histórico)
                day_high = price_data['usd'] * 1.02  # Simulado
                day_low = price_data['usd'] * 0.98   # Simulado
                
                # Análise de tendência
                if price_data['change_24h'] > 0:
                    trend = "📈 Alta"
                    trend_detail = "Mercado em recuperação"
                else:
                    trend = "📉 Baixa"
                    trend_detail = "Mercado em correção"
                
                # Alertas ativos
                alerts = await self.db.get_active_alerts(config.USER_CHAT_ID)
                alerts_text = f"🔔 Alertas Ativos: {len(alerts)}"
                if alerts:
                    nearest_alert = min(alerts, key=lambda x: abs(x['value'] - price_data['usd']))
                    dist_percent = ((nearest_alert['value'] - price_data['usd']) / price_data['usd']) * 100
                    alerts_text += f"\nMais próximo: ${nearest_alert['value']:,.0f} ({dist_percent:+.1f}%)"
                
                message = f"""
🌙 *RESUMO NOTURNO BITCOIN*
{datetime.now().strftime('%d/%m/%Y - %H:%M')}

📊 *PERFORMANCE DO DIA:*
• Tendência: {trend}
• Máxima: ${day_high:,.2f}
• Mínima: ${day_low:,.2f}
• Atual: ${price_data['usd']:,.2f}

💡 *ANÁLISE:*
• {trend_detail}
• Volume: {'Alto' if price_data['volume_24h'] > 30e9 else 'Normal'}
• Volatilidade: {abs(price_data['change_24h']):.1f}%

{alerts_text}

🎯 *Preços-Chave:*
• Resistência: ${price_data['usd']*1.05:,.0f}
• Suporte: ${price_data['usd']*0.95:,.0f}
• Seu Breakeven: ${config.USER_AVG_PRICE:,.0f}

_Boa noite e bons trades amanhã!_ 🌟
                """.strip()
                
                await self.bot.send_message(
                    chat_id=config.USER_CHAT_ID,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Erro ao enviar resumo noturno: {e}")
    
    async def _send_daily_close_summary(self):
        """Envia resumo de fechamento às 23:59"""
        try:
            async with self.market as collector:
                market_data = await collector.get_market_summary()
                price_data = market_data['price']
                fear_greed = market_data['fear_greed']
                
                # Determina sentimento do fechamento
                if fear_greed['value'] >= 75:
                    sentiment = "🔥 Ganância Extrema - Cuidado!"
                elif fear_greed['value'] >= 55:
                    sentiment = "😊 Ganância - Mercado Otimista"
                elif fear_greed['value'] >= 45:
                    sentiment = "😐 Neutro - Indecisão"
                elif fear_greed['value'] >= 25:
                    sentiment = "😟 Medo - Oportunidade?"
                else:
                    sentiment = "😱 Medo Extremo - Possível Fundo"
                
                message = f"""
📊 *FECHAMENTO DIÁRIO*
{datetime.now().strftime('%d/%m/%Y')}

💰 *FECHOU EM:*
• ${price_data['usd']:,.2f}
• R$ {price_data['brl']:,.2f}
• Variação: {price_data['change_24h']:+.2f}%

📈 *SENTIMENTO:*
{sentiment}
Fear & Greed: {fear_greed['value']}/100

💡 *RESUMO:*
Bitcoin {'subiu' if price_data['change_24h'] > 0 else 'caiu'} {abs(price_data['change_24h']):.2f}% hoje.
Volume: ${price_data['volume_24h']/1e9:.1f}B

_Fechamento registrado às 23:59_
                """.strip()
                
                await self.bot.send_message(
                    chat_id=config.USER_CHAT_ID,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Erro ao enviar fechamento diário: {e}")