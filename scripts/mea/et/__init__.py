#
# CV is a framework for continuous verification.
# This module was based on Klever-CV repository (https://github.com/mutilin/klever/tree/cv-v2.0).
#
# Copyright (c) 2018-2023 ISP RAS (http://www.ispras.ru)
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
# pylint: disable=invalid-name
"""
This library is intended for witnesses parsing.
"""

from mea.et.parser import WitnessParser
from mea.et.tmpvars import generic_simplifications


def import_error_trace(logger, witness, source_dir=None):
    """
    Main function for importing a witness into the CV internal format
    """
    # Parse a witness.
    witness_parser = WitnessParser(logger, witness, source_dir)
    internal_witness = witness_parser.internal_witness

    # Remove ugly code
    if internal_witness.witness_type != "correctness":
        generic_simplifications(logger, internal_witness)

    # Process notes (such as property checks, property violations and environment comments)
    internal_witness.process_verifier_notes()

    # Do final checks
    internal_witness.final_checks(witness_parser.entry_point)

    return internal_witness.serialize()


# This is intended for testing purposes, when one has a witness and would like to debug its
# transformations.
if __name__ == '__main__':
    import json
    import logging
    import sys

    gl_logger = logging.getLogger()
    gl_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s (%(filename)s:%(lineno)03d) %(levelname)5s> %(message)s', '%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    gl_logger.addHandler(handler)

    et = import_error_trace(gl_logger, 'witness.0.graphml')

    with open('error internal_witness.json', 'w', encoding='utf8') as fp:
        json.dump(et, fp, ensure_ascii=False, sort_keys=True, indent="\t")
