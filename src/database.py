"""
Gerenciamento de banco de dados SQLite
"""
import aiosqlite
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging
from pathlib import Path
from src.config import config

logger = logging.getLogger(__name__)

class Database:
    """Gerenciador de banco de dados assíncrono"""
    
    def __init__(self, db_path: str = config.DATABASE_PATH):
        self.db_path = db_path
        self.conn: Optional[aiosqlite.Connection] = None
        
    async def connect(self):
        """Conecta ao banco de dados"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.create_tables()
        logger.info(f"Conectado ao banco de dados: {self.db_path}")
        
    async def close(self):
        """Fecha conexão com o banco"""
        if self.conn:
            await self.conn.close()
            logger.info("Conexão com banco de dados fechada")
            
    async def create_tables(self):
        """Cria tabelas necessárias"""
        async with self.conn.cursor() as cursor:
            # Tabela de alertas
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    value REAL NOT NULL,
                    currency TEXT DEFAULT 'USD',
                    comparison TEXT DEFAULT 'above',
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    triggered_at TIMESTAMP,
                    acked_at TIMESTAMP,
                    retry_count INTEGER DEFAULT 0,
                    last_retry_at TIMESTAMP,
                    notes TEXT
                )
            ''')
            
            # Tabela de configuração do usuário
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_config (
                    chat_id TEXT PRIMARY KEY,
                    timezone TEXT DEFAULT 'America/Sao_Paulo',
                    silent_start INTEGER DEFAULT 23,
                    silent_end INTEGER DEFAULT 7,
                    language TEXT DEFAULT 'pt_BR',
                    notifications_enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabela de histórico de alertas
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER,
                    chat_id TEXT,
                    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    price_usd REAL,
                    price_brl REAL,
                    variation_24h REAL,
                    volume_24h REAL,
                    acked BOOLEAN DEFAULT 0,
                    acked_at TIMESTAMP,
                    message TEXT,
                    FOREIGN KEY (alert_id) REFERENCES alerts (id)
                )
            ''')
            
            # Tabela de cache de mercado
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await self.conn.commit()
            logger.info("Tabelas criadas/verificadas com sucesso")
    
    # === Métodos de Alertas ===
    
    async def add_alert(self, chat_id: str, alert_type: str, value: float, 
                        currency: str = 'USD', comparison: str = 'above') -> int:
        """Adiciona novo alerta"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                INSERT INTO alerts (chat_id, type, value, currency, comparison)
                VALUES (?, ?, ?, ?, ?)
            ''', (chat_id, alert_type, value, currency, comparison))
            await self.conn.commit()
            alert_id = cursor.lastrowid
            logger.info(f"Alerta #{alert_id} criado: {alert_type} {value} {currency}")
            return alert_id
    
    async def get_active_alerts(self, chat_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retorna alertas ativos"""
        query = '''
            SELECT * FROM alerts 
            WHERE status = 'active'
        '''
        params = []
        
        if chat_id:
            query += ' AND chat_id = ?'
            params.append(chat_id)
            
        async with self.conn.cursor() as cursor:
            await cursor.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def update_alert_retry(self, alert_id: int):
        """Atualiza contador de retry do alerta"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                UPDATE alerts 
                SET retry_count = retry_count + 1,
                    last_retry_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (alert_id,))
            await self.conn.commit()
    
    async def acknowledge_alert(self, alert_id: int, notes: str = None) -> bool:
        """Marca alerta como confirmado"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                UPDATE alerts 
                SET status = 'acknowledged',
                    acked_at = CURRENT_TIMESTAMP,
                    notes = ?
                WHERE id = ? AND status = 'active'
            ''', (notes, alert_id))
            await self.conn.commit()
            success = cursor.rowcount > 0
            if success:
                logger.info(f"Alerta #{alert_id} confirmado")
            return success
    
    async def delete_alert(self, alert_id: int, chat_id: str) -> bool:
        """Deleta um alerta"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                DELETE FROM alerts 
                WHERE id = ? AND chat_id = ?
            ''', (alert_id, chat_id))
            await self.conn.commit()
            success = cursor.rowcount > 0
            if success:
                logger.info(f"Alerta #{alert_id} deletado")
            return success
    
    # === Métodos de Configuração ===
    
    async def get_user_config(self, chat_id: str) -> Dict[str, Any]:
        """Retorna configuração do usuário"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                SELECT * FROM user_config WHERE chat_id = ?
            ''', (chat_id,))
            row = await cursor.fetchone()
            
            if not row:
                # Cria configuração padrão
                await self.create_user_config(chat_id)
                return await self.get_user_config(chat_id)
            
            return dict(row)
    
    async def create_user_config(self, chat_id: str):
        """Cria configuração padrão para novo usuário"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                INSERT OR IGNORE INTO user_config (chat_id)
                VALUES (?)
            ''', (chat_id,))
            await self.conn.commit()
            logger.info(f"Configuração criada para chat_id: {chat_id}")
    
    async def update_user_config(self, chat_id: str, **kwargs):
        """Atualiza configuração do usuário"""
        valid_fields = ['timezone', 'silent_start', 'silent_end', 
                       'language', 'notifications_enabled']
        
        updates = []
        values = []
        for field, value in kwargs.items():
            if field in valid_fields:
                updates.append(f"{field} = ?")
                values.append(value)
        
        if not updates:
            return
        
        values.append(chat_id)
        query = f'''
            UPDATE user_config 
            SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = ?
        '''
        
        async with self.conn.cursor() as cursor:
            await cursor.execute(query, values)
            await self.conn.commit()
            logger.info(f"Configuração atualizada para {chat_id}: {kwargs}")
    
    # === Métodos de Histórico ===
    
    async def add_alert_history(self, alert_id: int, chat_id: str, 
                                price_usd: float, price_brl: float,
                                variation_24h: float, volume_24h: float,
                                message: str):
        """Adiciona entrada no histórico de alertas"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                INSERT INTO alert_history 
                (alert_id, chat_id, price_usd, price_brl, variation_24h, 
                 volume_24h, message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (alert_id, chat_id, price_usd, price_brl, 
                  variation_24h, volume_24h, message))
            await self.conn.commit()
    
    # === Métodos de Cache ===
    
    async def get_cache(self, key: str, ttl_minutes: int = 5) -> Optional[str]:
        """Retorna valor do cache"""
        async with self.conn.cursor() as cursor:
            await cursor.execute(f'''
                SELECT value FROM market_cache 
                WHERE key = ? AND 
                datetime(updated_at) > datetime('now', '-{ttl_minutes} minutes')
            ''', (key,))
            row = await cursor.fetchone()
            return row['value'] if row else None
    
    async def set_cache(self, key: str, value: str):
        """Define/atualiza valor no cache com timestamp atual"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                INSERT OR REPLACE INTO market_cache (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, value))
            await self.conn.commit()
    
    async def set_cache_with_ttl(self, key: str, value: str, ttl_seconds: int):
        """Compatibilidade: seta cache e TTL é aplicado via parâmetro do get_cache."""
        await self.set_cache(key, value)
