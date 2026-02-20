import subprocess
import threading

def run_bot():
    subprocess.run(["python", "bot.py"])

def run_monitor():
    subprocess.run(["python", "monitor.py"])

t1 = threading.Thread(target=run_bot)
t2 = threading.Thread(target=run_monitor)

t1.start()
t2.start()

t1.join()
t2.join()
