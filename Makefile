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

cpu_cores=$(shell nproc)


# Additional tools.
cvv="cvv"
cil="cil"
frama_c_cil="frama_c_cil"
benchexec="benchexec"
cif="cif"

# Scripts
bv_script="process_benchmark.py"
bridge_script="bridge.py"
wv_script="visualize_witnesses.py"
launch_script="launch.py"
auto_script="auto_check.py"
bridge_script="bridge.py"

# Directories
root_dir=$(shell pwd)
install_dir=tools
cvv_dir=${install_dir}/${cvv}
mea_lib=web/reports/mea/core.py
cil_dir=${install_dir}/${cil}
frama_c_cil_dir=${install_dir}/${frama_c_cil}
benchexec_dir=${install_dir}/${benchexec}
cif_dir=${install_dir}/${cif}
plugin_dir="plugin"
deployment_dir="deployment"

compiled_cif_arch="cif.xz"
cil_arch="cil.xz"
compiled_cil_arch="frama_c_cil.xz"

# Repositories
cvv_repo="https://gitlab.ispras.ru/verification/cvv.git"
benchexec_repo="https://github.com/sosy-lab/benchexec.git"
cif_repo="https://github.com/ldv-klever/cif.git"
cif_compiled_link="https://github.com/ldv-klever/cif/releases/download/v1.2/linux-x86_64-cif-1.2.tar.xz"
cil_compiled_link="https://forge.ispras.ru/attachments/download/9905/frama-c-cil-c012809.tar.xz"

# Aux constants.
cvv_branch=master
benchexec_branch=3.16
cif_revision=master

tools_config_file=${install_dir}/config.json


download-cvv:
	@$(call download_tool,${cvv},${cvv_dir},${cvv_repo})
	@cd ${cvv_dir}; git checkout ${cvv_branch}; git pull

download-benchexec:
	@$(call download_tool,${benchexec},${benchexec_dir},${benchexec_repo})
	@cd ${benchexec_dir}; git checkout ${benchexec_branch}

download-cif:
	@$(call download_tool,${cif},${cif_dir},${cif_repo})
	@cd ${cif_dir}; git checkout ${cif_revision}; git submodule update

download-cif-compiled:
	@rm -f ${compiled_cif_arch}
	@cd ${install_dir}; wget ${cif_compiled_link} -O ${compiled_cif_arch}

download-frama-c-cil:
	@rm -f ${compiled_cil_arch}
	@cd ${install_dir}; wget ${cil_compiled_link} -O ${compiled_cil_arch}

download: download-cvv download-benchexec download-cpa
	@echo "*** Downloading has been completed ***"

build-cvv: download-cvv
	@echo "*** Building ${cvv} ***"
	@echo "from web.development import *" > ${cvv_dir}/web/web/settings.py
	@echo "{}" > ${cvv_dir}/web/web/db.json

build-benchexec: download-benchexec
	@echo "*** Building ${benchexec} ***"
	@cd ${benchexec_dir}; ./setup.py build

build-cif: download-cif
	@echo "*** Building ${cif} ***"
	@cd ${cif_dir}; make -j ${cpu_cores}

build-cif-compiled: download-cif-compiled
	@echo "*** Building compiled ${cif} ***"
	@rm -rf ${cif_dir}
	@cd ${install_dir}; tar -xf ${compiled_cif_arch}

build-cil:
	@echo "*** Building ${cil} ***"
	@rm -rf ${cil_dir}
	@cd ${install_dir}; tar -xf ${cil_arch}

build-frama-c-cil: download-frama-c-cil
	@echo "*** Building ${frama_c_cil} ***"
	@rm -rf ${frama_c_cil_dir}
	@mkdir -p ${frama_c_cil_dir}
	@cd ${frama_c_cil_dir}; tar -xf ../${compiled_cil_arch}

build: build-cvv build-benchexec build-cil build-cpa
	@echo "*** Building has been completed ***"

clean-cpa:
	@./build_cpa.py -m clean

custom-build-cpa:
	@./build_cpa.py -m custom

build-cpa:
	@./build_cpa.py -m build

download-cpa:
	@./build_cpa.py -m download

install-cpa:
	@./build_cpa.py -m install -i ${DEPLOY_DIR}

check-deploy-dir:
	@$(call check_dir,${DEPLOY_DIR},DEPLOY_DIR)


install-cvv: build-cvv check-deploy-dir
	@echo "*** Installing ${cvv} ***"
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}
	@cp -r ${cvv_dir} ${DEPLOY_DIR}/${cvv_dir}
	@mkdir -p ${DEPLOY_DIR}/scripts/aux
	@$(call shrink_installation,${DEPLOY_DIR}/${cvv_dir})

deploy-cvv: build-cvv check-deploy-dir
	@echo "*** Deploying ${cvv} web-interface ***"
	@mkdir -p ${DEPLOY_DIR}
	@rm -rf ${DEPLOY_DIR}
	@cp -r ${cvv_dir} ${DEPLOY_DIR}
	@$(call shrink_installation,${DEPLOY_DIR})

install-benchexec: build-benchexec check-deploy-dir
	@echo "*** Installing ${benchexec} ***"
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${benchexec_dir}
	@cp -r ${benchexec_dir} ${DEPLOY_DIR}/${benchexec_dir}

install-cil: build-cil check-deploy-dir
	@echo "*** Installing ${cil} ***"
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${cil_dir}
	@cp -r ${cil_dir} ${DEPLOY_DIR}/${cil_dir}

install-frama-c-cil: build-frama-c-cil check-deploy-dir
	@echo "*** Installing ${frama_c_cil} ***"
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${frama_c_cil_dir}
	@cp -r ${frama_c_cil_dir} ${DEPLOY_DIR}/${frama_c_cil_dir}

install-cif: build-cif check-deploy-dir
	@echo "*** Installing ${cif} ***"
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${cif_dir}
	@cd ${cif_dir}; DESTDIR=$(realpath ${DEPLOY_DIR})/${cif_dir} make install

install-cif-compiled: build-cif-compiled check-deploy-dir
	@echo "*** Installing compiled ${cif} ***"
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${cif_dir}
	@cp -r ${cif_dir} ${DEPLOY_DIR}/${cif_dir}

install-scripts: check-deploy-dir
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@mkdir -p ${root_dir}/${plugin_dir}
	@cp ${tools_config_file} ${DEPLOY_DIR}/${install_dir}
	@cd ${DEPLOY_DIR} ; \
	cp -r ${root_dir}/patches/ . ; \
	cp -r ${root_dir}/properties/ . ; \
	cp -r ${root_dir}/entrypoints/ . ; \
	cp -r ${root_dir}/configs/ . ; \
	cp -r ${root_dir}/scripts/ . ; \
	rm -f scripts/${bv_script} ; \
	rm -f scripts/${wv_script} ; \
	cp -r ${root_dir}/${plugin_dir} . ; \
	mkdir -p buildbot

install-witness-visualizer: check-deploy-dir build-cvv
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@cp ${tools_config_file} ${DEPLOY_DIR}/${install_dir}
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}
	@cp -r ${cvv_dir}/web ${DEPLOY_DIR}/${cvv_dir}
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}/web/static/codemirror
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}/web/static/calendar
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}/web/static/jstree
	@rm -rf ${DEPLOY_DIR}/${cvv_dir}/web/static/js/population.js
	@cd ${DEPLOY_DIR} ; \
	cp -r ${root_dir}/scripts/ . ; \
	rm -f scripts/${launch_script} ; \
	rm -f scripts/${auto_script} ; \
	rm -f scripts/${bv_script}
	@echo "*** Witness Visualizer has been successfully installed into the directory ${DEPLOY_DIR} ***"

install-mea: check-deploy-dir
	@mkdir -p ${DEPLOY_DIR}/${install_dir}
	@cp ${tools_config_file} ${DEPLOY_DIR}/${install_dir}
	@cd ${DEPLOY_DIR} ; \
	cp -r ${root_dir}/scripts/ . ; \
	rm -f scripts/${launch_script} ; \
	rm -f scripts/${auto_script} ; \
	rm -f scripts/${bv_script} ; \
	rm -f scripts/${bridge_script} ; \
	rm -rf scripts/coverage ; \
	rm -rf scripts/models/ ; \
	rm -rf scripts/klever_bridge ; \
	rm -f scripts/${wv_script} ; \
	rm -f scripts/aux/opts.py
	@cd ${DEPLOY_DIR}/scripts/components; \
	rm main_generator.py exporter.py builder.py benchmark_launcher.py qualifier.py launcher.py preparator.py coverage_processor.py full_launcher.py
	@echo "*** MEA has been successfully installed into the directory ${DEPLOY_DIR} ***"

install-benchmark-visualizer: install-witness-visualizer
	@cp -r ${cvv_dir}/utils/ ${DEPLOY_DIR}/${cvv_dir}/
	@cp -f ${root_dir}/scripts/${bv_script} ${DEPLOY_DIR}/scripts/

install-klever-bridge: install-witness-visualizer
	@cp -r ${cvv_dir}/utils/ ${DEPLOY_DIR}/${cvv_dir}/
	@cp -f ${root_dir}/scripts/${bridge_script} ${DEPLOY_DIR}/scripts/
	@echo "*** Klever bridge has been successfully installed into the directory ${DEPLOY_DIR} ***"

install: check-deploy-dir install-cvv install-benchexec install-cil install-cpa install-scripts install-cpa
	@$(call verify_installation,${DEPLOY_DIR})
	@echo "*** Successfully installed into the directory ${DEPLOY_DIR}' ***"

install-with-cloud: check-deploy-dir install-cvv install-benchexec install-cil install-cpa-with-cloud-links install-scripts
	@$(call verify_installation,${DEPLOY_DIR})
	@echo "*** Successfully installed into the directory ${DEPLOY_DIR}' with access to verification cloud ***"

install-cpa-with-cloud-links: | check-deploy-dir install-cpa
	@$(call check_dir,${VCLOUD_DIR},"VCLOUD_DIR","is_exist")
#	@for cpa in ${cpa_modes}; do \
#		cd "${DEPLOY_DIR}/${install_dir}/$${cpa}" ; \
#		mkdir -p lib/java-benchmark/ ; \
#		cp ${VCLOUD_DIR}/vcloud.jar lib/java-benchmark/ ; \
#	done
	@echo "*** Successfully created links for verification cloud in CPAchecker installation directories ***"

install-plugin:
	@$(call check_dir,${PLUGIN_DIR},"PLUGIN_DIR","is_exist")
	@$(call check_dir,${PLUGIN_ID},"PLUGIN_ID")
	@echo "*** Installing plugin '${PLUGIN_ID}' into directory '${plugin_dir}/${PLUGIN_ID}' ***"
	@if [ -d "${plugin_dir}/${PLUGIN_ID}" ]; then \
		echo "*** Removing old plugin installation '${plugin_dir}/${PLUGIN_ID}' ***" ; \
	fi
	@mkdir -p ${plugin_dir}
	@ln -s ${PLUGIN_DIR} ${plugin_dir}/${PLUGIN_ID}

install-control-groups-daemon:
	@sudo cp ${deployment_dir}/cgroups-boot /etc/init.d/
	@sudo chown root:root /etc/init.d/cgroups-boot
	@sudo update-rc.d cgroups-boot defaults

delete-plugins:
	@echo "*** Removing all installed plugins ***"
	@rm -rf plugin/*

clean:
	@echo "*** Removing old installation ***"
	@rm -rf ${install_dir}
	@git checkout -- ${install_dir}/

verify-installation: check-deploy-dir
	@$(call verify_installation,${DEPLOY_DIR})

# download_tool(name, path, repository)
define download_tool
	if [ -d "$2" ]; then \
		echo "*** Tool $1 is already downloaded in directory $2 ***" ; \
	else \
		echo "*** Downloading tool $1 into directory $2 ***" ; \
		git clone --recursive $3 $2 ; \
	fi
	cd $2; git fetch
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
define verify_installation
	echo "Verifying installation in directory '$1'"
	for tool in ${benchexec} ${cvv}; do \
		if [ -d "${1}/${install_dir}/$${tool}" ]; then \
			echo "Tool '$${tool}' is installed" ; \
		else \
			echo "Something went wrong during installation: tool '$${tool}' is not found in directory '${1}/${install_dir}."; \
			exit 1; \
		fi ; \
	done
endef

# $1 - deploy directory
define shrink_installation
	echo "Removing aux files in directory '$1'"
	@cd ${1} && rm -rf .git .idea
endef
