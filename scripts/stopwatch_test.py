
import tkinter as tk
import time

root = tk.Tk()
root.title("Stopwatch")
root.resizable(True, True)

start_time = None
running = False
elapsed_offset = 0.0  # For pause/resume functionality

label = tk.Label(root, text="0.000", font=("Helvetica", 80))
label.pack(padx=40, pady=40)

def update():
    if running:
        elapsed = time.perf_counter() - start_time + elapsed_offset
        # Convert to milliseconds and use integer division to avoid floating point rounding issues
        elapsed_ms = int(elapsed * 1000)
        seconds = elapsed_ms // 1000
        milliseconds = elapsed_ms % 1000
        label.config(text=f"{seconds}.{milliseconds:03d}")
        root.after(5, update)  # Update every 5ms - balance between smooth display and 60fps camera readability

def start():
    global start_time, running
    if not running:
        running = True
        start_time = time.perf_counter()
        update()

def stop():
    global running, elapsed_offset
    if running:
        elapsed_offset += time.perf_counter() - start_time
        running = False

def reset():
    if not running:
        global start_time, elapsed_offset
        elapsed_offset = 0.0
        start_time = None
        label.config(text="0.000")
        

# Button frame for better layout
button_frame = tk.Frame(root)
button_frame.pack(pady=10)

tk.Button(button_frame, text="Start", width=10, command=start).pack(side="left", padx=5)
tk.Button(button_frame, text="Stop",  width=10, command=stop).pack(side="left", padx=5)
tk.Button(button_frame, text="Reset", width=10, command=reset).pack(side="left", padx=5)

root.mainloop()

