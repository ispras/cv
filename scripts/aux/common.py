import os
import sys


def wait_for_launches(processes):
    try:
        for process in processes:
            if process:
                process.join()
    except:
        kill_launches(processes)


def kill_launches(processes):
    for process in processes:
        if process:
            os.kill(process.pid, 9)
    wait_for_launches(processes)
    sys.exit(0)


class NestedLoop(Exception):
    pass
