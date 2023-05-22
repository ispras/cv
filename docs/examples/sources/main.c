#include <stdlib.h>

const size_t STR_SIZE=10;

void fill_string(char *str) {
    for (size_t i = 0; i < STR_SIZE; ++i) {
        str[i] = i + 1;
    }
}

int execute(const char *str) {
    int nondet;
    // main function
    if (nondet) {
        return 1;
    }
    return 0;
}

int memory_leak()
{
    char *str;
    // Dynamically allocate memory for str
    str = (char*)malloc(STR_SIZE * sizeof(int));

    if (str == NULL) {
        // Exit if memory was not allocated
        return 1;
    }
    fill_string(str);
    if (execute(str)) {
        // Exit in case of error
        // Memory leak: free(str) is missing here!
        return 1;
    }
    // Free allocated memory
    free(str);
    return 0;
}

int no_memory_leak()
{
    char *str;
    // Dynamically allocate memory for str
    str = (char*)malloc(STR_SIZE * sizeof(int));

    if (str == NULL) {
        // Exit if memory was not allocated
        return 1;
    }
    fill_string(str);
    if (execute(str)) {
        // Exit in case of error
        free(str);
        return 1;
    }
    // Free allocated memory
    free(str);
    return 0;
}

int main() {
    int nondet;
    if (nondet) {
        if (memory_leak()) {
            return 1;
        }
    } else {
        if (no_memory_leak()) {
            return 1;
        }
    }
    return 0;
}