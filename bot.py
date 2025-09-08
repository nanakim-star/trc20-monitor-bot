import asyncio
import websockets
import json
import requests
import os
import time

# --- 1. 환경 변수 로드 ---
# Render 대시보드의 'Environment' 탭에서 설정해야 합니다.
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
YOUR_WEBSITE_API_URL = os.environ.get("YOUR_WEBSITE_API_URL")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")

# --- 설정값 검증 ---
if not all([WALLET_ADDRESS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, YOUR_WEBSITE_API_URL, API_SECRET_KEY]):
    print("오류: 필수 환경 변수가 설정되지 않았습니다.")
    print("Render 대시보드에서 다음 변수들을 설정하세요:")
    print("WALLET_ADDRESS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, YOUR_WEBSITE_API_URL, API_SECRET_KEY")
    # 스크립트 종료 (Render에서는 재시작됨)
    exit()

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
            print("Telegram 알림 전송 성공")
        else:
            print(f"Telegram API 오류: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Telegram 메시지 전송 중 예외 발생: {e}")

def send_to_server_for_charge(tx_data):
    """자동 충전을 위해 웹사이트 서버로 데이터를 전송합니다."""
    headers = {
        "Content-Type": "application/json",
        "X-Secret-Key": API_SECRET_KEY  # 서버 인증용 비밀 키
    }
    try:
        response = requests.post(YOUR_WEBSITE_API_URL, json=tx_data, headers=headers, timeout=10)
        if response.status_code == 200:
            print(f"서버 콜백 성공: {response.text}")
        else:
            print(f"서버 콜백 실패 (Status Code: {response.status_code}): {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"서버 콜백 연결 중 예외 발생: {e}")

# --- 3. 트랜잭션 처리 로직 ---

def process_incoming_transaction(tx_data):
    """수신된 트랜잭션 데이터를 파싱하고 알림/콜백을 실행합니다."""
    try:
        # 1. 데이터 추출
        txid = tx_data.get("transaction_id")
        from_address = tx_data.get("from")
        to_address = tx_data.get("to")
        value_str = tx_data.get("value")

        # 필수 데이터 누락 시 처리 중단
        if not all([txid, from_address, to_address, value_str]):
            print(f"[경고] 필수 필드가 누락된 데이터 수신: {tx_data}")
            return

        # 2. 금액 계산 (USDT는 소수점 6자리 고정)
        decimals = 6
        amount = int(value_str) / (10 ** decimals)

        # 3. 토큰 심볼 확인 (USDT가 아닐 수도 있으니 확인)
        token_info = tx_data.get("token_info", {})
        token_symbol = token_info.get("symbol", "USDT") # 기본값 USDT

        # 4. 텔레그램 알림 메시지 생성
        telegram_message = (
            f"🔔 **USDT 입금 감지 ({token_symbol})** 🔔\n\n"
            f"💰 **금액:** {amount:.6f} {token_symbol}\n"
            f"👤 **보낸 주소:** `{from_address}`\n"
            f"🔗 **TXID:** `{txid}`"
        )
        
        # 5. 서버 콜백 페이로드 생성
        server_payload = {
            "txid": txid,
            "from_address": from_address,
            "to_address": to_address,
            "amount": amount,
            "symbol": token_symbol,
            "timestamp_ms": tx_data.get("block_timestamp", int(time.time() * 1000))
        }

        # 6. 알림 및 콜백 실행
        send_telegram_notification(telegram_message)
        send_to_server_for_charge(server_payload)

    except Exception as e:
        print(f"트랜잭션 처리 중 오류 발생: {e}\n원본 데이터: {tx_data}")


# --- 4. 비동기 웹소켓 연결 및 구독 로직 ---

async def listen_to_wallet_events():
    uri = "wss://api.trongrid.io/jsonrpc"

    while True:
        try:
            async with websockets.connect(uri, ping_interval=30) as websocket:
                print(f"TronGrid WebSocket 연결 성공.")
                print(f"주소 구독 시작: {WALLET_ADDRESS}")

                # 구독 요청 메시지 (지갑 주소와 관련된 TRC20 이벤트 구독)
                subscribe_message = {
                    "method": "subscribe",
                    "params": [
                        "trc20",
                        {"address": WALLET_ADDRESS}
                    ]
                }
                await websocket.send(json.dumps(subscribe_message))

                # 메시지 수신 대기 루프
                async for message_raw in websocket:
                    try:
                        data = json.loads(message_raw)

                        # 입금 이벤트 필터링:
                        # 1. 'to' 필드가 존재하고, 내 지갑 주소와 일치하는지 확인 (대소문자 구분 없이)
                        # 2. 'transaction_id' 필드가 존재하는지 확인 (이벤트 트리거 확인 메시지가 아님)
                        if (data.get("to") and
                            data.get("to").lower() == WALLET_ADDRESS.lower() and
                            data.get("transaction_id")):
                            
                            # 0원 입금(컨트랙트 상호작용 등) 필터링
                            if int(data.get("value", 0)) > 0:
                                print(f"\n[입금 감지] TXID: {data.get('transaction_id')}")
                                process_incoming_transaction(data)

                    except json.JSONDecodeError:
                        print(f"[오류] JSON 파싱 실패: {message_raw}")
                    except Exception as e:
                        print(f"[오류] 메시지 처리 중 예외 발생: {e}")

        except websockets.exceptions.ConnectionClosed as e:
            print(f"WebSocket 연결 끊김 (오류: {e}). 10초 후 재연결 시도...")
        except Exception as e:
            print(f"WebSocket 연결 중 예기치 않은 오류 발생: {e}. 10초 후 재연결 시도...")
        
        await asyncio.sleep(10)

# --- 5. 프로그램 시작 ---
if __name__ == "__main__":
    print("USDT (TRC20) 입금 모니터링 봇을 시작합니다...")
    asyncio.run(listen_to_wallet_events())
