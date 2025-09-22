"""
Common functions.
"""

import os
import sys


def wait_for_launches(processes):
    """
    Wait for all created processes.
    """
    try:
        for process in processes:
            if process:
                process.join()
    except Exception as exception:
        print(f"Killing all processes due to {exception}")
        kill_launches(processes)


def kill_launches(processes):
    """
    Kill all created processes.
    """
    for process in processes:
        if process:
            os.kill(process.pid, 9)
    wait_for_launches(processes)
    sys.exit(0)


def update_symlink(abs_path: str):
    """
    Update symlinks in benchmark directory.
    """
    rel_path = os.path.basename(abs_path)
    # Remove old link.
    if os.path.islink(rel_path):
        os.remove(rel_path)
    # Do not create link for current directory.
    if not os.path.exists(rel_path):
        os.symlink(abs_path, rel_path)


def clear_symlink(abs_path: str):
    """
    Clear symlinks in benchmark directory.
    """
    if not abs_path:
        return
    rel_path = os.path.basename(abs_path)
    if os.path.islink(rel_path):
        os.remove(rel_path)


class NestedLoop(Exception):
    """
    Exception for exiting nested loops.
    """
