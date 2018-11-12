#!/usr/bin/env bash

verifier_patches_dir="patches/tools/cpachecker"

echo "Removing all installed plugins"

special_directories=(configs docs entrypoints patches/preparation patches/sources rules verifier_files/options)
echo "Cleaning special directories"
for dir in ${special_directories[@]};
do
    find ${dir} -type l -delete
done

echo "Restoring verifier patches"
git checkout -- ${verifier_patches_dir}/*
