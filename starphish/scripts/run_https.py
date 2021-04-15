import subprocess
import time
import signal

while True:
    try:
        proc = subprocess.Popen("python -m starphish", shell=True, executable='/bin/bash')
        for _ in range(0, 3600, 2):
            time.sleep(2)
        proc.send_signal(signal.SIGINT)
        time.sleep(5)
        if proc.poll() is None:
            proc.terminate()
            time.sleep(5)
        print("=======Restarting========")
    except KeyboardInterrupt:
        print("=======Stopping=========")
        proc.send_signal(signal.SIGINT)
        time.sleep(5)
        if proc.poll() is None:
            proc.terminate()
        break
