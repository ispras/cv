#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define INSTALL_CGROUPS_SCRIPT "./install_cgroups.sh"

int main()
{
  int ret;

  if (setuid(0) == -1) {
    printf("Couldn't change user ID to root: %s\n", strerror(errno));
    return errno;
  }

  if((ret = system(INSTALL_CGROUPS_SCRIPT)) == -1) {
    printf("Couldn't execute" INSTALL_CGROUPS_SCRIPT ": %s\n", strerror(errno));
    return errno;
  }

  if (WEXITSTATUS(ret)) {
    printf("Something went wrong during execution of script " INSTALL_CGROUPS_SCRIPT "\n");
    return WEXITSTATUS(ret);
  }

  printf("Control groups were installed successfully\n");
  return 0;
}
