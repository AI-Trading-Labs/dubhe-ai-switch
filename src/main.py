import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gui import App
if __name__ == "__main__":
    app = App()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        if app._running:
            app.runner.stop()
        os._exit(0)
