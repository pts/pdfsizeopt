/*
 * pdfsizeopt_winstub.c: Start Python on Win32.
 * by pts@fazekas.hu at Wed Jun 27 14:07:04 CEST 2012
 *
 * Compile with: i586-mingw32msvc-gcc -mconsole -s -W -Wall -o ../pdfsizeopt.exe pdfsizeopt_winstub.c
 */

#include <errno.h>
#include <limits.h>  // PATH_MAX is 259.
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define FILE_SEP '\\'
#define PATH_SEP ';'

#define ARGV_MAX 1000

static char is_in_dir(const char *file, const char *p, const char *q) {
  struct stat st;
  char pathname[PATH_MAX + 1];
  int len = (q - p) + 1 + strlen(file);
  if (len > PATH_MAX) len = PATH_MAX;
  strncpy(pathname, p, q - p);
  if (len > q - p) {
    pathname[q - p] = FILE_SEP;
    strncpy(pathname + (q - p) + 1, file, len - (q - p) - 1);
  } else {
    if (q - p < PATH_MAX) pathname[q - p] = '\0';
  }
  pathname[len] = '\0';
  return 0 == stat(pathname, &st) && S_ISREG(st.st_mode);
}

static char is_file(const char *pathname) {
  struct stat st;
  return 0 == stat(pathname, &st) && S_ISREG(st.st_mode);
}

static void find_on_path(const char *prog, char *dir_out) {
  const char *path = getenv("PATH"), *p, *q;
  if (path != NULL || *path != '\0') {
    p = path;
    while (*p != '\0') {
      while (*p == PATH_SEP) {
        ++p;
      }
      if (*p == '\0') break;
      q = p;
      while (*q != '\0' && *q != PATH_SEP) ++q;
      if (is_in_dir(prog, p, q)) {
        if (q - p > PATH_MAX) {
          q = p + PATH_MAX;
        }
        memcpy(dir_out, p, q - p);
        dir_out[q - p] = '\0';
        return;
      }
      p = q;
    }
  }
  *dir_out = '\0';
}

/* FILE_SEP inlined here. */
static const char python_exe[] = "pdfsizeopt_win32exec\\pdfsizeopt_python.exe";
static const char pdfsizeopt_py0[] = "pdfsizeopt";
static const char pdfsizeopt_py1[] = "pdfsizeopt.single";

int main(int argc, char **argv) {
  char python_bin[PATH_MAX + 1], argv0_bin[PATH_MAX + 1], *p, *q;
  char prog_py[PATH_MAX + 2];
  const char *moreargv[ARGV_MAX + 1];
  int i;
  (void)argc;
  p = argv[0];
  q = NULL;
  while (*p != '\0') {
    if (*p++ == FILE_SEP) q = p;
  }
  if (q == NULL) {  // Try to find argv[0] on $PATH.
    p = argv[0];
    strncpy(argv0_bin, p, sizeof argv0_bin);
    q = NULL;
    while (*p != '\0') {
      if (*p++ == '.') q = p;
    }
    if (q == NULL) {
      argv0_bin[sizeof argv0_bin - 5] = '\0';
      strcat(argv0_bin, ".exe");
    } else {
      argv0_bin[sizeof argv0_bin - 1] = '\0';
    }
    find_on_path(argv0_bin, python_bin);
  } else {  // Put dirname(argv[0]) to python_bin.
    p = argv[0];
    --q;
    if (q - p > PATH_MAX) {
      q = p + PATH_MAX;
    }
    strncpy(python_bin, p, q - p);
    python_bin[q - p] = '\0';
  }

  if (python_bin[0] == '\0') {
    python_bin[0] = '.';
    python_bin[1] = '\0';
  }
  strcpy(prog_py, python_bin);

  i = strlen(python_bin);
  if (i + strlen(python_exe) > PATH_MAX) {
    i = PATH_MAX - strlen(python_exe);
  }
  python_bin[i] = FILE_SEP;
  strcpy(python_bin + i + 1, python_exe);

  i = strlen(prog_py);
  if (i + strlen(pdfsizeopt_py0) > PATH_MAX) {
    i = PATH_MAX - strlen(pdfsizeopt_py0);
  }
  if (i + strlen(pdfsizeopt_py1) > PATH_MAX) {
    i = PATH_MAX - strlen(pdfsizeopt_py0);
  }
  prog_py[i++] = FILE_SEP;
  strcpy(prog_py + i, pdfsizeopt_py0);
  if (!is_file(prog_py)) {
    strcpy(prog_py + i, pdfsizeopt_py1);
    if (!is_file(prog_py)) {
      fprintf(stderr, "error: Python script missing: %s\n", prog_py);
    }
  }

  moreargv[0] = "python26";
  moreargv[1] = prog_py;
  for (i = 1; argv[i] != NULL; ++i) {
    moreargv[i + 1] = argv[i];
  }
  moreargv[i + 1] = NULL;

  // execv(...) and P_OVERLAY don't work well in wine-1.2.2 and Windows XP,
  // because they make this process return before the started process finishes.
  i = spawnv(P_WAIT, python_bin, moreargv);
  if (i < 0) {
    fprintf(stderr, "error: could not start %s: %s\n",
            python_bin, strerror(errno));
    return 120;
  }
  return i;
}
