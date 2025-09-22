# Continuous Verification Framework - processing and managing verification results.
# Repository: https://github.com/ispras/cv
#
# Copyright © 2025 Vitalii Mordan, ISP RAS
#
# SPDX-License-Identifier: Apache-2.0

cpu_cores=$(shell nproc)


# Additional tools.
cvv="cvv"

# Directories
root_dir=$(shell pwd)
install_dir=tools
cvv_dir=${install_dir}/${cvv}
project_dir=cv
tools_config_file=${install_dir}/config.json

# Repositories
cvv_repo_1="https://gitlab.ispras.ru/verification/cvv.git"
cvv_repo_2="https://github.com/ispras/cv-visualizer.git"

# Aux constants.
cvv_branch=master

all: build

download-cvv:
	@$(call download_tool,${cvv},${cvv_dir},${cvv_repo_1},${cvv_repo_2})
	@cd ${cvv_dir}; git checkout ${cvv_branch}; git pull

build-cvv: download-cvv
	@echo "*** Building ${cvv} ***"
	@echo "from web.development import *" > ${cvv_dir}/web/web/settings.py
	@echo "{}" > ${cvv_dir}/web/web/db.json

build: build-cvv
	@echo "*** Building has been completed ***"

download: download-cvv
	@echo "*** Downloading has been completed ***"

check-deploy-dir:
	@$(call check_dir,${DEPLOY_DIR},DEPLOY_DIR)

install-cvv: build-cvv check-deploy-dir
	@echo "*** Installing ${cvv} ***"
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}
	@cp -r ${cvv_dir} ${DEPLOY_DIR}/${cvv_dir}
	@$(call shrink_installation,${DEPLOY_DIR}/${cvv_dir})

deploy-cvv: build-cvv check-deploy-dir
	@echo "*** Deploying ${cvv} web-interface ***"
	@rm -rf ${DEPLOY_DIR}
	@mkdir -p ${DEPLOY_DIR}
	@cp -r ${cvv_dir} ${DEPLOY_DIR}
	@$(call shrink_installation,${DEPLOY_DIR})

install-scripts: check-deploy-dir
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@cp ${tools_config_file} ${DEPLOY_DIR}/${install_dir}
	@cp -r ${root_dir}/${project_dir} ${DEPLOY_DIR}

install-witness-visualizer: check-deploy-dir build-cvv install-scripts
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}
	@cp -r ${cvv_dir} ${DEPLOY_DIR}/${cvv_dir}
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}/web/static/codemirror
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}/web/static/calendar
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}/web/static/jstree
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}/web/static/js/population.js
	@echo "*** Witness Visualizer has been successfully installed into the directory ${DEPLOY_DIR} ***"

install-mea: check-deploy-dir
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@cp ${tools_config_file} ${DEPLOY_DIR}/${install_dir}
	@mkdir -p ${DEPLOY_DIR}/${project_dir}/components
	@cp -r ${root_dir}/${project_dir}/mea ${DEPLOY_DIR}/${project_dir}
	@cp -r ${root_dir}/${project_dir}/models ${DEPLOY_DIR}/${project_dir}
	@cp -r ${root_dir}/${project_dir}/aux ${DEPLOY_DIR}/${project_dir}
	@cp ${root_dir}/${project_dir}/components/__init__.py ${DEPLOY_DIR}/${project_dir}/components
	@cp ${root_dir}/${project_dir}/components/component.py ${DEPLOY_DIR}/${project_dir}/components
	@cp ${root_dir}/${project_dir}/components/mea.py ${DEPLOY_DIR}/${project_dir}/components
	@cp ${root_dir}/${project_dir}/mea.py ${DEPLOY_DIR}/${project_dir}/
	@echo "*** MEA has been successfully installed into the directory ${DEPLOY_DIR} ***"

install: check-deploy-dir install-cvv install-scripts
	@echo "*** Successfully installed into the directory ${DEPLOY_DIR}' ***"

clean:
	@echo "*** Removing old installation ***"
	@rm -rf ${cvv_dir}


# download_tool(name, path, repository_1, mirror_repository)
define download_tool
	if [ -d "$2" ]; then \
		echo "*** Tool $1 is already downloaded in directory $2 ***"; \
	else \
		echo "*** Downloading tool $1 into directory $2 ***"; \
		if ! git clone --recursive "$3" "$2"; then \
			echo "*** Primary repo failed, trying fallback: $4 ***"; \
			if ! git clone --recursive "$4" "$2"; then \
				echo "*** ERROR: Failed to download tool $1 from both sources ***"; \
				exit 1; \
			fi; \
		fi; \
	fi; \
	cd "$2" && git fetch --all --tags --prune
endef

# $1 - absolute directory path, $2 - env variable name, $3 - aux options
define check_dir
	if [ -n "$1" ]; then \
		if [ "$1" -ef "${root_dir}" ]; then \
			echo "Specified directory path '$1' is the same as current directory"; \
			false ; \
		else \
			if [ "$3" = "is_exist" ] ; then \
				if [ -d "$1" ] ; then \
					true ; \
				else \
					echo "Specified directory path '$1' does not exist. Add correct path to the '$2' environment variable"; \
					false; \
				fi ; \
			else \
				true ; \
			fi \
		fi ; \
	else \
		echo "Required variable '$2' was not specified"; \
		false; \
	fi
endef

# $1 - deploy directory
define shrink_installation
	echo "Removing aux files in directory '$1'"
	@cd ${1} && rm -rf .git .idea
endef
