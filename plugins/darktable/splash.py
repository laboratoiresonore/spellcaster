import tkinter as tk
import sys
import os

def show_splash():
    if len(sys.argv) < 2:
        print("Usage: splash.py <lock_file_path>")
        sys.exit(1)
        
    lock_file = sys.argv[1]
    
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(script_dir, "darktable_splash.png")
    
    root.splash_img = None
    try:
        root.splash_img = tk.PhotoImage(file=img_path)
        label = tk.Label(root, image=root.splash_img, bd=0, bg='black')
        label.pack()
    except Exception:
        label = tk.Label(root, text="Processing with Spellcaster...", font=("Arial", 16), fg="white", bg="black")
        label.pack(padx=20, pady=20)
        
    root.update_idletasks()
    width = 400
    height = 400
    
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw/2) - (width/2)
    y = (sh/2) - (height/2)
    root.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')
    
    def check_lock():
        if not os.path.exists(lock_file):
            root.destroy()
        else:
            root.after(1000, check_lock)
            
    # Start checking
    root.after(1000, check_lock)
    root.mainloop()

if __name__ == "__main__":
    show_splash()
