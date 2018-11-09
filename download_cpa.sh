#!/bin/bash

set -e

branch=$1
revision=$2
inst=${branch}-svn
if [ -z ${revision} ];
then
    echo "Usage: <branch> <revision>"
    exit 1
fi
echo "CPAchecker branch '${branch}', revision '${revision}' will be downloaded"

echo "Cleaning previously downloaded version"
rm -rf ${inst}

if [ ${branch} != 'trunk' ]; then
link="https://svn.sosy-lab.org/software/cpachecker/branches/"
else
link="https://svn.sosy-lab.org/software/cpachecker/"
fi

echo "Downloading CPAchecker"
svn co ${link}${branch} ${inst}
cd ${inst}

echo "Using revision '${revision}'"
svn up -r${revision}

patch=../../patches/tools/cpachecker/${branch}.patch
if [ ! -f ${patch} ];
then
    echo "There is no patch for this branch"
else
    echo "Applying patch '${patch}'"
    svn patch ${patch}
fi
cd ..

