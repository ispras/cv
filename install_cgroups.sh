#!/usr/bin/env bash

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
