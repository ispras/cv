#!/bin/bash

set -e

branch=$1
inst=${branch}-svn

if [ -z ${branch} ];
then
    echo "Usage: <branch>"
    exit 1
fi
echo "CPAchecker branch '${branch}' will be installed"

echo "Cleaning previously installed version"
rm -rf ${branch}

cd ${inst}

echo "Building CPAchecker"
# ant clean - fails at first time
ant build tar
tar -xf CPAchecker-*

echo "Copying installed directory"
mv CPAchecker-*/ ../${branch}
cd ..

echo "Installation has been successfully completed"
