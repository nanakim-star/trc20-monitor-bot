import asyncio
import requests
import os
import time
from aiohttp import web # 웹 서버 라이브러리

# --- 1. 환경 변수 로드 ---
# Render 대시보드의 'Environment' 탭에서 설정해야 합니다.
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS") # 모니터링 대상 주소 (참고용으로 남겨둘 수 있음)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
YOUR_WEBSITE_API_URL = os.environ.get("YOUR_WEBSITE_API_URL")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")

# Render가 웹 서비스에 할당하는 포트 번호 (필수)
PORT = os.environ.get("PORT", 8080)

# --- 설정값 검증 ---
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, YOUR_WEBSITE_API_URL, API_SECRET_KEY]):
    print("!!!!!!!!!! [시작 오류] !!!!!!!!!!!")
    print("오류: 필수 환경 변수가 설정되지 않았습니다.")
    print("TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, YOUR_WEBSITE_API_URL, API_SECRET_KEY 필요")
    exit()
else:
    print("[시작 준비] 모든 환경 변수가 성공적으로 로드되었습니다.")


# --- 2. 알림 전송 함수 ---

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

# --- 3. 웹훅 데이터 처리 로직 ---

def process_tatum_webhook_data(data):
    """Tatum에서 받은 데이터를 파싱하고 알림/콜백을 실행합니다."""
    try:
        # [중요] Tatum 웹훅 데이터 구조에 맞춰 파싱해야 합니다.
        # Tatum API 문서를 보고 txid, from, to, amount, symbol 키를 정확히 추출해야 합니다.
        # 아래는 예시 구조이며, 실제 데이터 형식에 따라 수정이 필요합니다.

        # 예시: if data.get("type") == "INCOMING_TRANSACTION" and data.get("chain") == "TRON":
        txid = data.get("txId", "N/A")
        amount = float(data.get("amount", 0)) # 금액 파싱 (숫자형으로 변환)
        from_address = data.get("address", {}).get("from", "N/A") # 데이터 구조에 따라 깊이가 다를 수 있음
        to_address = data.get("address", {}).get("to", "N/A")
        token_symbol = data.get("asset", "USDT") # 토큰 심볼 추출

        print(f"[데이터 처리] 입금 감지: {amount} {token_symbol} from {from_address}")

        # 1. 텔레그램 알림 메시지 생성
        telegram_message = (
            f"🔔 **Tatum 웹훅 입금 감지 ({token_symbol})** 🔔\n\n"
            f"💰 **금액:** {amount} {token_symbol}\n"
            f"👤 **보낸 주소:** `{from_address}`\n"
            f"🔗 **TXID:** `{txid}`"
        )
        
        # 2. 서버 콜백 페이로드 생성
        server_payload = {
            "txid": txid,
            "from_address": from_address,
            "to_address": to_address,
            "amount": amount,
            "symbol": token_symbol,
            "timestamp_ms": data.get("timestamp", int(time.time() * 1000))
        }

        # 3. 알림 및 콜백 실행
        send_telegram_notification(telegram_message)
        send_to_server_for_charge(server_payload)

    except Exception as e:
        print(f"[오류] process_tatum_webhook_data 함수 내부 오류: {e}\n원본 데이터: {data}")

# --- 4. 웹 서버 로직 (휴면 방지 및 웹훅 수신) ---

async def handle_tatum_webhook(request):
    """Tatum에서 보낸 POST 요청을 처리합니다."""
    try:
        # Tatum이 보낸 JSON 데이터를 파싱합니다.
        data = await request.json()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Tatum Webhook 수신 성공: {data}")
        
        # 데이터 처리 함수 호출
        process_tatum_webhook_data(data)
        
        # Tatum 서버에 정상 수신 응답 (HTTP 200 OK)
        return web.Response(text="Webhook received successfully")

    except Exception as e:
        print(f"[오류] 웹훅 요청 처리 중 오류 발생: {e}")
        return web.Response(status=500, text="Internal server error")

async def health_check(request):
    """UptimeRobot 휴면 방지용 PING 응답 핸들러."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Health check ping received.")
    return web.Response(text="Bot server is alive.")

async def start_web_server():
    app = web.Application()
    
    # 라우터 설정
    app.router.add_get("/", health_check)                 # UptimeRobot용 PING 경로
    app.router.add_post("/tatum-callback", handle_tatum_webhook) # Tatum 웹훅 수신 경로

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(PORT))
    
    print(f"[웹서버] 휴면 방지 및 웹훅 수신 서버 시작됨. Port: {PORT}")
    print(f"웹훅 수신 주소: http://0.0.0.0:{PORT}/tatum-callback")
    await site.start()
    
    # 서버가 종료되지 않도록 무한 대기
    await asyncio.Event().wait()

# --- 5. 메인 실행 로직 ---

if __name__ == "__main__":
    print("Tatum 웹훅 수신 서버를 시작합니다...")
    asyncio.run(start_web_server())
