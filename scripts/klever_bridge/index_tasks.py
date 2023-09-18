#!/usr/bin/python3
#
# CV is a framework for continuous verification.
#
# Copyright (c) 2018-2023 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""
Module for indexing klever tasks in its working directory.
"""

import glob
import json
import os
import re
import sys

CIL_FILE = "cil.i"
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
JOBS_FILE = os.path.join(SCRIPT_DIR, os.path.pardir, os.path.pardir, ".klever_jobs_index.json")
TASKS_FILE = os.path.join(SCRIPT_DIR, os.path.pardir, os.path.pardir, ".klever_tasks_index.json")

PROP_NAMING = {
    "memory safety": "smg",
    "memory safety with mea": "smg",
    "concurrency safety": "sync:races"
}


def __parse_args():
    if len(sys.argv) < 2:
        sys.exit(f"Usage: ./{os.path.basename(__file__)} <path to tasks directory>")
    return sys.argv[1]


def _iterate_over_tasks(tasks_dir: str, jobs: dict, tasks: dict):
    job_dir = os.path.realpath(os.path.join(tasks_dir, os.pardir, "jobs"))
    tasks_dir_list = glob.glob(os.path.join(tasks_dir, "*"))
    tasks_num = len(tasks_dir_list)
    counter = 0
    prev_percent = 0
    attrs_to_tasks = {}

    def _save_attrs(cur_task_id):
        attrs = "&&&".join(tasks[cur_task_id])
        if attrs not in attrs_to_tasks:
            attrs_to_tasks[attrs] = []
        attrs_to_tasks[attrs].append(cur_task_id)

    def _get_job_from_attrs(str_attrs: str) -> str:
        attrs = str_attrs.split("&&&")
        return attrs[2]

    for task_dir in tasks_dir_list:
        cil_file = os.path.join(task_dir, CIL_FILE)
        task_id = os.path.basename(task_dir)
        counter += 1
        percent = int(100 * counter / tasks_num)
        if prev_percent != percent:
            prev_percent = percent
            print(f"Tasks processed {counter} ({percent}%)")
        if task_id in tasks:
            _save_attrs(task_id)
            continue
        if os.path.exists(cil_file):
            with open(cil_file, encoding="utf8", errors='ignore') as cil_fp:
                for line in cil_fp.readlines():
                    if "vtg" not in line or "emg" not in line:
                        continue
                    res = re.search(
                        rf"{job_dir}/(.+)/klever-core-work-dir/job/vtg/(.+)\.ko/(.+)/emg", line
                    )
                    if res:
                        new_job_id = res.group(1)
                        module = res.group(2) + ".ko"
                        prop = res.group(3)
                        prop = PROP_NAMING.get(prop, prop)
                        task_attrs = [module, prop, new_job_id]
                        # if not _check_attrs(task_attrs):
                        if new_job_id not in jobs:
                            jobs[new_job_id] = []
                        jobs[new_job_id].append(task_id)
                        tasks[task_id] = task_attrs
                        _save_attrs(task_id)
                        break
    for target_attrs, task_ids in attrs_to_tasks.items():
        if len(task_ids) > 1:
            target_job_id = _get_job_from_attrs(target_attrs)
            transformed_list = sorted([int(t_id) for t_id in task_ids])
            for elem in transformed_list[:-1]:
                elem = str(elem)
                if elem in jobs[target_job_id]:
                    jobs[target_job_id].remove(elem)


def _save_index(jobs: dict, tasks: dict):
    def _proc_single_file(file_name: str, content: dict):
        with open(file_name, "w", encoding="ascii") as index_fp:
            json.dump(content, index_fp, ensure_ascii=True, indent="\t")
    _proc_single_file(JOBS_FILE, jobs)
    _proc_single_file(TASKS_FILE, tasks)


def _upload_index() -> tuple:
    def _proc_single_file(file_name: str) -> dict:
        if os.path.exists(file_name):
            with open(file_name, "r", encoding="ascii") as index_fp:
                return json.load(index_fp, parse_int=int)
        return {}
    jobs = _proc_single_file(JOBS_FILE)
    tasks = _proc_single_file(TASKS_FILE)
    return jobs, tasks


def index_klever_tasks(tasks_dir: str) -> tuple:
    """
    Upload index cache and update it.
    """
    jobs, tasks = _upload_index()
    _iterate_over_tasks(tasks_dir, jobs, tasks)
    _save_index(jobs, tasks)
    return jobs, tasks


if __name__ == '__main__':
    TASK_DIR_NAME = __parse_args()
    TASK_DIR_NAME = os.path.abspath(TASK_DIR_NAME)
    index_klever_tasks(TASK_DIR_NAME)
