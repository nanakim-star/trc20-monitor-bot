import asyncio
import websockets
import json
import requests
import os
import time
from aiohttp import web # 웹 서버 라이브러리 임포트

# --- 1. 환경 변수 로드 (이전과 동일) ---
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
YOUR_WEBSITE_API_URL = os.environ.get("YOUR_WEBSITE_API_URL")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")

# Render가 웹 서비스에 할당하는 포트 번호 (필수)
PORT = os.environ.get("PORT", 8080) # Render가 $PORT 환경변수를 자동으로 설정해줌

# --- 2. 알림 및 콜백 함수 (이전과 동일) ---

def send_telegram_notification(message):
    # (이전 코드와 동일)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"Telegram 전송 실패: {e}")

def send_to_server_for_charge(tx_data):
    # (이전 코드와 동일)
    headers = {"Content-Type": "application/json", "X-Secret-Key": API_SECRET_KEY}
    try:
        requests.post(YOUR_WEBSITE_API_URL, json=tx_data, headers=headers, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"서버 전송 실패: {e}")

def process_incoming_transaction(tx_data):
    # (이전 코드와 동일)
    try:
        txid = tx_data.get("transaction_id")
        from_address = tx_data.get("from")
        to_address = tx_data.get("to")
        value_str = tx_data.get("value")
        decimals = 6 # USDT 기준
        amount = int(value_str) / (10 ** decimals)
        token_symbol = tx_data.get("token_info", {}).get("symbol", "USDT")

        print(f"[입금 감지] {amount} {token_symbol} from {from_address}")
        
        telegram_message = f"🔔 **USDT 입금 감지** 🔔\n💰 **금액:** {amount:.6f} {token_symbol}\n👤 **보낸 주소:** `{from_address}`\n🔗 **TXID:** `{txid}`"
        server_payload = {"txid": txid, "from_address": from_address, "to_address": to_address, "amount": amount, "symbol": token_symbol}
        
        send_telegram_notification(telegram_message)
        send_to_server_for_charge(server_payload)
    except Exception as e:
        print(f"트랜잭션 처리 오류: {e}")


# --- 3. 웹소켓 모니터링 로직 (이전과 동일) ---

async def listen_to_wallet_events():
    uri = "wss://api.trongrid.io/jsonrpc"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=30) as websocket:
                print(f"TronGrid WebSocket 연결 성공. 주소 구독 시작: {WALLET_ADDRESS}")
                subscribe_message = {"method": "subscribe", "params": ["trc20", {"address": WALLET_ADDRESS}]}
                await websocket.send(json.dumps(subscribe_message))

                async for message_raw in websocket:
                    try:
                        data = json.loads(message_raw)
                        if (data.get("to") and data.get("to").lower() == WALLET_ADDRESS.lower() and int(data.get("value", 0)) > 0):
                            process_incoming_transaction(data)
                    except Exception as e:
                        print(f"메시지 처리 중 오류: {e}")
        except Exception as e:
            print(f"WebSocket 연결 오류: {e}. 10초 후 재연결 시도...")
            await asyncio.sleep(10)

# --- 4. [신규] Render 휴면 방지용 웹 서버 로직 ---

async def start_web_server():
    app = web.Application()
    
    # UptimeRobot이 호출할 간단한 경로 설정
    async def health_check(request):
        print("Health check ping received.")
        return web.Response(text="Bot is alive and running.")

    app.router.add_get("/", health_check) # 루트 경로 PING 응답

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT) # 0.0.0.0:PORT 에서 수신 대기
    await site.start()
    print(f"Web server started on port {PORT} to prevent sleep.")
    # 웹 서버가 종료되지 않도록 대기
    await asyncio.Event().wait()

# --- 5. [수정] 메인 실행 로직 (웹소켓과 웹서버 동시 실행) ---

async def main():
    task1 = asyncio.create_task(listen_to_wallet_events()) # 봇 기능
    task2 = asyncio.create_task(start_web_server())      # 휴면 방지 기능
    await asyncio.gather(task1, task2)

if __name__ == "__main__":
    print("모니터링 봇 및 휴면 방지 웹서버 시작...")
    asyncio.run(main())
