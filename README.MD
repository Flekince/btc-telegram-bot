# Bitcoin Telegram Bot 🚀

Bot completo para monitoramento e alertas de Bitcoin no Telegram, com sistema de confirmação de ações e análise de mercado em tempo real.

## ✨ Funcionalidades

### 📊 Monitoramento de Preço
- Preço em tempo real (USD e BRL)
- Alertas personalizados por preço-alvo
- Notificações de proximidade ao breakeven
- Sistema de confirmação de alertas

### 📈 Análise de Mercado
- Fear & Greed Index
- RSI (alertas em oversold/overbought)
- Volume e liquidações
- Dominância do Bitcoin
- Funding rate

### 🔔 Sistema de Alertas Inteligente
- Múltiplos alertas simultâneos
- Reenvio automático até confirmação
- Horário silencioso configurável
- Alertas especiais para sua posição

## 🚀 Instalação Rápida

### Pré-requisitos
- Python 3.11+
- Token do bot Telegram (obtenha com @BotFather)
- Docker (opcional)

### Instalação Local

1. Clone o repositório:
```bash
git clone https://github.com/Flekince/btc-telegram-bot.git
cd btc-telegram-bot

### 2. Configure as variáveis de ambiente:
```bash
# Copie o arquivo de exemplo
cp .env.example .env

# Edite o arquivo .env com seus dados reais
notepad .env  # Windows