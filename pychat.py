import base64
import json
import os
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

APP_NAME = "PyChat"
DEFAULT_PORT = 9999
HEADER_SIZE = 8


class PyChatApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("560x720")
        self.root.minsize(420, 560)
        self.root.resizable(True, True)

        self.username = "Self"
        self.server_socket = None
        self.connections = []
        self.running = True
        self.msg_queue = queue.Queue()

        self.last_typing_sent = 0
        self.typing_clear_job = None
        self.image_refs = []

        self.colors = {
            "bg": "#0B0F14",
            "surface": "#111820",
            "surface2": "#182330",
            "primary": "#4CAF50",
            "primary_dark": "#2E7D32",
            "text": "#EAF0F6",
            "muted": "#8FA3B8",
            "incoming": "#1D2B3A",
            "outgoing": "#2E7D32",
            "system": "#263241",
        }

        self.build_ui()
        self.poll_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        self.root.configure(bg=self.colors["bg"])

        header = tk.Frame(self.root, bg=self.colors["surface"], height=74)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_box = tk.Frame(header, bg=self.colors["surface"])
        title_box.pack(side="left", padx=16, pady=10)

        tk.Label(
            title_box,
            text="PyChat",
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")

        self.status_label = tk.Label(
            title_box,
            text="Offline",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        )
        self.status_label.pack(anchor="w")

        actions = tk.Frame(header, bg=self.colors["surface"])
        actions.pack(side="right", padx=10)

        self.host_btn = self.header_button(actions, "Host", self.host_dialog)
        self.host_btn.pack(side="left", padx=4)

        self.connect_btn = self.header_button(actions, "Connect", self.connect_dialog)
        self.connect_btn.pack(side="left", padx=4)

        self.menu_btn = self.header_button(actions, "⋮", self.open_menu, width=3)
        self.menu_btn.pack(side="left", padx=4)

        composer = tk.Frame(self.root, bg=self.colors["surface"], height=76)
        composer.pack(fill="x", side="bottom")
        composer.pack_propagate(False)

        self.image_btn = tk.Button(
            composer,
            text="＋",
            command=self.send_image,
            bg=self.colors["surface2"],
            fg=self.colors["text"],
            activebackground=self.colors["primary"],
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 16, "bold"),
            cursor="hand2",
            padx=10,
            pady=6,
        )
        self.image_btn.pack(side="left", padx=(14, 6), pady=14)

        self.message_entry = tk.Entry(
            composer,
            bg=self.colors["surface2"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            relief="flat",
            font=("Segoe UI", 12),
        )
        self.message_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=14, ipady=10)
        self.message_entry.bind("<Return>", lambda e: self.send_message())
        self.message_entry.bind("<KeyRelease>", self.on_typing)
        self.message_entry.focus_set()

        self.send_btn = tk.Button(
            composer,
            text="Send",
            command=self.send_message,
            bg=self.colors["primary"],
            fg="white",
            activebackground=self.colors["primary_dark"],
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            padx=14,
            pady=8,
        )
        self.send_btn.pack(side="right", padx=(0, 14), pady=14)

        self.typing_label = tk.Label(
            self.root,
            text="",
            bg=self.colors["bg"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10, "italic"),
        )
        self.typing_label.pack(fill="x", side="bottom", padx=14, pady=(0, 4))

        chat_container = tk.Frame(self.root, bg=self.colors["bg"])
        chat_container.pack(fill="both", expand=True, side="top")

        self.chat_canvas = tk.Canvas(chat_container, bg=self.colors["bg"], highlightthickness=0)
        self.chat_scroll = tk.Scrollbar(chat_container, orient="vertical", command=self.chat_canvas.yview)
        self.chat_frame = tk.Frame(self.chat_canvas, bg=self.colors["bg"])

        self.chat_frame.bind(
            "<Configure>",
            lambda e: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all")),
        )

        self.chat_window = self.chat_canvas.create_window((0, 0), window=self.chat_frame, anchor="nw")
        self.chat_canvas.bind("<Configure>", self.resize_chat_frame)
        self.chat_canvas.configure(yscrollcommand=self.chat_scroll.set)

        self.chat_canvas.pack(side="left", fill="both", expand=True)
        self.chat_scroll.pack(side="right", fill="y")

        composer.lift()

        self.add_bubble(
            "Welcome to PyChat. Host a room or connect to a friend on your network.",
            "System",
            "system",
        )

    def header_button(self, parent, text, command, width=None):
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg=self.colors["surface2"],
            fg=self.colors["text"],
            activebackground=self.colors["primary"],
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            padx=10,
            pady=6,
        )

    def resize_chat_frame(self, event):
        self.chat_canvas.itemconfig(self.chat_window, width=event.width)

    def add_bubble(self, text, sender="System", kind="incoming", receipt_text=None):
        outer = tk.Frame(self.chat_frame, bg=self.colors["bg"])

        if kind == "outgoing":
            outer.pack(fill="x", padx=12, pady=6, anchor="e")
            bg = self.colors["outgoing"]
            side = "right"
            anchor = "e"
        elif kind == "system":
            outer.pack(fill="x", padx=12, pady=6)
            bg = self.colors["system"]
            side = "top"
            anchor = "center"
        else:
            outer.pack(fill="x", padx=12, pady=6, anchor="w")
            bg = self.colors["incoming"]
            side = "left"
            anchor = "w"

        bubble = tk.Frame(outer, bg=bg)
        bubble.pack(side=side, anchor=anchor, padx=4)

        tk.Label(
            bubble,
            text=sender,
            bg=bg,
            fg="#DDE8F1",
            font=("Segoe UI", 9, "bold"),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(8, 0))

        tk.Label(
            bubble,
            text=text,
            bg=bg,
            fg="white",
            font=("Segoe UI", 11),
            justify="left",
            wraplength=360,
        ).pack(anchor="w", padx=12, pady=(2, 4))

        tk.Label(
            bubble,
            text=receipt_text or "",
            bg=bg,
            fg="#DDE8F1",
            font=("Segoe UI", 8),
        ).pack(anchor="e", padx=12, pady=(0, 8))

        self.root.after(50, lambda: self.chat_canvas.yview_moveto(1.0))
        return bubble

    def add_image_bubble(self, image_data, filename, sender="System", kind="incoming", receipt_text=None):
        outer = tk.Frame(self.chat_frame, bg=self.colors["bg"])

        if kind == "outgoing":
            outer.pack(fill="x", padx=12, pady=6, anchor="e")
            bg = self.colors["outgoing"]
            side = "right"
            anchor = "e"
        else:
            outer.pack(fill="x", padx=12, pady=6, anchor="w")
            bg = self.colors["incoming"]
            side = "left"
            anchor = "w"

        bubble = tk.Frame(outer, bg=bg)
        bubble.pack(side=side, anchor=anchor, padx=4)

        tk.Label(
            bubble,
            text=sender,
            bg=bg,
            fg="#DDE8F1",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(8, 4))

        try:
            raw = base64.b64decode(image_data)
            temp_path = f"pychat_temp_{int(time.time() * 1000)}.png"

            with open(temp_path, "wb") as file:
                file.write(raw)

            img = tk.PhotoImage(file=temp_path)

            max_width = 280
            if img.width() > max_width:
                scale = max(1, img.width() // max_width)
                img = img.subsample(scale, scale)

            self.image_refs.append(img)

            img_label = tk.Label(bubble, image=img, bg=bg, cursor="hand2")
            img_label.pack(anchor="w", padx=12, pady=(2, 6))
            img_label.bind("<Button-1>", lambda e: self.save_received_image(raw, filename))

            try:
                os.remove(temp_path)
            except OSError:
                pass

        except Exception:
            tk.Label(
                bubble,
                text=f"[Image: {filename}]",
                bg=bg,
                fg="white",
                font=("Segoe UI", 11),
            ).pack(anchor="w", padx=12, pady=(2, 6))

        tk.Label(
            bubble,
            text=receipt_text or "",
            bg=bg,
            fg="#DDE8F1",
            font=("Segoe UI", 8),
        ).pack(anchor="e", padx=12, pady=(0, 8))

        self.root.after(50, lambda: self.chat_canvas.yview_moveto(1.0))

    def save_received_image(self, raw, filename):
        file_path = filedialog.asksaveasfilename(
            title="Save image",
            initialfile=filename,
            defaultextension=".png",
            filetypes=[
                ("PNG image", "*.png"),
                ("GIF image", "*.gif"),
                ("All files", "*.*"),
            ],
        )

        if file_path:
            with open(file_path, "wb") as file:
                file.write(raw)

            messagebox.showinfo(APP_NAME, "Image saved.")

    def open_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Change username", command=self.change_username)
        menu.add_command(label="Save chat", command=self.save_chat_text)
        menu.add_separator()
        menu.add_command(label="Disconnect", command=self.disconnect_all)
        menu.add_command(label="Exit", command=self.on_close)
        menu.tk_popup(self.menu_btn.winfo_rootx(), self.menu_btn.winfo_rooty() + 32)

    def host_dialog(self):
        port = simpledialog.askinteger(
            "Host PyChat",
            "Port:",
            initialvalue=DEFAULT_PORT,
            minvalue=1,
            maxvalue=65535,
        )
        if port:
            self.start_server(port)

    def connect_dialog(self):
        host = simpledialog.askstring("Connect to PyChat", "Host IP address:")
        if not host:
            return

        port = simpledialog.askinteger(
            "Connect to PyChat",
            "Port:",
            initialvalue=DEFAULT_PORT,
            minvalue=1,
            maxvalue=65535,
        )
        if port:
            self.connect_to_host(host.strip(), port)

    def change_username(self):
        name = simpledialog.askstring("Username", "Enter your username:", initialvalue=self.username)

        if not name:
            return

        name = name.strip()

        if not name:
            return

        if " " in name or len(name) > 24:
            messagebox.showerror("Invalid username", "Use 1-24 characters and no spaces.")
            return

        self.username = name
        self.add_bubble(f"Your username is now {self.username}.", "System", "system")

    def on_typing(self, event=None):
        now = time.time()

        if now - self.last_typing_sent < 1:
            return

        self.last_typing_sent = now

        packet = {
            "type": "typing",
            "sender": self.username,
            "time": now,
        }

        self.broadcast_packet(packet)

    def start_server(self, port):
        if self.server_socket:
            messagebox.showinfo(APP_NAME, "A server is already running.")
            return

        def server_thread():
            try:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind(("", port))
                self.server_socket.listen(5)

                self.queue_system(f"Hosting on port {port}.")
                self.set_status(f"Hosting :{port}")

                while self.running:
                    try:
                        conn, addr = self.server_socket.accept()
                        self.connections.append(conn)
                        self.queue_system(f"Connected: {addr[0]}")

                        threading.Thread(
                            target=self.receive_loop,
                            args=(conn, addr[0]),
                            daemon=True,
                        ).start()

                    except OSError:
                        break

            except OSError as error:
                self.queue_system(f"Could not host: {error}")
                self.server_socket = None

        threading.Thread(target=server_thread, daemon=True).start()

    def connect_to_host(self, host, port):
        def client_thread():
            try:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                conn.settimeout(8)
                conn.connect((host, port))
                conn.settimeout(None)

                self.connections.append(conn)
                self.queue_system(f"Connected to {host}:{port}")
                self.set_status(f"Connected to {host}")

                threading.Thread(
                    target=self.receive_loop,
                    args=(conn, host),
                    daemon=True,
                ).start()

            except OSError as error:
                self.queue_system(f"Connection failed: {error}")

        threading.Thread(target=client_thread, daemon=True).start()

    def receive_loop(self, conn, label):
        while self.running:
            try:
                packet = self.recv_packet(conn)

                if not packet:
                    break

                packet_type = packet.get("type", "message")
                sender = packet.get("sender", label)

                if packet_type == "message":
                    text = packet.get("text", "")

                    if text:
                        self.msg_queue.put(("message", sender, text))

                        read_packet = {
                            "type": "read",
                            "sender": self.username,
                            "time": time.time(),
                        }
                        self.send_packet(conn, read_packet)

                elif packet_type == "image":
                    filename = packet.get("filename", "image.png")
                    image_data = packet.get("image", "")

                    if image_data:
                        self.msg_queue.put(("image", sender, filename, image_data))

                        read_packet = {
                            "type": "read",
                            "sender": self.username,
                            "time": time.time(),
                        }
                        self.send_packet(conn, read_packet)

                elif packet_type == "typing":
                    self.msg_queue.put(("typing", sender, ""))

                elif packet_type == "read":
                    reader = packet.get("sender", "Someone")
                    self.msg_queue.put(("system", "System", f"Read by {reader}"))

            except OSError:
                break
            except Exception as error:
                self.queue_system(f"Receive error: {error}")
                break

        self.remove_connection(conn)
        self.queue_system(f"Disconnected: {label}")

    def send_message(self):
        text = self.message_entry.get().strip()

        if not text:
            return

        self.message_entry.delete(0, "end")
        self.add_bubble(text, self.username, "outgoing", "Sent")

        packet = {
            "type": "message",
            "sender": self.username,
            "text": text,
            "time": time.time(),
        }

        self.broadcast_packet(packet)

        if not self.connections:
            self.add_bubble(
                "Message shown locally. You are not connected to anyone yet.",
                "System",
                "system",
            )

    def send_image(self):
        file_path = filedialog.askopenfilename(
            title="Choose image",
            filetypes=[
                ("Images", "*.png *.gif"),
                ("PNG files", "*.png"),
                ("GIF files", "*.gif"),
                ("All files", "*.*"),
            ],
        )

        if not file_path:
            return

        try:
            file_size = os.path.getsize(file_path)

            if file_size > 2 * 1024 * 1024:
                messagebox.showerror(APP_NAME, "Image is too large. Please choose an image under 2 MB.")
                return

            with open(file_path, "rb") as file:
                raw = file.read()

            image_data = base64.b64encode(raw).decode("utf-8")
            filename = os.path.basename(file_path)

            self.add_image_bubble(image_data, filename, self.username, "outgoing", "Sent")

            packet = {
                "type": "image",
                "sender": self.username,
                "filename": filename,
                "image": image_data,
                "time": time.time(),
            }

            self.broadcast_packet(packet)

            if not self.connections:
                self.add_bubble(
                    "Image shown locally. You are not connected to anyone yet.",
                    "System",
                    "system",
                )

        except Exception as error:
            messagebox.showerror(APP_NAME, f"Could not send image: {error}")

    def broadcast_packet(self, packet):
        dead_connections = []

        for conn in list(self.connections):
            try:
                self.send_packet(conn, packet)
            except OSError:
                dead_connections.append(conn)

        for conn in dead_connections:
            self.remove_connection(conn)

    def send_packet(self, conn, payload):
        data = json.dumps(payload).encode("utf-8")
        header = f"{len(data):0{HEADER_SIZE}d}".encode("ascii")
        conn.sendall(header + data)

    def recv_packet(self, conn):
        header = self.recv_exact(conn, HEADER_SIZE)

        if not header:
            return None

        size = int(header.decode("ascii"))
        data = self.recv_exact(conn, size)

        if not data:
            return None

        return json.loads(data.decode("utf-8"))

    def recv_exact(self, conn, size):
        chunks = b""

        while len(chunks) < size:
            part = conn.recv(size - len(chunks))

            if not part:
                return None

            chunks += part

        return chunks

    def remove_connection(self, conn):
        try:
            conn.close()
        except OSError:
            pass

        if conn in self.connections:
            self.connections.remove(conn)

        if not self.connections and not self.server_socket:
            self.set_status("Offline")

    def disconnect_all(self):
        for conn in list(self.connections):
            self.remove_connection(conn)

        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass

            self.server_socket = None

        self.set_status("Offline")
        self.add_bubble("Disconnected.", "System", "system")

    def queue_system(self, text):
        self.msg_queue.put(("system", "System", text))

    def set_status(self, text):
        self.msg_queue.put(("status", "", text))

    def clear_typing_label_later(self):
        if self.typing_clear_job:
            self.root.after_cancel(self.typing_clear_job)

        self.typing_clear_job = self.root.after(2500, lambda: self.typing_label.config(text=""))

    def poll_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                kind = item[0]

                if kind == "message":
                    _, sender, text = item
                    self.add_bubble(text, sender, "incoming")

                elif kind == "image":
                    _, sender, filename, image_data = item
                    self.add_image_bubble(image_data, filename, sender, "incoming")

                elif kind == "system":
                    _, sender, text = item
                    self.add_bubble(text, sender, "system")

                elif kind == "status":
                    _, sender, text = item
                    self.status_label.config(text=text)

                elif kind == "typing":
                    _, sender, text = item
                    self.typing_label.config(text=f"{sender} is typing...")
                    self.clear_typing_label_later()

        except queue.Empty:
            pass

        if self.running:
            self.root.after(100, self.poll_queue)

    def save_chat_text(self):
        file_path = filedialog.asksaveasfilename(
            title="Save chat",
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )

        if not file_path:
            return

        lines = []

        for bubble_group in self.chat_frame.winfo_children():
            for bubble in bubble_group.winfo_children():
                labels = bubble.winfo_children()

                if len(labels) >= 2:
                    sender = labels[0].cget("text")
                    try:
                        text = labels[1].cget("text")
                    except Exception:
                        text = "[Image]"
                    lines.append(f"{sender}: {text}")

        with open(file_path, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))

        messagebox.showinfo(APP_NAME, "Chat saved.")

    def on_close(self):
        self.running = False

        for conn in list(self.connections):
            self.remove_connection(conn)

        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass

        self.root.destroy()


def main():
    root = tk.Tk()
    PyChatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()