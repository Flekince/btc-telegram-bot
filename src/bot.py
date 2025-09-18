"""
Bot principal do Telegram
"""
import asyncio
import logging
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from telegram.constants import ParseMode
from src.config import config
from src.database import Database
from src.market import MarketDataCollector
from src.alerts import AlertEngine
import re

logger = logging.getLogger(__name__)

class BTCTelegramBot:
    """Bot principal do Telegram para monitoramento de Bitcoin"""
    
    def __init__(self):
        self.app = Application.builder().token(config.BOT_TOKEN).build()
        self.db = Database()
        self.alert_engine = None
        self.setup_handlers()
        
    def setup_handlers(self):
        """Configura handlers do bot"""
        # Comandos principais
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("price", self.cmd_price))
        self.app.add_handler(CommandHandler("market", self.cmd_market))
        self.app.add_handler(CommandHandler("daily", self.cmd_daily))
        
        # Comandos de alertas
        self.app.add_handler(CommandHandler("alert_add", self.cmd_alert_add))
        self.app.add_handler(CommandHandler("alert_list", self.cmd_alert_list))
        self.app.add_handler(CommandHandler("alert_del", self.cmd_alert_del))
        self.app.add_handler(CommandHandler("ack", self.cmd_acknowledge))
        
        # Comandos de configuração
        self.app.add_handler(CommandHandler("config", self.cmd_config))
        
        # Handler para mensagens não reconhecidas
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start - Inicialização"""
        chat_id = str(update.effective_chat.id)
        
        # Cria configuração do usuário
        await self.db.create_user_config(chat_id)
        
        welcome_message = """
🚀 *Bem-vindo ao Bot de Monitoramento Bitcoin!*

Eu vou te ajudar a acompanhar o mercado de Bitcoin com alertas inteligentes e análises em tempo real.

📊 *Comandos principais:*
• `/price` - Preço atual do BTC
• `/market` - Análise completa do mercado
• `/alert_add [valor] [moeda]` - Criar alerta
• `/alert_list` - Ver seus alertas
• `/daily` - Configurar resumos diários
• `/help` - Ajuda detalhada

💡 *Sua posição atual:*
• BTC: {:.8f}
• Preço médio: ${:,.2f}
• Breakeven alerts: Ativado ✅

📅 *Resumos diários:* Ativados (8h, 20h, 23:59)

Vamos começar? Digite `/price` para ver o preço atual!
        """.format(config.USER_BTC_POSITION, config.USER_AVG_PRICE).strip()
        
        await update.message.reply_text(
            welcome_message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"Novo usuário iniciado: {chat_id}")
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /help - Ajuda detalhada"""
        help_text = """
📚 *AJUDA COMPLETA - Bot Bitcoin*

*🎯 Comandos de Preço:*
• `/price` - Preço atual em USD e BRL
• `/market` - Análise completa do mercado

*🔔 Comandos de Alertas:*
• `/alert_add [valor] [USD/BRL]` - Criar alerta
  Ex: `/alert_add 110000 USD`
• `/alert_list` - Listar alertas ativos
• `/alert_del [id]` - Deletar alerta
• `/ack [id]` - Confirmar alerta (para reenvios)

*📅 Resumos Diários:*
• `/daily` - Ver configuração de resumos
• `/daily on` - Ativar resumos
• `/daily off` - Desativar resumos
• `/daily test` - Testar resumos

*⚙️ Configuração:*
• `/config` - Ver/editar configurações
• `/config silent 22 8` - Horário silencioso (22h-8h)
• `/config timezone America/Sao_Paulo`

*📊 Indicadores Monitorados:*
• RSI (alerta quando < 30 ou > 70)
• Fear & Greed Index
• Funding Rate
• Liquidações > $10M
• Proximidade ao seu breakeven

*💡 Dicas:*
• Alertas reenviam até confirmação com `/ack`
• Horário silencioso pausa notificações
• Alertas de breakeven são automáticos

Dúvidas? Digite um comando para começar!
        """.strip()
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def cmd_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /price - Preço atual"""
        try:
            async with MarketDataCollector(self.db) as collector:
                price_data = await collector.get_btc_price()
                is_near, diff = collector.check_breakeven_proximity(price_data['usd'])
            
            # Emoji baseado na variação
            emoji = "🟢" if price_data['change_24h'] > 0 else "🔴"
            breakeven_emoji = "⚠️" if is_near else ""
            
            # Calcula P&L do usuário
            user_value = config.USER_BTC_POSITION * price_data['usd']
            user_cost = config.USER_BTC_POSITION * config.USER_AVG_PRICE
            pnl = user_value - user_cost
            pnl_percent = (pnl / user_cost) * 100
            
            message = f"""
{emoji} *BITCOIN - PREÇO ATUAL*

💵 *USD:* {config.USD_FORMAT.format(price_data['usd'])}
💵 *BRL:* {config.BRL_FORMAT.format(price_data['brl'])}

📊 *Variação 24h:* {price_data['change_24h']:+.2f}%
📈 *Volume 24h:* ${price_data['volume_24h']/1e9:.2f}B

{breakeven_emoji} *Sua Posição:*
• Quantidade: {config.USER_BTC_POSITION:.8f} BTC
• Valor atual: {config.USD_FORMAT.format(user_value)}
• P&L: {config.USD_FORMAT.format(pnl)} ({pnl_percent:+.2f}%)
• Breakeven: {config.USD_FORMAT.format(config.USER_AVG_PRICE)}

_Atualizado: {datetime.now().strftime('%d/%m %H:%M')}_
            """.strip()
            
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Erro no comando price: {e}")
            await update.message.reply_text(
                "❌ Erro ao obter preço. Tente novamente em alguns segundos."
            )
    
    async def cmd_market(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /market - Resumo do mercado"""
        try:
            await update.message.reply_text("📊 Analisando mercado... aguarde...")
            
            async with MarketDataCollector(self.db) as collector:
                market_data = await collector.get_market_summary()
            
            price = market_data['price']
            fear_greed = market_data['fear_greed']
            dominance = market_data['dominance']
            funding_rate = market_data['funding_rate']
            liquidations = market_data['liquidations']
            rsi = market_data['rsi']
            
            # Determina sentimento
            if fear_greed['value'] >= 75:
                sentiment = "🔥 Extreme Greed"
            elif fear_greed['value'] >= 55:
                sentiment = "😊 Greed"
            elif fear_greed['value'] >= 45:
                sentiment = "😐 Neutral"
            elif fear_greed['value'] >= 25:
                sentiment = "😟 Fear"
            else:
                sentiment = "😱 Extreme Fear"
            
            # RSI status
            if rsi <= 30:
                rsi_status = "🔥 OVERSOLD"
            elif rsi >= 70:
                rsi_status = "❄️ OVERBOUGHT"
            else:
                rsi_status = "✅ Normal"
            
            message = f"""
📊 *BITCOIN MARKET OVERVIEW*

💰 *Preço:*
• USD: {config.USD_FORMAT.format(price['usd'])}
• BRL: {config.BRL_FORMAT.format(price['brl'])}
• 24h: {price['change_24h']:+.2f}%

📈 *Indicadores:*
• RSI (14): {rsi:.1f} - {rsi_status}
• Fear & Greed: {fear_greed['value']} - {sentiment}
• Dominância: {dominance:.1f}%

💱 *Derivativos:*
• Funding Rate: {funding_rate:.4f}%
• Liquidações 24h: ${liquidations['total_24h']/1e6:.1f}M

📊 *Volume & Cap:*
• Volume 24h: ${price['volume_24h']/1e9:.2f}B
• Market Cap: ${price.get('market_cap', 0)/1e12:.2f}T

_Atualizado: {datetime.now().strftime('%d/%m %H:%M')}_
            """.strip()
            
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Erro no comando market: {e}")
            await update.message.reply_text(
                "❌ Erro ao analisar mercado. Tente novamente."
            )
    
    async def cmd_daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /daily - Ativa/desativa resumos diários"""
        try:
            if not context.args:
                status = "✅ Ativado" if config.ENABLE_DAILY_SUMMARIES else "❌ Desativado"
                message = f"""
📅 *RESUMOS DIÁRIOS*

Status atual: {status}

*Horários programados:*
• 08:00 - Resumo Matinal
• 20:00 - Resumo Noturno  
• 23:59 - Fechamento do Dia

*Comandos:*
• `/daily on` - Ativar resumos
• `/daily off` - Desativar resumos
• `/daily morning` - Resumo matinal agora
• `/daily evening` - Resumo noturno agora
• `/daily close` - Fechamento agora
• `/daily test` - Testar todos
                """
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
                return
            
            action = context.args[0].lower()
            
            if action == 'on':
                config.ENABLE_DAILY_SUMMARIES = True
                await update.message.reply_text("✅ Resumos diários ATIVADOS!")
                
            elif action == 'off':
                config.ENABLE_DAILY_SUMMARIES = False
                await update.message.reply_text("❌ Resumos diários DESATIVADOS!")
                
            elif action == 'morning':
                await update.message.reply_text("☀️ Enviando resumo matinal...")
                await self.alert_engine._send_morning_summary()
                
            elif action == 'evening':
                await update.message.reply_text("🌙 Enviando resumo noturno...")
                await self.alert_engine._send_evening_summary()
                
            elif action == 'close':
                await update.message.reply_text("📊 Enviando fechamento diário...")
                await self.alert_engine._send_daily_close_summary()
                
            elif action == 'test':
                await update.message.reply_text("📤 Enviando todos os resumos de teste...")
                await self.alert_engine._send_morning_summary()
                await asyncio.sleep(2)
                await self.alert_engine._send_evening_summary()
                await asyncio.sleep(2)
                await self.alert_engine._send_daily_close_summary()
                
        except Exception as e:
            logger.error(f"Erro no comando daily: {e}")
            await update.message.reply_text("❌ Erro ao configurar resumos diários")
    
    async def cmd_alert_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /alert_add - Adicionar alerta"""
        try:
            chat_id = str(update.effective_chat.id)
            
            if len(context.args) < 2:
                await update.message.reply_text(
                    "❌ Uso: `/alert_add [valor] [USD/BRL]`\n"
                    "Ex: `/alert_add 110000 USD`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            value = float(context.args[0])
            currency = context.args[1].upper()
            
            if currency not in ['USD', 'BRL']:
                await update.message.reply_text(
                    "❌ Moeda deve ser USD ou BRL"
                )
                return
            
            # Determina se é above ou below baseado no preço atual
            async with MarketDataCollector(self.db) as collector:
                price_data = await collector.get_btc_price()
                current_price = price_data['usd' if currency == 'USD' else 'brl']
                comparison = 'above' if value > current_price else 'below'
            
            # Adiciona alerta
            alert_id = await self.db.add_alert(
                chat_id=chat_id,
                alert_type='price',
                value=value,
                currency=currency,
                comparison=comparison
            )
            
            symbol = "$" if currency == "USD" else "R$"
            message = f"""
✅ *Alerta #{alert_id} criado!*

🎯 Alertar quando BTC {comparison} {symbol}{value:,.2f}
💰 Preço atual: {symbol}{current_price:,.2f}
📊 Diferença: {abs(value-current_price)/current_price*100:.2f}%

Use `/alert_list` para ver todos os alertas.
            """.strip()
            
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            
        except ValueError:
            await update.message.reply_text(
                "❌ Valor inválido. Use números.\nEx: `/alert_add 110000 USD`",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Erro ao adicionar alerta: {e}")
            await update.message.reply_text("❌ Erro ao criar alerta.")
    
    # CONTINUA NA PARTE 2...
    # CONTINUAÇÃO DO ARQUIVO bot.py (adicione após cmd_alert_add)
    
    async def cmd_alert_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /alert_list - Listar alertas"""
        try:
            chat_id = str(update.effective_chat.id)
            alerts = await self.db.get_active_alerts(chat_id)
            
            if not alerts:
                await update.message.reply_text(
                    "📭 Você não tem alertas ativos.\n"
                    "Use `/alert_add [valor] [moeda]` para criar.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            message = "🔔 <b>SEUS ALERTAS ATIVOS</b>\n\n"
            
            for alert in alerts:
                symbol = "$" if alert['currency'] == "USD" else "R$"
                status_emoji = "🟢" if alert['retry_count'] == 0 else "🔄"
                
                message += f"""
{status_emoji} <b>Alerta #{alert['id']}</b>
• Tipo: {alert['type'].title()}
• Valor: {symbol}{alert['value']:,.2f}
• Condição: {alert['comparison']}
• Tentativas: {alert['retry_count']}/{config.MAX_ALERT_RETRIES}
• Criado: {alert['created_at'][:16]}

"""
            
            message += "Use <code>/alert_del [id]</code> para deletar"
            
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Erro ao listar alertas: {e}")
            await update.message.reply_text("❌ Erro ao listar alertas.")
    
    async def cmd_alert_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /alert_del - Deletar alerta"""
        try:
            chat_id = str(update.effective_chat.id)
            
            if not context.args:
                await update.message.reply_text(
                    "❌ Uso: `/alert_del [id]`\nEx: `/alert_del 5`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            alert_id = int(context.args[0])
            success = await self.db.delete_alert(alert_id, chat_id)
            
            if success:
                await update.message.reply_text(
                    f"✅ Alerta #{alert_id} deletado com sucesso!"
                )
            else:
                await update.message.reply_text(
                    f"❌ Alerta #{alert_id} não encontrado ou não é seu."
                )
                
        except ValueError:
            await update.message.reply_text("❌ ID inválido. Use números.")
        except Exception as e:
            logger.error(f"Erro ao deletar alerta: {e}")
            await update.message.reply_text("❌ Erro ao deletar alerta.")
    
    async def cmd_acknowledge(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /ack - Confirmar alerta"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "❌ Uso: `/ack [id] [comentário opcional]`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            alert_id = int(context.args[0])
            notes = ' '.join(context.args[1:]) if len(context.args) > 1 else None
            
            success = await self.db.acknowledge_alert(alert_id, notes)
            
            if success:
                message = f"✅ Alerta #{alert_id} confirmado!"
                if notes:
                    message += f"\n📝 Nota: _{notes}_"
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(
                    f"❌ Alerta #{alert_id} não encontrado ou já confirmado."
                )
                
        except ValueError:
            await update.message.reply_text("❌ ID inválido.")
        except Exception as e:
            logger.error(f"Erro ao confirmar alerta: {e}")
            await update.message.reply_text("❌ Erro ao confirmar alerta.")
    
    async def cmd_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /config - Configurações"""
        try:
            chat_id = str(update.effective_chat.id)
            
            if not context.args:
                # Mostra configurações atuais
                config_data = await self.db.get_user_config(chat_id)
                
                message = f"""
⚙️ *SUAS CONFIGURAÇÕES*

🕐 *Horário Silencioso:*
• {config_data['silent_start']}h às {config_data['silent_end']}h
• Status: {'Ativado ✅' if config_data['notifications_enabled'] else 'Desativado ❌'}

🌍 *Timezone:* {config_data['timezone']}
🗣 *Idioma:* {config_data['language']}

*Comandos de configuração:*
• `/config silent [início] [fim]` - Horário silencioso
• `/config timezone [timezone]` - Fuso horário
• `/config notifications [on/off]` - Ativar/desativar

Ex: `/config silent 22 7` (silencioso das 22h às 7h)
                """.strip()
                
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
                return
            
            # Processa comandos de configuração
            setting = context.args[0].lower()
            
            if setting == 'silent' and len(context.args) >= 3:
                start_hour = int(context.args[1])
                end_hour = int(context.args[2])
                
                await self.db.update_user_config(
                    chat_id,
                    silent_start=start_hour,
                    silent_end=end_hour
                )
                
                await update.message.reply_text(
                    f"✅ Horário silencioso configurado: {start_hour}h às {end_hour}h"
                )
                
            elif setting == 'timezone' and len(context.args) >= 2:
                timezone = context.args[1]
                await self.db.update_user_config(chat_id, timezone=timezone)
                await update.message.reply_text(f"✅ Timezone alterado para: {timezone}")
                
            elif setting == 'notifications' and len(context.args) >= 2:
                enabled = context.args[1].lower() == 'on'
                await self.db.update_user_config(
                    chat_id,
                    notifications_enabled=enabled
                )
                status = "ativadas" if enabled else "desativadas"
                await update.message.reply_text(f"✅ Notificações {status}!")
                
            else:
                await update.message.reply_text(
                    "❌ Comando inválido. Use `/config` para ver opções.",
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Erro no comando config: {e}")
            await update.message.reply_text("❌ Erro ao atualizar configurações.")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para mensagens não reconhecidas"""
        text = update.message.text.lower()
        
        # Respostas inteligentes baseadas em palavras-chave
        if any(word in text for word in ['preço', 'price', 'valor', 'quanto', 'cotação']):
            await self.cmd_price(update, context)
        elif any(word in text for word in ['mercado', 'market', 'análise']):
            await self.cmd_market(update, context)
        elif any(word in text for word in ['alerta', 'alert', 'aviso']):
            await update.message.reply_text(
                "💡 Para gerenciar alertas:\n"
                "• `/alert_add [valor] [moeda]` - Criar\n"
                "• `/alert_list` - Listar\n"
                "• `/alert_del [id]` - Deletar",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "🤔 Não entendi. Digite `/help` para ver os comandos disponíveis.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def run(self):
        """Inicia o bot"""
        try:
            # Conecta ao banco de dados
            await self.db.connect()
            
            # Inicia o alert engine
            self.alert_engine = AlertEngine(self.app.bot, self.db)
            await self.alert_engine.start()
            
            # Define comandos no menu do Telegram
            await self.app.bot.set_my_commands([
                BotCommand("start", "Iniciar bot"),
                BotCommand("price", "Preço atual do Bitcoin"),
                BotCommand("market", "Análise completa do mercado"),
                BotCommand("daily", "Configurar resumos diários"),
                BotCommand("alert_add", "Criar novo alerta"),
                BotCommand("alert_list", "Listar alertas ativos"),
                BotCommand("alert_del", "Deletar alerta"),
                BotCommand("ack", "Confirmar alerta"),
                BotCommand("config", "Configurações"),
                BotCommand("help", "Ajuda detalhada")
            ])
            
            logger.info("Bot iniciado com sucesso!")
            print("🚀 Bot Bitcoin rodando! Pressione Ctrl+C para parar.")
            
            # Inicia o bot
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling()
            
            # Mantém rodando
            while True:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Bot parado pelo usuário")
        except Exception as e:
            logger.error(f"Erro crítico: {e}")
        finally:
            if self.alert_engine:
                await self.alert_engine.stop()
            await self.db.close()
            await self.app.stop()

# Função principal
async def main():
    bot = BTCTelegramBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())