#!/usr/bin/env bash

verifiercloud_dir=$1
if [ -z ${verifiercloud_dir} ];
then
    echo "Usage: <verifiercloud_dir>"
    exit 1
fi

cd tools

while read line; do
    conf=( ${line} )
    branch=${conf[0]}
    cd ${branch}
    rm -rf lib/java-benchmark/
    mkdir -p lib/java-benchmark/
    cp ${verifiercloud_dir}/vcloud.jar lib/java-benchmark/
    cd ..
done <../cpa.config
cd ..
