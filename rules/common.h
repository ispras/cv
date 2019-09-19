/*
CV is a framework for continuous verification.

Copyright (c) 2018-2019 ISP RAS (http://www.ispras.ru)
Ivannikov Institute for System Programming of the Russian Academy of Sciences

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

#ifndef __VERIFIER_COMMON_H
#define __VERIFIER_COMMON_H

#define ldv_check_model_state(expr) ((expr) ? 0 : ldv_error_location())

/* This is error function - is it is reached, the checked rule is violated */
static void ldv_error_location(void);

/* Stop verification */
void ldv_stop_execution(void)
{
  STOP: goto STOP;
}

void exit(int status)
{
  ldv_stop_execution();
}

#endif /* __VERIFIER_COMMON_H */