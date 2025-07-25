from flask import Flask, render_template, request, redirect
import requests
import os
from telegram import Bot
import asyncio
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_NOTIFICATION_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_NOTIFICATION_CHAT_ID')
SOLSNIFFER_API_KEY = os.getenv('SOLSNIFFER_API_KEY')
SOLSNIFFER_API_URL = "https://api.solsniffer.com/v1/token"
TOXISOL_WALLET = os.getenv('toxisol_user_wallet', '956FpaMnWhqK91NtD4xbjwTvCbcXWHpPSCDmXb9WoMq')
TOXISOL_BOT = "@ToxiSolBot"

bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

def get_tokens():
    """Fetch tokens from Solsniffer or return mock data for testing."""
    try:
        headers = {"Authorization": f"Bearer {SOLSNIFFER_API_KEY}"}
        response = requests.get(SOLSNIFFER_API_URL, headers=headers)
        response.raise_for_status()
        data = response.json()
        tokens = data.get('tokens', [])
        if not tokens:  # Fallback to mock data if API returns empty
            tokens = [
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
        return tokens
    except Exception as e:
        logging.error(f"Error fetching tokens: {e}")
        # Fallback mock data
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
        message = f"{action} request for token {token_address} via {TOXISOL_BOT}"
        logging.info(message)
        # Simulate ToxiSol trade (replace with actual API call if available)
        asyncio.run(send_telegram_notification(message))
    else:
        logging.error("Missing token_address or action in trade request")
    return redirect('/')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))