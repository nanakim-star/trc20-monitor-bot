import asyncio
import websockets
import json
import requests
import os
import time
from aiohttp import web # Render 휴면 방지용 웹 서버 라이브러리

# --- 1. 환경 변수 로드 ---
# Render 대시보드의 'Environment' 탭에서 설정해야 합니다.
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
YOUR_WEBSITE_API_URL = os.environ.get("YOUR_WEBSITE_API_URL")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")

# Render가 웹 서비스에 할당하는 포트 번호 (필수)
PORT = os.environ.get("PORT", 8080)

# --- 설정값 검증 ---
if not all([WALLET_ADDRESS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, YOUR_WEBSITE_API_URL, API_SECRET_KEY]):
    print("!!!!!!!!!! [시작 오류] !!!!!!!!!!!")
    print("오류: 필수 환경 변수가 설정되지 않았습니다.")
    print("Render 대시보드에서 다음 변수들을 설정했는지 확인하세요:")
    print("WALLET_ADDRESS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, YOUR_WEBSITE_API_URL, API_SECRET_KEY")
    # 스크립트 종료
    exit()
else:
    print("[시작 준비] 모든 환경 변수가 성공적으로 로드되었습니다.")


# --- 2. 동기식 알림 함수 ---

def send_telegram_notification(message):
    """텔레그램으로 메시지를 전송합니다."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print("[알림] Telegram 알림 전송 성공")
        else:
            print(f"[알림 오류] Telegram API 오류: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"[알림 오류] Telegram 메시지 전송 중 예외 발생: {e}")

def send_to_server_for_charge(tx_data):
    """자동 충전을 위해 웹사이트 서버로 데이터를 전송합니다."""
    headers = {
        "Content-Type": "application/json",
        "X-Secret-Key": API_SECRET_KEY
    }
    try:
        response = requests.post(YOUR_WEBSITE_API_URL, json=tx_data, headers=headers, timeout=10)
        if response.status_code == 200:
            print(f"[알림] 서버 콜백 성공: {response.text}")
        else:
            print(f"[알림 오류] 서버 콜백 실패 (Status Code: {response.status_code}): {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"[알림 오류] 서버 콜백 연결 중 예외 발생: {e}")

# --- 3. 트랜잭션 처리 로직 ---

def process_incoming_transaction(tx_data):
    """수신된 트랜잭션 데이터를 파싱하고 알림/콜백을 실행합니다."""
    try:
        # 데이터 추출
        txid = tx_data.get("transaction_id")
        from_address = tx_data.get("from")
        to_address = tx_data.get("to")
        value_str = tx_data.get("value")
        decimals = 6 # USDT 기준
        amount = int(value_str) / (10 ** decimals)
        token_symbol = tx_data.get("token_info", {}).get("symbol", "USDT")

        # 텔레그램 알림 메시지 생성
        telegram_message = (
            f"🔔 **USDT 입금 감지 ({token_symbol})** 🔔\n\n"
            f"💰 **금액:** {amount:.6f} {token_symbol}\n"
            f"👤 **보낸 주소:** `{from_address}`\n"
            f"🔗 **TXID:** `{txid}`"
        )
        
        # 서버 콜백 페이로드 생성
        server_payload = {
            "txid": txid,
            "from_address": from_address,
            "to_address": to_address,
            "amount": amount,
            "symbol": token_symbol,
            "timestamp_ms": tx_data.get("block_timestamp", int(time.time() * 1000))
        }

        # 알림 및 콜백 실행
        send_telegram_notification(telegram_message)
        send_to_server_for_charge(server_payload)

    except Exception as e:
        print(f"[오류] process_incoming_transaction 함수 내부 오류: {e}\n원본 데이터: {tx_data}")


# --- 4. 비동기 웹소켓 연결 및 구독 로직 (디버깅 PPRINT 추가됨) ---

async def listen_to_wallet_events():
    uri = "wss://api.trongrid.io/jsonrpc"
    print("[디버그 1] listen_to_wallet_events 함수 시작됨.")

    while True:
        print("\n[디버그 2] 새로운 Websocket 연결 시도 시작...")
        try:
            # 10초 연결 타임아웃 설정 추가
            async with websockets.connect(uri, ping_interval=30, open_timeout=10) as websocket:
                
                print("[디버그 3] WebSocket 연결 성공! (uri: {uri})") # ★★★★★ 중요 체크포인트 1

                subscribe_message = {
                    "method": "subscribe",
                    "params": [
                        "trc20",
                        {"address": WALLET_ADDRESS}
                    ]
                }
                
                print(f"[디버그 4] 구독 메시지 전송 시도: {json.dumps(subscribe_message)}")
                await websocket.send(json.dumps(subscribe_message))
                print("[디버그 5] 구독 메시지 전송 완료. 서버 응답 대기 중...") # ★★★★★ 중요 체크포인트 2

                # 메시지 수신 대기 루프
                async for message_raw in websocket:
                    # [디버그 6] TronGrid로부터 수신된 모든 원본 데이터 출력
                    print(f"[디버그 6 - 수신 데이터] {message_raw}") 
                    
                    try:
                        data = json.loads(message_raw)
                        # 입금 이벤트 필터링 (내 지갑 주소로 들어오고, 금액이 0보다 큰 경우)
                        if (data.get("to") and
                            data.get("to").lower() == WALLET_ADDRESS.lower() and
                            int(data.get("value", 0)) > 0):
                            print("[디버그 7] 입금 조건 일치! process_incoming_transaction 호출.")
                            process_incoming_transaction(data)

                    except json.JSONDecodeError:
                         print(f"[오류] 수신된 데이터 JSON 파싱 실패: {message_raw}")
                    except Exception as e:
                        print(f"[오류] 메시지 처리 중 예외 발생: {e}")

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[오T류] WebSocket 연결 끊김 (ConnectionClosed): {e}")
        except asyncio.TimeoutError:
            print("[오류] WebSocket 연결 시간 초과 (TimeoutError).")
        except Exception as e:
            print(f"[오류] WebSocket 루프에서 예기치 않은 오류 발생: {type(e).__name__} - {e}")
        
        print("[디버그 8] 10초 후 재연결 시도...")
        await asyncio.sleep(10)

# --- 5. Render 휴면 방지용 웹 서버 로직 ---

async def start_web_server():
    app = web.Application()
    
    async def health_check(request):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Health check ping received.")
        return web.Response(text="Bot is alive and running.")

    app.router.add_get("/", health_check) # 루트 경로 PING 응답

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(PORT))
    
    print(f"[웹서버] 휴면 방지 웹서버 시작됨. Port: {PORT}")
    await site.start()
    
    # 웹 서버가 종료되지 않도록 무한 대기
    await asyncio.Event().wait()

# --- 6. 메인 실행 로직 (웹소켓과 웹서버 동시 실행) ---

async def main():
    task1 = asyncio.create_task(listen_to_wallet_events()) # 봇 기능
    task2 = asyncio.create_task(start_web_server())      # 휴면 방지 기능
    await asyncio.gather(task1, task2)

if __name__ == "__main__":
    print("모니터링 봇 및 휴면 방지 웹서버 시작...")
    asyncio.run(main())
