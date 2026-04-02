import tkinter as tk
import sys
import os

# ── Spellcaster Darktable Splash Screen ──
# Shown while ComfyUI processes a workflow. Displays the branded splash
# image with an animated progress overlay and a breathing opacity effect.
# Exits when the lock file is deleted by the Lua plugin.

# Theme constants
_BG = '#0B0715'
_ACCENT = '#D122E3'
_TEXT = '#E2DFEB'
_SUBTEXT = '#8B7CA8'
_FONTS = ("Segoe UI", "Inter", "Cantarell", "Arial")

def _best_font(size=16, bold=False):
    """Return a font tuple using the first available font family."""
    weight = "bold" if bold else "normal"
    return (_FONTS[0], size, weight)


def show_splash():
    if len(sys.argv) < 2:
        print("Usage: splash.py <lock_file_path>")
        sys.exit(1)

    lock_file = sys.argv[1]

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.configure(bg=_BG)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(script_dir, "installer_background.png")

    root.splash_img = None
    target = 500  # desired max dimension in pixels

    # ── Main container ──
    container = tk.Frame(root, bg=_BG, bd=0)
    container.pack(fill='both', expand=True)

    # ── Image section ──
    try:
        img = tk.PhotoImage(file=img_path)
        factor = max(1, max(img.width(), img.height()) // target)
        if factor > 1:
            img = img.subsample(factor, factor)
        root.splash_img = img
        img_label = tk.Label(container, image=root.splash_img, bd=0, bg=_BG)
        img_label.pack(padx=0, pady=0)
        img_width, img_height = root.splash_img.width(), root.splash_img.height()
    except Exception:
        img_label = None
        img_width, img_height = 420, 0

    # ── Overlay bar at the bottom ──
    overlay = tk.Frame(container, bg=_BG, padx=12, pady=8)
    overlay.pack(fill='x')

    # Title label
    title_label = tk.Label(
        overlay,
        text="Spellcaster",
        font=_best_font(14, bold=True),
        fg=_ACCENT,
        bg=_BG,
        anchor='w'
    )
    title_label.pack(fill='x')

    # Status message (animated)
    status_label = tk.Label(
        overlay,
        text="Processing with AI...",
        font=_best_font(11),
        fg=_TEXT,
        bg=_BG,
        anchor='w'
    )
    status_label.pack(fill='x')

    # ── Progress bar ──
    bar_frame = tk.Frame(overlay, bg='#21153B', height=4, bd=0)
    bar_frame.pack(fill='x', pady=(6, 0))
    bar_frame.pack_propagate(False)

    progress_bar = tk.Frame(bar_frame, bg=_ACCENT, height=4, width=0, bd=0)
    progress_bar.place(x=0, y=0, relheight=1.0)

    # Total window size
    width = max(img_width, 420)
    height = img_height + 60  # 60px for the overlay bar
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw / 2) - (width / 2)
    y = (sh / 2) - (height / 2)
    root.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')

    # ── Animated progress messages ──
    messages = [
        "Processing with AI...",
        "Generating magic...",
        "Applying neural spells...",
        "Compositing result...",
        "Almost there...",
    ]
    msg_state = {'idx': 0}

    def cycle_message():
        msg_state['idx'] = (msg_state['idx'] + 1) % len(messages)
        status_label.configure(text=messages[msg_state['idx']])
        root.after(3000, cycle_message)

    root.after(3000, cycle_message)

    # ── Progress bar indeterminate animation ──
    bar_state = {'pos': 0, 'dir': 1, 'segment_width': 120}

    def animate_bar():
        bar_width = bar_frame.winfo_width()
        if bar_width < 10:
            bar_width = width
        seg = bar_state['segment_width']
        bar_state['pos'] += bar_state['dir'] * 4
        if bar_state['pos'] + seg >= bar_width:
            bar_state['dir'] = -1
        elif bar_state['pos'] <= 0:
            bar_state['dir'] = 1
        progress_bar.place(x=bar_state['pos'], y=0, width=seg, relheight=1.0)
        root.after(30, animate_bar)

    root.after(100, animate_bar)

    # ── Breathing / pulsing opacity on the title ──
    # Simulate pulsing by cycling the title color brightness
    pulse_state = {'step': 0}
    _PULSE_COLORS = []
    # Pre-compute 40 color steps: from accent (#D122E3) dimmed to bright and back
    for i in range(20):
        t = i / 19.0  # 0.0 .. 1.0
        r = int(140 + t * (209 - 140))
        g = int(20 + t * (34 - 20))
        b = int(160 + t * (227 - 160))
        _PULSE_COLORS.append(f'#{r:02x}{g:02x}{b:02x}')
    _PULSE_COLORS += list(reversed(_PULSE_COLORS))

    def pulse_title():
        pulse_state['step'] = (pulse_state['step'] + 1) % len(_PULSE_COLORS)
        title_label.configure(fg=_PULSE_COLORS[pulse_state['step']])
        root.after(80, pulse_title)

    root.after(200, pulse_title)

    # ── Lock file polling ──
    def check_lock():
        if not os.path.exists(lock_file):
            root.destroy()
        else:
            root.after(1000, check_lock)

    root.after(1000, check_lock)
    root.mainloop()


if __name__ == "__main__":
    show_splash()
