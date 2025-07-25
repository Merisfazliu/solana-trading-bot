from flask import Flask, render_template, request, redirect
import requests
import os
from telegram import Bot
import asyncio
import logging
import json
from datetime import datetime, timedelta

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Load configuration
try:
    with open('config.json') as f:
        config = json.load(f)
except FileNotFoundError:
    logging.error("config.json not found, using defaults")
    config = {
        "filters": {
            "min_volume_24h": 10000,
            "min_liquidity_usd": 5000,
            "min_price_usd": 0.0001,
            "max_price_change_1h": 500
        },
        "toxisol_user_wallet": "956FpaMnWhqK91NtD4xbjwTvCbtcGXWHpPSCDmXb9WoMq",
        "toxisol_bot_username": "@ToxiSolBot",
        "ui_port": 10000,
        "toxisol_slippage": 5
    }

# Environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_NOTIFICATION_BOT_TOKEN', config.get('telegram_notification_bot_token'))
CHAT_ID = os.getenv('TELEGRAM_NOTIFICATION_CHAT_ID', config.get('telegram_notification_chat_id'))
DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/tokens"

bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

def get_tokens():
    """Fetch tokens from DexScreener with filters."""
    try:
        response = requests.get(DEXSCREENER_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        tokens = data.get('pairs', [])

        filtered_tokens = []
        for token in tokens:
            if token.get('chainId') != 'solana':
                continue
            liquidity = float(token.get('liquidity', {}).get('usd', 0))
            volume_24h = float(token.get('volume', {}).get('h24', 0))
            price_usd = float(token.get('priceUsd', 0))
            price_change_1h = float(token.get('priceChange', {}).get('h1', 0))
            created_at = token.get('createdAt', '')
            try:
                token_age = datetime.utcnow() - datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                hours_old = token_age.total_seconds() / 3600
            except:
                hours_old = 0

            if (liquidity >= config['filters']['min_liquidity_usd'] and
                volume_24h >= config['filters']['min_volume_24h'] and
                price_usd >= config['filters']['min_price_usd'] and
                price_change_1h <= config['filters']['max_price_change_1h'] and
                hours_old >= 24):
                filtered_tokens.append({
                    "symbol": token.get('baseToken', {}).get('symbol', 'UNKNOWN'),
                    "price_usd": price_usd,
                    "volume_24h": volume_24h,
                    "liquidity_usd": liquidity,
                    "solsniffer_status": "Good",  # Placeholder, add Rugcheck if needed
                    "token_address": token.get('baseToken', {}).get('address', 'UNKNOWN')
                })

        if not filtered_tokens:
            logging.warning("No tokens meet criteria, using mock data")
            filtered_tokens = [
                {
                    "symbol": "TOKEN1",
                    "price_usd": 0.01,
                    "volume_24h": 10000,
                    "liquidity_usd": 5000,
                    "solsniffer_status": "Good",
                    "token_address": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
                },
                {
                    "symbol": "TOKEN2",
                    "price_usd": 0.02,
                    "volume_24h": 20000,
                    "liquidity_usd": 8000,
                    "solsniffer_status": "Good",
                    "token_address": "7x8By5twvM3eW3nWv2PB6mjX7u4i8gYvWaJ3pFWCfZ2"
                }
            ]
        return filtered_tokens[:10]
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching tokens from DexScreener: {e}")
        return [
            {
                "symbol": "TEST",
                "price_usd": 0.01,
                "volume_24h": 1000,
                "liquidity_usd": 500,
                "solsniffer_status": "Test",
                "token_address": "TEST_ADDRESS"
            }
        ]

async def send_telegram_notification(message):
    """Send notification to Telegram."""
    if bot and CHAT_ID:
        try:
            await bot.send_message(chat_id=CHAT_ID, text=message)
        except Exception as e:
            logging.error(f"Telegram notification error: {e}")

@app.route('/')
def dashboard():
    """Render the dashboard with token data."""
    tokens = get_tokens()
    logging.info(f"Rendering dashboard with {len(tokens)} tokens")
    return render_template('dashboard.html', tokens=tokens)

@app.route('/trade', methods=['POST'])
def trade():
    """Handle Buy/Sell actions."""
    token_address = request.form.get('token_address')
    action = request.form.get('action')
    if token_address and action:
        message = f"{action} {token_address} with 5% balance (max 0.1 SOL), slippage {config['toxisol_slippage']}%, via {config['toxisol_bot_username']}"
        logging.info(message)
        asyncio.run(send_telegram_notification(message))
    else:
        logging.error("Missing token_address or action in trade request")
    return redirect('/')

@app.route('/debug')
def debug():
    """Debug endpoint to check token data."""
    tokens = get_tokens()
    return {"tokens": tokens}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', config.get('ui_port', 10000))))