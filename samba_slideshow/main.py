import os
import json
import time
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from smb.SMBConnection import SMBConnection

# Load Home Assistant options safely
OPTIONS_PATH = "/data/options.json"
if os.path.exists(OPTIONS_PATH):
    with open(OPTIONS_PATH, "r") as f:
        options = json.load.get(f, {})
else:
    options = {
        "samba_host": "192.168.1.50",
        "samba_share": "media",
        "samba_folder": "photos",
        "username": "admin",
        "password": "",
        "interval_seconds": 30
    }

SAMBA_HOST = options.get("samba_host")
SAMBA_SHARE = options.get("samba_share")
SAMBA_FOLDER = options.get("samba_folder")
USERNAME = options.get("username")
PASSWORD = options.get("password")
INTERVAL = options.get("interval_seconds", 30)

# Local output path inside HA config www folder so it can be used in cards easily
OUTPUT_DIR = "/config/www"
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_IMAGE_PATH = os.path.join(OUTPUT_DIR, "slideshow_current.jpg")

current_image_name = "None"
image_list = []
lock = threading.Lock()

def fetch_samba_images():
    global image_list
    try:
        # Simple connection using pysmb
        conn = SMBConnection(USERNAME, PASSWORD, "ha_client", SAMBA_HOST, use_ntlm_v2=True)
        if conn.connect(SAMBA_HOST, 445):
            shares = conn.listPath(SAMBA_SHARE, "/" + SAMBA_FOLDER)
            files = [file.filename for file in shares if file.filename.lower().endswith(('.png', '.jpg', '.jpeg'))]
            with lock:
                image_list = files
            conn.close()
            print(f"Successfully fetched {len(image_list)} images from Samba.")
    except Exception as e:
        print(f"Error connecting to Samba share: {e}")

def update_slideshow_loop():
    global current_image_name
    while True:
        time.sleep(INTERVAL)
        with lock:
            if not image_list:
                fetch_samba_images()
            if image_list:
                chosen = random.choice(image_list)
                current_image_name = chosen
                try:
                    conn = SMBConnection(USERNAME, PASSWORD, "ha_client", SAMBA_HOST, use_ntlm_v2=True)
                    if conn.connect(SAMBA_HOST, 445):
                        remote_file_path = f"/{SAMBA_FOLDER}/{chosen}"
                        with open(OUTPUT_IMAGE_PATH, "wb") as fp:
                            conn.getFile(SAMBA_SHARE, remote_file_path, fp)
                        conn.close()
                        print(f"Updated slideshow image to: {chosen}")
                except Exception as e:
                    print(f"Failed to download image file: {e}")

class SlideshowHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global current_image_name
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == "/shuffle":
            # Force immediate shuffle
            with lock:
                if image_list:
                    chosen = random.choice(image_list)
                    current_image_name = chosen
                    try:
                        conn = SMBConnection(USERNAME, PASSWORD, "ha_client", SAMBA_HOST, use_ntlm_v2=True)
                        if conn.connect(SAMBA_HOST, 445):
                            remote_path = f"/{SAMBA_FOLDER}/{chosen}"
                            with open(OUTPUT_IMAGE_PATH, "wb") as fp:
                                conn.getFile(SAMBA_SHARE, remote_path, fp)
                            conn.close()
                    except Exception as e:
                        print(f"Manual shuffle error: {e}")
            self.send_response(303)
            self.send_header('Location', '/')
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Samba Slideshow Controller</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; background: #111; color: #fff; margin-top: 50px; }}
                img {{ max-width: 600px; max-height: 400px; border: 4px solid #444; border-radius: 8px; margin-top: 20px; }}
                button {{ padding: 12px 24px; font-size: 16px; background: #03a9f4; color: white; border: none; border-radius: 4px; cursor: pointer; }}
                button:hover {{ background: #0288d1; }}
            </style>
        </head>
        <body>
            <h1>Samba Slideshow Control Panel</h1>
            <p>Current Active Image: <strong>{current_image_name}</strong></p>
            <p>Interval Timer: {INTERVAL} seconds</p>
            <br>
            <form action="/shuffle" method="get">
                <button type="submit">Shuffle Next Image Now</button>
            </form>
            <br><br>
            <div>
                <h3>Live Preview Output:</h3>
                <img src="/local/slideshow_current.jpg?t={time.time()}" alt="Current Slideshow Image">
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

def run_server():
    server = HTTPServer(('0.0.0.0', 8099), SlideshowHTTPHandler)
    server.serve_forever()

if __name__ == "__main__":
    # Initial fetch
    fetch_samba_images()
    
    # Start background loop for timer changes
    t = threading.Thread(target=update_slideshow_loop, daemon=True)
    t.start()
    
    # Start WebUI server
    run_server()
