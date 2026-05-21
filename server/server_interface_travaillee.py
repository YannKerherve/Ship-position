import asyncio
import websockets
import customtkinter as ctk
from threading import Thread
from queue import Queue
from flask import Flask, send_from_directory, Response
from tkinter import messagebox

# ================== STYLE ==================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

WINDY_RED  = "#e53935"
WINDY_DARK = "#222222"
WINDY_GREY = "#333333"

# ================== GLOBALS ==================
TCP_IP = None
TCP_PORT = None
latest_data = ""
connected_clients = set()
log_queue = Queue()

# ================== LOAD CONFIG ==================
try:
    with open("data.txt", "r") as f:
        ip, port = f.read().strip().split(":")
except:
    ip, port = "127.0.0.1", "10110"

# ================== FLASK ==================
app = Flask(__name__, static_folder="static")

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/gps-data")
def gps_data():
    return Response(latest_data, content_type="text/plain")

def start_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# ================== GUI ==================
class WindyBridgeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("WINDY TCP BRIDGE")
        self.geometry("520x640")
        self.configure(fg_color=WINDY_DARK)

        
        try:
            # On n'applique l'icône que si on est sur Windows
            if sys.platform.startswith("win"):
                self.iconbitmap("ico.ico")
                self.after(200, lambda: self.iconbitmap("ico.ico"))
        except:
            pass

        # -------- TITLES --------
        ctk.CTkLabel(
            self, text="WINDY POSITION PLUGIN",
            font=("Helvetica", 24, "bold"),
            text_color=WINDY_RED
        ).pack(pady=(20, 5))

        ctk.CTkLabel(
            self, text="Marine Data Bridge",
            font=("Helvetica", 13),
            text_color="#cccccc"
        ).pack(pady=(0, 20))

        # -------- MAIN FRAME --------
        self.main_frame = ctk.CTkFrame(self, fg_color=WINDY_GREY, corner_radius=15)
        self.main_frame.pack(padx=20, pady=10, fill="x")

        # -------- IP --------
        ctk.CTkLabel(self.main_frame, text="TCP IP ADDRESS").pack(pady=(15, 0))
        self.ip_entry = ctk.CTkEntry(self.main_frame, width=320)
        self.ip_entry.pack(pady=5)
        self.ip_entry.insert(0, ip)

        # -------- PORT --------
        ctk.CTkLabel(self.main_frame, text="TCP PORT").pack(pady=(10, 0))
        self.port_entry = ctk.CTkEntry(self.main_frame, width=320)
        self.port_entry.pack(pady=5)
        self.port_entry.insert(0, port)

        # -------- BUTTON --------
        self.start_button = ctk.CTkButton(
            self.main_frame,
            text="START TRANSMISSION",
            fg_color=WINDY_RED,
            hover_color="#b71c1c",
            height=45,
            font=("Helvetica", 14, "bold"),
            command=self.start_bridge
        )
        self.start_button.pack(pady=25)

        # -------- LOG AREA --------
        self.log_area = ctk.CTkTextbox(
            self, width=480, height=220,
            fg_color="#111111",
            text_color="#00ff66",
            font=("Consolas", 12)
        )
        self.log_area.pack(padx=20, pady=20)

        self.after(100, self.process_logs)
        self.log("> System ready. Waiting for input...")

    # ---------- LOG HANDLING ----------
    def log(self, msg):
        self.log_area.insert("end", f"{msg}\n")
        self.log_area.see("end")

    def process_logs(self):
        while not log_queue.empty():
            self.log("> " + log_queue.get())
        self.after(100, self.process_logs)

    # ---------- START ----------
    def start_bridge(self):
        global TCP_IP, TCP_PORT

        TCP_IP = self.ip_entry.get()
        try:
            TCP_PORT = int(self.port_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Port must be a number")
            return

        with open("data.txt", "w") as f:
            f.write(f"{TCP_IP}:{TCP_PORT}")

        self.start_button.configure(state="disabled", text="RUNNING...", fg_color="#444")
        log_queue.put(f"Connecting to {TCP_IP}:{TCP_PORT}")

        Thread(target=start_flask, daemon=True).start()
        Thread(target=start_asyncio, daemon=True).start()

# ================== ASYNCIO ==================
async def tcp_reader():
    global latest_data
    try:
        reader, _ = await asyncio.open_connection(TCP_IP, TCP_PORT)
        log_queue.put("CONNECTED TO TCP SOURCE")

        while True:
            data = await reader.read(1024)
            if not data:
                break

            message = data.decode(errors="ignore").strip()
            latest_data = message
            log_queue.put(f"TCP DATA: {message[:60]}")

            for ws in list(connected_clients):
                try:
                    await ws.send(message)
                except:
                    connected_clients.remove(ws)

    except Exception as e:
        log_queue.put(f"TCP ERROR: {e}")

async def websocket_handler(websocket):
    connected_clients.add(websocket)
    log_queue.put("WebSocket client connected")
    try:
        async for _ in websocket:
            pass
    finally:
        connected_clients.remove(websocket)
        log_queue.put("WebSocket client disconnected")
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response
async def main_async():
    async with websockets.serve(websocket_handler, "0.0.0.0", 6789):
        log_queue.put("WebSocket server: ws://localhost:6789")
        await tcp_reader()

def start_asyncio():
    asyncio.run(main_async())

# ================== MAIN ==================
if __name__ == "__main__":
    WindyBridgeApp().mainloop()
