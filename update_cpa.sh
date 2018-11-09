#!/usr/bin/env bash

verifiercloud_dir=$1
branches=()
revisions=()
while read line; do
    conf=( ${line} )
    branch=${conf[0]}
    branches+=("${branch}")
    revision=${conf[1]}
    revisions+=("${revision}")
done <./cpa.config

cd tools
for (( i=0; i<${#revisions[@]}; i++ ));
do
    branch=${branches[$i]}
    revision=${revisions[$i]}
    echo $branch
    ../download_cpa.sh ${branch} ${revision}
    ../install_cpa.sh ${branch}
done
cd ..

if [[ ! -z ${verifiercloud_dir} ]];
then
    ./create_cloud_links.sh ${verifiercloud_dir}
fi
