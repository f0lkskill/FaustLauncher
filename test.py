import pystray
from PIL import Image, ImageDraw
import tkinter as tk
import threading

def create_tray_icon():
    """创建托盘图标图像"""
    width, height = 64, 64
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    # 绘制一个绿色圆形
    draw.ellipse((16, 16, 48, 48), fill='green')
    return image

class TrayApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("托盘应用示例")
        self.root.geometry("400x300")
        
        # 创建主窗口内容
        self.label = tk.Label(self.root, text="点击下方按钮最小化到托盘", font=("Arial", 12))
        self.label.pack(pady=30)
        
        self.minimize_btn = tk.Button(self.root, text="最小化到托盘", command=self.minimize)
        self.minimize_btn.pack(pady=10)
        
        self.quit_btn = tk.Button(self.root, text="退出程序", command=self.quit)
        self.quit_btn.pack(pady=10)
        
        self.tray_icon = None
    
    def minimize(self):
        """最小化到托盘"""
        self.root.withdraw()  # 隐藏主窗口
        self.create_tray()
    
    def create_tray(self):
        """创建托盘图标"""
        def on_left_click(icon, item):
            """左键点击事件：显示主窗口"""
            self.show_window()
        
        def on_quit(icon, item):
            """退出事件"""
            icon.stop()
            self.root.quit()
        
        # 创建菜单
        menu = pystray.Menu(
            pystray.MenuItem('显示窗口', self.show_window, ),
            pystray.MenuItem('退出', on_quit)
        )
        
        # 创建托盘图标
        self.tray_icon = pystray.Icon(
            'tray_app',
            create_tray_icon(),
            '托盘应用示例',
            menu
        )
        
        # 在单独线程中运行托盘图标
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
    
    def show_window(self, icon=None, item=None):
        """显示主窗口"""
        self.root.after(0, lambda: (
            self.root.deiconify(),  # 显示窗口
            self.root.lift()  # 提升到前台
        ))
    
    def quit(self):
        """退出程序"""
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()
    
    def run(self):
        """运行应用"""
        self.root.mainloop()

if __name__ == "__main__":
    app = TrayApp()
    app.run()