import asyncio
import requests
import os
import time
from aiohttp import web # 웹 서버 라이브러리

# --- 1. 환경 변수 로드 ---
# Render 대시보드의 'Environment' 탭에서 설정해야 합니다.
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
        # ★★★★★ 수정된 부분 ★★★★★
        # Tatum 로그를 기반으로 '보낸 주소'와 '받는 주소'를 정확한 키에서 추출합니다.
        txid = data.get("txId", "N/A")
        amount = float(data.get("amount", 0)) 
        from_address = data.get("counterAddress", "N/A") # '보낸 주소'는 counterAddress 입니다.
        to_address = data.get("address", "N/A")         # '받는 주소'(내 지갑)는 address 입니다.
        token_symbol = "USDT"  # USDT_TRON 에서 USDT 부분만 사용하도록 고정

        # 0원 거래나 불필요한 이벤트 필터링
        if amount == 0:
            print(f"[데이터 처리] 금액 0 트랜잭션 필터링됨 (TXID: {txid})")
            return

        print(f"[데이터 처리] 입금 감지: {amount} {token_symbol} from {from_address}")

        # 1. 텔레그램 알림 메시지 생성
        telegram_message = (
            f"**USDT 충전봇이 지갑에 입금 내역 감지하였습니다.**\n\n"
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
        data = await request.json()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Tatum Webhook 수신 성공: {data}")
        
        # 데이터 처리 함수 호출
        process_tatum_webhook_data(data)
        
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
    
    await asyncio.Event().wait() # 서버가 종료되지 않도록 무한 대기

# --- 5. 메인 실행 로직 ---

if __name__ == "__main__":
    print("Tatum 웹훅 수신 서버를 시작합니다...")
    asyncio.run(start_web_server())
