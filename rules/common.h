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