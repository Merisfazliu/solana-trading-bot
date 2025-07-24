import json
import logging
import os
import requests
import pandas as pd
from sklearn.preprocessing import StandardScaler
from solders.keypair import Keypair
from solders.pubkey import Pubkey
import sqlite3
import asyncio
from telegram import Bot
from flask import Flask, render_template, request
from threading import Thread
import time

# Logging setup
logging.basicConfig(filename='solana_bot.log', level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Constants
CONFIG_FILE = 'config.json'
DB_FILE = 'solana_tokens.db'

app = Flask(__name__)

def load_config():
    """Load and validate configuration from config.json and environment variables."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        # Override with environment variables
        config['helius_api_key'] = os.environ.get('HELIUS_API_KEY', config['helius_api_key'])
        config['solsniffer_api_key'] = os.environ.get('SOLSNIFFER_API_KEY', config['solsniffer_api_key'])
        config['solana_tracker_api_key'] = os.environ.get('SOLANA_TRACKER_API_KEY', config['solana_tracker_api_key'])
        config['telegram_notification_bot_token'] = os.environ.get('TELEGRAM_NOTIFICATION_BOT_TOKEN', config['telegram_notification_bot_token'])
        config['telegram_notification_chat_id'] = os.environ.get('TELEGRAM_NOTIFICATION_CHAT_ID', config['telegram_notification_chat_id'])
        
        config['filters'].setdefault('min_volume_24h', 0)
        config['filters'].setdefault('min_liquidity_usd', 0)
        config['filters'].setdefault('min_price_usd', 0)
        config['filters'].setdefault('max_price_change_1h', float('inf'))
        config.setdefault('coin_blacklist', [])
        config.setdefault('dev_blacklist', [])
        config.setdefault('rpc_endpoint', 'https://api.mainnet-beta.solana.com')
        config.setdefault('solsniffer_api_url', 'https://api.solsniffer.com/v1/token')
        config.setdefault('toxisol_bot_username', '@ToxiSolBot')
        config.setdefault('ui_port', 10000)
        config.setdefault('toxisol_slippage', 5)
        
        if not config['toxisol_user_wallet']:
            logger.error("ToxiSol user wallet address is required in config.json")
            raise ValueError("Missing ToxiSol user wallet address")
        
        logger.info("Configuration loaded successfully.")
        return config
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        raise

def init_db():
    """Initialize SQLite database for token tracking."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tokens
                 (token_address TEXT PRIMARY KEY, symbol TEXT, price_usd REAL,
                  volume_24h REAL, liquidity_usd REAL, solsniffer_score INTEGER,
                  solsniffer_status TEXT, last_updated INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (trade_id INTEGER PRIMARY KEY AUTOINCREMENT, token_address TEXT,
                  trade_type TEXT, amount REAL, price REAL, timestamp INTEGER)''')
    conn.commit()
    conn.close()

def fetch_tokens_dexscreener():
    """Fetch token data from DexScreener."""
    try:
        url = "https://api.dexscreener.com/latest/dex/tokens"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        tokens = []
        for token in data.get('pairs', []):
            tokens.append({
                'token_address': token['baseToken']['address'],
                'symbol': token['baseToken']['symbol'],
                'price_usd': float(token['priceUsd']),
                'volume_24h': float(token['volume']['h24']),
                'liquidity_usd': float(token['liquidity']['usd'])
            })
        logger.info(f"Fetched {len(tokens)} tokens from DexScreener.")
        return tokens
    except Exception as e:
        logger.error(f"Error fetching DexScreener data: {e}")
        return []

def check_solsniffer(token_address, api_key, api_url):
    """Check token safety with Solsniffer API."""
    try:
        headers = {'Authorization': f'Bearer {api_key}'}
        response = requests.get(f"{api_url}/{token_address}", headers=headers)
        response.raise_for_status()
        data = response.json()
        score = data.get('score', 0)
        fake_volume = data.get('fake_volume', False)
        rugger = data.get('rugger', False)
        cabal = data.get('cabal', False)
        status = 'Good' if score >= 85 and not (fake_volume or rugger or cabal) else 'Bad'
        logger.info(f"Solsniffer check for {token_address}: score={score}, status={status}")
        return score, status
    except Exception as e:
        logger.error(f"Error checking Solsniffer for {token_address}: {e}")
        return 0, 'Unknown'

def apply_filters(tokens, config):
    """Apply trading filters to token list."""
    filtered = []
    for token in tokens:
        if (token['symbol'] not in config['coin_blacklist'] and
            token['volume_24h'] >= config['filters']['min_volume_24h'] and
            token['liquidity_usd'] >= config['filters']['min_liquidity_usd'] and
            token['price_usd'] >= config['filters']['min_price_usd'] and
            token['price_usd'] <= config['filters']['max_price_change_1h']):
            filtered.append(token)
    logger.info(f"Applied filters: {len(filtered)} tokens remain.")
    return filtered

def update_db(tokens):
    """Update SQLite database with token data."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for token in tokens:
        c.execute('''INSERT OR REPLACE INTO tokens
                     (token_address, symbol, price_usd, volume_24h, liquidity_usd,
                      solsniffer_score, solsniffer_status, last_updated)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (token['token_address'], token['symbol'], token['price_usd'],
                   token['volume_24h'], token['liquidity_usd'], token.get('solsniffer_score', 0),
                   token.get('solsniffer_status', 'Unknown'), int(time.time())))
    conn.commit()
    conn.close()

async def send_telegram_notification(message, bot_token, chat_id):
    """Send notification to Telegram."""
    try:
        bot = Bot(token=bot_token)
        await bot.send_message(chat_id=chat_id, text=message)
        logger.info(f"Sent Telegram notification: {message}")
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")

def execute_trade(token_address, trade_type, amount, config):
    """Execute trade via ToxiSol Telegram bot."""
    try:
        message = f"{config['toxisol_bot_username']} /{trade_type.lower()} {token_address} {amount} {config['toxisol_slippage']}"
        asyncio.run(send_telegram_notification(message, config['telegram_notification_bot_token'],
                                              config['telegram_notification_chat_id']))
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''INSERT INTO trades (token_address, trade_type, amount, price, timestamp)
                     VALUES (?, ?, ?, ?, ?)''',
                  (token_address, trade_type, amount, 0, int(time.time())))
        conn.commit()
        conn.close()
        logger.info(f"Executed {trade_type} for {token_address}: amount={amount}")
    except Exception as e:
        logger.error(f"Error executing {trade_type} for {token_address}: {e}")

def trading_strategy(config):
    """Run trading strategy."""
    try:
        tokens = fetch_tokens_dexscreener()
        filtered_tokens = apply_filters(tokens, config)
        
        for token in filtered_tokens:
            score, status = check_solsniffer(token['token_address'], config['solsniffer_api_key'], config['solsniffer_api_url'])
            token['solsniffer_score'] = score
            token['solsniffer_status'] = status
            
            if score >= 85 and status == 'Good':
                balance = 1.0  # Placeholder; replace with actual wallet balance query
                trade_amount = min(balance * 0.05, 0.1)  # 5% of balance, capped at 0.1 SOL
                execute_trade(token['token_address'], 'buy', trade_amount, config)
                
                # Set take-profit (10x) and stop-loss (20%)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute('''SELECT price FROM trades WHERE token_address=? AND trade_type='buy' ORDER BY timestamp DESC LIMIT 1''',
                          (token['token_address'],))
                buy_price = c.fetchone()[0] if c.fetchone() else token['price_usd']
                take_profit_price = buy_price * 10
                stop_loss_price = buy_price * 0.8
                
                # Monitor price (simplified; use WebSocket or polling in production)
                current_price = token['price_usd']
                if current_price >= take_profit_price:
                    sell_amount = trade_amount * 0.85  # Sell 85%
                    execute_trade(token['token_address'], 'sell', sell_amount, config)
                    logger.info(f"Take-profit triggered for {token['token_address']}: Sold 85%")
                elif current_price <= stop_loss_price:
                    execute_trade(token['token_address'], 'sell', trade_amount, config)
                    logger.info(f"Stop-loss triggered for {token['token_address']}")
                
                token['take_profit_price'] = take_profit_price
                token['stop_loss_price'] = stop_loss_price
        
        update_db(filtered_tokens)
    except Exception as e:
        logger.error(f"Error in trading strategy: {e}")

@app.route('/')
def dashboard():
    """Render Flask dashboard."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM tokens')
    tokens = [{'token_address': row[0], 'symbol': row[1], 'price_usd': row[2],
               'volume_24h': row[3], 'liquidity_usd': row[4], 'solsniffer_status': row[6]}
              for row in c.fetchall()]
    conn.close()
    return render_template('dashboard.html', tokens=tokens)

@app.route('/trade', methods=['POST'])
def trade():
    """Handle manual trades from dashboard."""
    token_address = request.form['token_address']
    action = request.form['action']
    config = load_config()
    amount = 0.1  # Fixed amount for manual trades
    execute_trade(token_address, action.lower(), amount, config)
    return dashboard()

def run_trading_loop():
    """Run trading loop in a separate thread."""
    config = load_config()
    while True:
        trading_strategy(config)
        time.sleep(300)  # Run every 5 minutes

if __name__ == '__main__':
    init_db()
    Thread(target=run_trading_loop).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)