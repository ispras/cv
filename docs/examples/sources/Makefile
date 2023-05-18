CC=gcc
CFLAGS="-g"
SOURCE_FILE=main.c
DST_FILE=main

default: all

all: $(SOURCE_FILE)
	@$(CC) $(CFLAGS) -o $(DST_FILE) $(SOURCE_FILE)

clean:
	@rm -f $(DST_FILE)
