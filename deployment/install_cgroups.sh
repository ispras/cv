#!/usr/bin/env bash
#
# CV is a framework for continuous verification.
#
# Copyright (c) 2018-2019 ISP RAS (http://www.ispras.ru)
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

if cat /proc/mounts | grep "cgroup" &> /dev/null; then
    echo "Control groups are already installed"
else
    echo "Installing control groups"
    sudo mount -t cgroup none /sys/fs/cgroup
fi

special_directories=(
'/sys/fs/cgroup/cpuset/'
'/sys/fs/cgroup/freezer/'
'/sys/fs/cgroup/blkio/'
'/sys/fs/cgroup/cpu,cpuacct/'
'/sys/fs/cgroup/cpuacct/'
'/sys/fs/cgroup/memory/'
'/sys/fs/cgroup/cpu,cpuacct/user.slice'
'/sys/fs/cgroup/memory/user.slice'
'/sys/fs/cgroup'
)

for dir in ${special_directories[@]};
do
    if [ -d "${dir}" ]; then
        echo "Changing directory '${dir}' permissions"
        sudo chmod o+wt ${dir}
    fi
done
