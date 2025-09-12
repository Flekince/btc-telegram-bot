FROM python:3.11-slim

# Define diretório de trabalho
WORKDIR /app

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements e instala dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código da aplicação
COPY src/ ./src/

# Cria diretórios necessários
RUN mkdir -p data logs

# Define variáveis de ambiente padrão
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Sao_Paulo

# Comando para rodar o bot
CMD ["python", "-m", "src.bot"]