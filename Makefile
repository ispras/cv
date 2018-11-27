#!/bin/bash

# Additional tools.
klever=klever
clade=clade
cil=cil
benchexec=benchexec
cif=cif

# Directories
root_dir=$(shell pwd)
patches_dir=../../patches/tools/
install_dir=tools
klever_dir=${install_dir}/${klever}
clade_dir=${install_dir}/${clade}
cil_dir=${install_dir}/${cil}
benchexec_dir=${install_dir}/${benchexec}
cif_dir=${install_dir}/${cif}
cif_inst_dir=${install_dir}/${cif}_install

.PHONY: all

all: clean download cpa-install deploy install
	
download: clean 
	@echo "*** Downloading ${klever} ***"
	@rm -rf ${klever_dir}
	git clone https://github.com/mutilin/klever.git ${klever_dir}
	cd ${klever_dir}; git checkout cv
	
	@echo "*** Downloading ${clade} ***"
	@rm -rf ${clade_dir}
	git clone https://github.com/mutilin/clade.git ${clade_dir}
	cd ${clade_dir}; git checkout cv
	
	@echo "*** Downloading ${cil} ***"
	@rm -rf ${cil_dir}
	cd ${install_dir}; tar -xf cil.xz
	
	@echo "*** Downloading ${benchexec} ***"
	@rm -rf ${benchexec_dir}
	git clone https://github.com/sosy-lab/benchexec.git ${benchexec_dir}
	
	@echo "*** Downloading ${cif} ***"
	@rm -rf ${cif_inst_dir}
	git clone --recursive https://forge.ispras.ru/git/cif.git ${cif_inst_dir}
	cd ${cif_inst_dir}; git checkout ca907524; git submodule update

install: download
	@echo "*** Installing ${clade} ***"
	cd ${clade_dir}; pip3 install --user -e .
	
	@echo "*** Installing ${cif} ***"
	cd ${cif_inst_dir}; make -j8; prefix=${root_dir}/${cif_dir} make install
	@if [ -z ${DEBUG} ]; then \
		echo "*** Removing installation directories for ${cif} ***" ; \
		rm -rf ${cif_inst_dir}; \
	fi
	
cpa-install: clean
	./update_cpa.sh
	@if [ -z ${DEBUG} ]; then \
		echo "*** Removing installation directories for CPAchecker ***" ; \
		rm -rf ${install_dir}/*-svn/ ; \
	fi
	
deploy:
	@if [ -n "${DEPLOY_DIR}" ]; then \
		echo "*** Deploying into the ${DEPLOY_DIR}' ***" ; \
		mkdir -p ${DEPLOY_DIR} ; \
		cd ${DEPLOY_DIR} ; \
		ln -sf ${root_dir}/verifier_files/ . ; \
		ln -sf ${root_dir}/patches/ . ; \
		ln -sf ${root_dir}/rules/ . ; \
		ln -sf ${root_dir}/tools/ . ; \
		ln -sf ${root_dir}/entrypoints/ . ; \
		ln -sf ${root_dir}/configs/ . ; \
		ln -sf ${root_dir}/scripts/ . ; \
		mkdir -p buildbot ; \
	else \
		echo "Specified deploy path '${DEPLOY_DIR}' does not exist. Add correct path to the 'DEPLOY_DIR' variable"; \
	fi

clean:
	@echo "*** Removing old installation ***"
	@rm -rf ${install_dir}
	@git checkout -- ${install_dir}/

