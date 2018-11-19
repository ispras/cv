#!/usr/bin/env bash

plugin_dir=$1
plugin=$2
is_multiple_plugins=$3
cv_dir=`pwd`
verifier_patches_dir="patches/tools/cpachecker"
tmp_patch="__tmp.patch"

if [ -z ${plugin} ];
then
    echo "Usage: <plugin directory> <plugin id>"
    exit 1
fi

echo "Installing plugin '${plugin}' into Continuous Verification system found in '${cv_dir}'"

special_directories=(configs docs entrypoints patches/preparation patches/sources rules verifier_files/options verifier_files/properties)
echo "Updating special directories"
for dir in ${special_directories[@]};
do
    src_dir=${plugin_dir}/${dir}/${plugin}
    dst_dir=${cv_dir}/${dir}
    if [ -d "${src_dir}" ]; then
        if [ -d "${dst_dir}" ]; then
            echo "Copying directory '${src_dir}' into '${dst_dir}'"
            ln -sf ${src_dir} ${dst_dir}
        else
            echo "Warning: directory '${dst_dir}' does not exist"
        fi
    else
        echo "Warning: directory '${src_dir}' does not exist"
    fi
done

verifier_patches=$(ls ${plugin_dir}/${verifier_patches_dir}/${plugin})
if [ -n "${verifier_patches}" ]; then
    echo "Updating verifier patches"
    for patch in ${verifier_patches[@]};
    do
        src_patch=${plugin_dir}/${verifier_patches_dir}/${plugin}/${patch}
        dst_patch=${cv_dir}/${verifier_patches_dir}/${patch}
        if [ -e "${dst_patch}" ]; then
            if [ -z "${is_multiple_plugins}" ];
            then
                git checkout -- ${verifier_patches_dir}/${patch}
            fi
            echo "Updating verifier patch ${dst_patch} by ${src_patch}"
            cat ${dst_patch} ${src_patch} > ${tmp_patch}
            mv ${tmp_patch} ${dst_patch}
        else
            echo "Warning: patch '${dst_patch}' does not exist"
        fi
    done
else
    echo "Could not find verifier patches to update"
fi
